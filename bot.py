import os
import sqlite3
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TOKEN = os.environ.get("DISCORD_TOKEN")

# Replace this with your Discord user ID.
ECONOMY_ADMINS = {219111589247320066,212859793138909184}

CURRENCY_NAME = "Ryo"
GUILD_ID = 1528476084176162977
DB_PATH = BASE_DIR / "/app/data/economy.db"

# Village economy accounts
VILLAGES = {
    "konoha": "Hidden Leaf (Konoha)",
    "suna": "Hidden Sand (Suna)",
    "kiri": "Hidden Mist (Kiri)",
    "kumo": "Hidden Cloud (Kumo)",
    "iwa": "Hidden Stone (Iwa)",
    "ame": "Rain Village (Amegakure)",
    "taki": "Waterfall Village (Takigakure)",
}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    conn = db()

    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER NOT NULL DEFAULT 0
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS villages (
        village_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        balance INTEGER NOT NULL DEFAULT 0
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS characters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        village_id TEXT NOT NULL,
        rank TEXT NOT NULL,
        user_id INTEGER NOT NULL
    )""")

    for village_id, name in VILLAGES.items():
        conn.execute(
            "INSERT OR IGNORE INTO villages (village_id, name, balance) VALUES (?, ?, 0)",
            (village_id, name)
        )

    conn.commit()
    conn.close()


def ensure_user(user_id):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO users (user_id,balance) VALUES (?,0)", (user_id,))
    conn.commit()
    conn.close()


def get_balance(user_id):
    ensure_user(user_id)
    conn = db()
    row = conn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row["balance"]


def transaction(user_id, amount, action, admin_id=None, reason=None):
    conn = db()
    conn.execute("""INSERT INTO transactions
        (user_id,amount,action,admin_id,reason,created_at)
        VALUES (?,?,?,?,?,?)""",
        (user_id, amount, action, admin_id, reason,
         datetime.utcnow().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()


def change_balance(user_id, amount, action, admin_id=None, reason=None):
    ensure_user(user_id)
    conn = db()
    conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    transaction(user_id, amount, action, admin_id, reason)


def set_balance(user_id, amount, action, admin_id=None, reason=None):
    old = get_balance(user_id)
    ensure_user(user_id)
    conn = db()
    conn.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    transaction(user_id, amount-old, action, admin_id, reason)

def get_village_balance(village_id):
    conn = db()
    row = conn.execute(
        "SELECT balance FROM villages WHERE village_id = ?",
        (village_id,)
    ).fetchone()
    conn.close()

    if row is None:
        return None

    return row["balance"]


def change_village_balance(village_id, amount, action, admin_id=None, reason=None):
    conn = db()
    conn.execute(
        "UPDATE villages SET balance = balance + ? WHERE village_id = ?",
        (amount, village_id)
    )
    conn.commit()
    conn.close()


def set_village_balance(village_id, amount):
    conn = db()
    conn.execute(
        "UPDATE villages SET balance = ? WHERE village_id = ?",
        (amount, village_id)
    )
    conn.commit()
    conn.close()

def is_admin(user_id):
    return user_id in ECONOMY_ADMINS


class EconomyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        setup_database()
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash commands.")
        except Exception as e:
            print(f"Command sync error: {e}")


bot = EconomyBot()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.tree.command(name="balance", description="Check your Ryo balance.")
async def balance(interaction):
    await interaction.response.send_message(
        f"💰 **{interaction.user.display_name}** has **{get_balance(interaction.user.id):,} Ryo**."
    )


@bot.tree.command(name="leaderboard", description="View the richest players.")
async def leaderboard(interaction):
    conn = db()
    rows = conn.execute("SELECT user_id,balance FROM users ORDER BY balance DESC LIMIT 10").fetchall()
    conn.close()
    if not rows:
        await interaction.response.send_message("No economy data yet.")
        return
    lines = []
    for i, row in enumerate(rows, 1):
        member = interaction.guild.get_member(row["user_id"]) if interaction.guild else None
        name = member.display_name if member else f"User {row['user_id']}"
        lines.append(f"**{i}.** {name} — {row['balance']:,} Ryo")
    await interaction.response.send_message(
        embed=discord.Embed(title="💰 Ryo Leaderboard",
                            description="\n".join(lines),
                            color=discord.Color.gold())
    )


@bot.tree.command(name="transactions", description="View your recent Ryo transactions.")
async def transactions_cmd(interaction):
    conn = db()
    rows = conn.execute("""SELECT amount,action,reason,created_at FROM transactions
                           WHERE user_id=? ORDER BY id DESC LIMIT 10""",
                        (interaction.user.id,)).fetchall()
    conn.close()
    if not rows:
        await interaction.response.send_message("You have no transactions yet.")
        return
    lines = []
    for row in rows:
        sign = "+" if row["amount"] >= 0 else ""
        reason = f" — {row['reason']}" if row["reason"] else ""
        lines.append(f"`{row['created_at']}` **{sign}{row['amount']:,}** Ryo ({row['action']}){reason}")
@bot.tree.command(
    name="village_balance",
    description="Check a village's Ryo treasury."
)
@app_commands.describe(village="Village")
@app_commands.choices(
    village=[
        app_commands.Choice(name=name, value=village_id)
        for village_id, name in VILLAGES.items()
    ]
)
async def village_balance(
    interaction: discord.Interaction,
    village: app_commands.Choice[str]
):
    amount = get_village_balance(village.value)

    if amount is None:
        await interaction.response.send_message(
            "❌ That village does not exist.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"🏯 **{VILLAGES[village.value]}** has **{amount:,} Ryo**."
    )

roster = app_commands.Group(
    name="roster",
    description="Manage and view RP village rosters."
)

@roster.command(
    name="view",
    description="View a village's RP character roster."
)
@app_commands.describe(village="Choose a village")
@app_commands.choices(
    village=[
        app_commands.Choice(name=name, value=village_id)
        for village_id, name in VILLAGES.items()
    ]
)
async def roster_view(
    interaction: discord.Interaction,
    village: app_commands.Choice[str]
):
    conn = db()

    rows = conn.execute("""
        SELECT character_name, rank, user_id
        FROM characters
        WHERE village_id = ?
        ORDER BY rank, character_name
    """, (village.value,)).fetchall()

    conn.close()

    if not rows:
        await interaction.response.send_message(
            f"🏯 **{VILLAGES[village.value]}** currently has no characters registered."
        )
        return

    lines = []

    for row in rows:
        member = interaction.guild.get_member(row["user_id"])
        player = member.mention if member else "Unknown Player"

        lines.append(
            f"**{row['character_name']}** — {row['rank']} — {player}"
        )

    embed = discord.Embed(
        title=f"🏯 {VILLAGES[village.value]} Roster",
        description="\n".join(lines),
        color=discord.Color.gold()
    )

    await interaction.response.send_message(embed=embed)

@roster.command(
    name="add",
    description="Add a character to a village roster."
)
@app_commands.describe(
    character_name="Character's name",
    village="Choose a village",
    rank="Choose the character's rank",
    player="Discord player"
)
@app_commands.choices(
    village=[
        app_commands.Choice(name=name, value=village_id)
        for village_id, name in VILLAGES.items()
    ],
    rank=[
        app_commands.Choice(name="Kage", value="Kage"),
        app_commands.Choice(name="Jonin", value="Jonin"),
        app_commands.Choice(name="Special Jonin", value="Special Jonin"),
        app_commands.Choice(name="Chunin", value="Chunin"),
        app_commands.Choice(name="Genin", value="Genin"),
        app_commands.Choice(name="Academy Student", value="Academy Student"),
        app_commands.Choice(name="Civilian", value="Civilian"),
        app_commands.Choice(name="Missing-Nin", value="Missing-Nin"),
        app_commands.Choice(name="Rogue Ninja", value="Rogue Ninja")
    ]
)
async def roster_add(
    interaction: discord.Interaction,
    character_name: str,
    village: app_commands.Choice[str],
    rank: app_commands.Choice[str],
    player: discord.Member
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ You are not authorized to manage the roster.",
            ephemeral=True
        )
        return

    conn = db()

    conn.execute("""
        INSERT INTO characters
        (character_name, village_id, rank, user_id)
        VALUES (?, ?, ?, ?)
    """, (
        character_name,
        village.value,
        rank.value,
        player.id
    ))

    conn.commit()
    conn.close()

    await interaction.response.send_message(
        f"✅ **{character_name}** has been added to "
        f"**{VILLAGES[village.value]}** as **{rank.value}**.\n"
        f"👤 Player: {player.mention}"
    )

@roster.command(
    name="remove",
    description="Remove a character from a village roster."
)
@app_commands.describe(
    character_name="Name of the character to remove"
)
async def roster_remove(
    interaction: discord.Interaction,
    character_name: str
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ You are not authorized to manage the roster.",
            ephemeral=True
        )
        return

    conn = db()

    character = conn.execute("""
        SELECT id, village_id, rank, user_id
        FROM characters
        WHERE LOWER(character_name) = LOWER(?)
        LIMIT 1
    """, (character_name,)).fetchone()

    if character is None:
        conn.close()
        await interaction.response.send_message(
            f"❌ No character named **{character_name}** was found.",
            ephemeral=True
        )
        return

    conn.execute(
        "DELETE FROM characters WHERE id = ?",
        (character["id"],)
    )

    conn.commit()
    conn.close()

    await interaction.response.send_message(
        f"🗑️ **{character['character_name']}** has been removed from "
        f"**{VILLAGES[character['village_id']]}**."
    )


economy = app_commands.Group(name="economy", description="Admin economy controls.")


@economy.command(name="give", description="Give Ryo to a player.")
@app_commands.describe(user="Player", amount="Amount of Ryo", reason="Optional reason")
async def give(interaction, user: discord.Member, amount: int, reason: str = None):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True); return
    if amount <= 0:
        await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True); return
    change_balance(user.id, amount, "GIVE", interaction.user.id, reason)
    await interaction.response.send_message(f"✅ Gave **{amount:,} Ryo** to {user.mention}.")


@economy.command(name="remove", description="Remove Ryo from a player.")
@app_commands.describe(user="Player", amount="Amount of Ryo", reason="Optional reason")
async def remove(interaction, user: discord.Member, amount: int, reason: str = None):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True); return
    if amount <= 0:
        await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True); return
    current = get_balance(user.id)
    if amount > current:
        await interaction.response.send_message(f"❌ {user.mention} only has **{current:,} Ryo**.", ephemeral=True); return
    change_balance(user.id, -amount, "REMOVE", interaction.user.id, reason)
    await interaction.response.send_message(f"✅ Removed **{amount:,} Ryo** from {user.mention}.")


@economy.command(name="set", description="Set a player's Ryo balance.")
@app_commands.describe(user="Player", amount="New balance", reason="Optional reason")
async def set_cmd(interaction, user: discord.Member, amount: int, reason: str = None):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True); return
    if amount < 0:
        await interaction.response.send_message("Balance cannot be negative.", ephemeral=True); return
    set_balance(user.id, amount, "SET", interaction.user.id, reason)
    await interaction.response.send_message(f"✅ Set {user.mention}'s balance to **{amount:,} Ryo**.")


@economy.command(name="reset", description="Reset a player's Ryo balance to zero.")
@app_commands.describe(user="Player", reason="Optional reason")
async def reset(interaction, user: discord.Member, reason: str = None):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True); return
    set_balance(user.id, 0, "RESET", interaction.user.id, reason)
    await interaction.response.send_message(f"✅ Reset {user.mention}'s balance to **0 Ryo**.")


@economy.command(name="stats", description="View economy statistics.")
async def stats(interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You are not authorized.", ephemeral=True); return
    conn = db()
    users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    total = conn.execute("SELECT COALESCE(SUM(balance),0) t FROM users").fetchone()["t"]
    tx = conn.execute("SELECT COUNT(*) c FROM transactions").fetchone()["c"]
    conn.close()
    embed = discord.Embed(title="📊 Economy Statistics", color=discord.Color.green())
    embed.add_field(name="Players Tracked", value=f"{users:,}")
    embed.add_field(name="Total Ryo", value=f"{total:,}")
    embed.add_field(name="Transactions", value=f"{tx:,}")
    await interaction.response.send_message(embed=embed)

@economy.command(
    name="village-give",
    description="Give Ryo to a village treasury."
)
@app_commands.describe(
    village="Village",
    amount="Amount of Ryo to give",
    reason="Reason for the payment"
)
@app_commands.choices(
    village=[
        app_commands.Choice(name=name, value=village_id)
        for village_id, name in VILLAGES.items()
    ]
)
async def village_give(
    interaction: discord.Interaction,
    village: app_commands.Choice[str],
    amount: int,
    reason: str = "No reason provided"
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ You are not authorized to manage the economy.",
            ephemeral=True
        )
        return

    if amount <= 0:
        await interaction.response.send_message(
            "❌ Amount must be greater than 0.",
            ephemeral=True
        )
        return

    change_village_balance(
        village.value,
        amount,
        "village-give",
        interaction.user.id,
        reason
    )

    new_balance = get_village_balance(village.value)

    await interaction.response.send_message(
        f"✅ Added **{amount:,} Ryo** to "
        f"**{VILLAGES[village.value]}**.\n"
        f"💰 New Treasury Balance: **{new_balance:,} Ryo**\n"
        f"📝 Reason: {reason}"
    )

@economy.command(
    name="village-remove",
    description="Remove Ryo from a village treasury."
)
@app_commands.describe(
    village="Village",
    amount="Amount of Ryo to remove",
    reason="Reason for the removal"
)
@app_commands.choices(
    village=[
        app_commands.Choice(name=name, value=village_id)
        for village_id, name in VILLAGES.items()
    ]
)
async def village_remove(
    interaction: discord.Interaction,
    village: app_commands.Choice[str],
    amount: int,
    reason: str = "No reason provided"
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ You are not authorized to manage the economy.",
            ephemeral=True
        )
        return

    if amount <= 0:
        await interaction.response.send_message(
            "❌ Amount must be greater than 0.",
            ephemeral=True
        )
        return

    current_balance = get_village_balance(village.value)

    if current_balance is None:
        await interaction.response.send_message(
            "❌ That village does not exist.",
            ephemeral=True
        )
        return

    if amount > current_balance:
        await interaction.response.send_message(
            f"❌ **{VILLAGES[village.value]}** only has "
            f"**{current_balance:,} Ryo**.",
            ephemeral=True
        )
        return

    change_village_balance(
        village.value,
        -amount,
        "village-remove",
        interaction.user.id,
        reason
    )

    new_balance = get_village_balance(village.value)

    await interaction.response.send_message(
        f"✅ Removed **{amount:,} Ryo** from "
        f"**{VILLAGES[village.value]}**.\n"
        f"💰 New Treasury Balance: **{new_balance:,} Ryo**\n"
        f"📝 Reason: {reason}"
    )

@economy.command(
    name="village-set",
    description="Set a village treasury to a specific amount."
)
@app_commands.describe(
    village="Village",
    amount="New Ryo balance",
    reason="Reason for changing the balance"
)
@app_commands.choices(
    village=[
        app_commands.Choice(name=name, value=village_id)
        for village_id, name in VILLAGES.items()
    ]
)
async def village_set(
    interaction: discord.Interaction,
    village: app_commands.Choice[str],
    amount: int,
    reason: str = "No reason provided"
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ You are not authorized to manage the economy.",
            ephemeral=True
        )
        return

    if amount < 0:
        await interaction.response.send_message(
            "❌ Amount cannot be negative.",
            ephemeral=True
        )
        return

    current_balance = get_village_balance(village.value)

    if current_balance is None:
        await interaction.response.send_message(
            "❌ That village does not exist.",
            ephemeral=True
        )
        return

    set_village_balance(village.value, amount)

    await interaction.response.send_message(
        f"✅ **{VILLAGES[village.value]}** treasury has been set to "
        f"**{amount:,} Ryo**.\n"
        f"📊 Previous Balance: **{current_balance:,} Ryo**\n"
        f"📝 Reason: {reason}"
    )

@economy.command(
    name="village-reset",
    description="Reset a village treasury to 0 Ryo."
)
@app_commands.describe(
    village="Village",
    reason="Reason for resetting the treasury"
)
@app_commands.choices(
    village=[
        app_commands.Choice(name=name, value=village_id)
        for village_id, name in VILLAGES.items()
    ]
)
async def village_reset(
    interaction: discord.Interaction,
    village: app_commands.Choice[str],
    reason: str = "No reason provided"
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ You are not authorized to manage the economy.",
            ephemeral=True
        )
        return

    current_balance = get_village_balance(village.value)

    if current_balance is None:
        await interaction.response.send_message(
            "❌ That village does not exist.",
            ephemeral=True
        )
        return

    set_village_balance(village.value, 0)

    await interaction.response.send_message(
        f"🔄 **{VILLAGES[village.value]}** treasury has been reset "
        f"to **0 Ryo**.\n"
        f"📊 Previous Balance: **{current_balance:,} Ryo**\n"
        f"📝 Reason: {reason}"
    )

bot.tree.add_command(economy)

bot.tree.add_command(roster)



@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)

    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)

    print(f"Synced {len(synced)} slash commands to Naruto Divided World.")
    print(f"Logged in as {bot.user}")


if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is missing. Add it to Pella Environment Variables or your .env file.")

bot.run(TOKEN)
