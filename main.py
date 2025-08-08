import sys
import types

# ✅ Bypass for audioop crashes
sys.modules['audioop'] = types.ModuleType('audioop')
sys.modules['audioop'].mul = lambda *args, **kwargs: None
sys.modules['audioop'].add = lambda *args, **kwargs: None
sys.modules['audioop'].getsample = lambda *args, **kwargs: 0
sys.modules['audioop'].max = lambda *args, **kwargs: 0
sys.modules['audioop'].minmax = lambda *args, **kwargs: (0, 0)
sys.modules['audioop'].avg = lambda *args, **kwargs: 0
sys.modules['audioop'].avgpp = lambda *args, **kwargs: 0
sys.modules['audioop'].rms = lambda *args, **kwargs: 0
sys.modules['audioop'].cross = lambda *args, **kwargs: 0

import discord, asyncio, requests, os, traceback
from discord.ext import commands, tasks
from discord import app_commands, ui
from datetime import datetime, timedelta
from pymongo import MongoClient
from keep_alive import keep_alive  # ✅ Using separate keep_alive file

keep_alive()  # ✅ Start Flask keepalive server

# ======================= CONFIG =======================
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
PROXY_URL = "https://clash-of-clans-api-4bi0.onrender.com"

LEADERBOARD_PAGE_SIZE = 10
EMOJI_TROPHY = "<:trophy:1400826511799484476>"
EMOJI_OFFENSE = "<:Offence:1400826628099014676>"
EMOJI_DEFENSE = "<:emoji_9:1252010455694835743>"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ======================= MONGO INIT =======================
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["coc_bot"]
players_col = db["players"]
backup_col = db["backup_players"]
players_col.create_index([("trophies", -1)])

# ======================= DB HELPERS =======================
def add_or_update_player(discord_id, tag, data):
    update = {
        "discord_id": discord_id,
        "player_tag": tag,
        "name": data["name"],
        "trophies": data["trophies"],
        "rank": data.get("rank", 0),
        "prev_trophies": data.get("prev_trophies", data["trophies"]),
        "prev_rank": data.get("prev_rank", data["rank"]),
        "attacks": data.get("attacks", 0),
        "defenses": data.get("defenses", 0),
        "offense_trophies": data.get("offense_trophies", 0),
        "offense_attacks": data.get("offense_attacks", 0),
        "defense_trophies": data.get("defense_trophies", 0),
        "defense_defenses": data.get("defense_defenses", 0),
        "last_reset": data.get("last_reset", datetime.now().strftime("%Y-%m-%d"))
    }
    players_col.update_one({"player_tag": tag}, {"$set": update}, upsert=True)
    print(f"✅ Player updated/added: {data['name']} ({tag})")

def get_all_players():
    return list(players_col.find().sort("trophies", -1))

def remove_player(discord_id, tag=None):
    if tag:
        result = players_col.delete_one({"discord_id": discord_id, "player_tag": tag.replace("#", "")})
        print(f"🔁 Removed one: matched={result.deleted_count}")
    else:
        result = players_col.delete_many({"discord_id": discord_id})
        print(f"🔁 Removed all: matched={result.deleted_count}")

# ======================= SAFE API CALL =======================
def fetch_player_data(tag: str):
    tag_encoded = tag if tag.startswith("#") else f"#{tag}"
    tag_encoded = tag_encoded.replace("#", "%23")
    url = f"{PROXY_URL}/player/{tag_encoded}"

    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"❌ HTTP {r.status_code} for {tag} -> {r.text}")
            return None

        data = r.json()
        if not data or "name" not in data or "trophies" not in data:
            print(f"⚠️ Incomplete data for {tag} -> {data}")
            return None

        return {
            "name": data["name"],
            "trophies": data["trophies"],
            "rank": data.get("rank", 0),
            "attacks": len(data.get("attackLog", [])),
            "defenses": len(data.get("defenseLog", []))
        }

    except Exception as e:
        print(f"❌ Exception for {tag}: {e}")
        return None

async def async_fetch_player_data(tag):
    return await asyncio.to_thread(fetch_player_data, tag)

# ======================= BACKGROUND TASKS =======================
@tasks.loop(minutes=1)
async def update_players_data():
    players = get_all_players()
    print(f"\n⏳ Background update: {len(players)} players")
    for player in players:
        try:
            discord_id = player["discord_id"]
            tag = player["player_tag"]

            trophies = player["trophies"]
            rank = player.get("rank", 0)
            off_t = player.get("offense_trophies", 0)
            off_a = player.get("offense_attacks", 0)
            def_t = player.get("defense_trophies", 0)
            def_d = player.get("defense_defenses", 0)

            data = await async_fetch_player_data(tag)
            if data:
                delta = data["trophies"] - trophies
                if delta > 0:
                    off_t += delta
                    off_a += 1
                elif delta < 0:
                    def_t += abs(delta)
                    def_d += 1

                data.update({
                    "prev_trophies": trophies,
                    "prev_rank": rank,
                    "offense_trophies": off_t,
                    "offense_attacks": off_a,
                    "defense_trophies": def_t,
                    "defense_defenses": def_d,
                    "last_reset": datetime.now().strftime("%Y-%m-%d")
                })
                add_or_update_player(discord_id, tag, data)
            else:
                print(f"❌ Failed: {tag}")
        except Exception as e:
            print(f"❌ Error updating {player['player_tag']}: {e}")
    print("✅ Update finished!")

@tasks.loop(minutes=1)
async def reset_offense_defense():
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # Convert UTC to IST
    if now.hour == 10 and now.minute == 30:
        players_col.update_many({}, {
            "$set": {
                "offense_trophies": 0,
                "offense_attacks": 0,
                "defense_trophies": 0,
                "defense_defenses": 0
            }
        })
        print("🔁 Daily offense/defense reset done (10:30 AM IST)")

@tasks.loop(minutes=1)
async def backup_leaderboard():
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # Convert UTC to IST
    if now.hour == 10 and now.minute == 25:
        players = list(players_col.find({}))
        if players:
            backup_col.delete_many({})
            backup_col.insert_many(players)
            print(f"💾 Backup complete with {len(players)} players (10:25 AM IST)")

# ======================= UI LEADERBOARD =======================
class LeaderboardView(ui.View):
    def __init__(self, players, color, name, page=0):
        super().__init__(timeout=None)
        self.players = players
        self.color = color
        self.name = name
        self.page = page

    def get_embed(self):
        start = self.page * LEADERBOARD_PAGE_SIZE
        end = start + LEADERBOARD_PAGE_SIZE
        embed = discord.Embed(title=self.name, color=self.color)

        now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        embed.set_footer(text=f"Last refreshed: {now_ist.strftime('%d-%m-%Y %I:%M %p')}")

        for i, p in enumerate(self.players[start:end], start=start + 1):
            embed.add_field(
                name=f"{i}. {p['name']} (#{p['player_tag']})",
                value=f"{EMOJI_TROPHY} {p['trophies']} | {EMOJI_OFFENSE} +{p.get('offense_trophies', 0)}/{p.get('offense_attacks', 0)} | {EMOJI_DEFENSE} -{p.get('defense_trophies', 0)}/{p.get('defense_defenses', 0)}\n\u200b",
                inline=False
            )
        return embed

    async def update_message(self, interaction):
        await interaction.response.defer()
        self.players = get_all_players()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    @ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction, button):
        if self.page > 0:
            self.page -= 1
            await self.update_message(interaction)

    @ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction, button):
        if (self.page + 1) * LEADERBOARD_PAGE_SIZE < len(self.players):
            self.page += 1
            await self.update_message(interaction)

    @ui.button(label="🔄 Refresh", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction, button):
        await self.update_message(interaction)

# ======================= DISCORD COMMANDS =======================
@bot.tree.command(name="link")
@app_commands.describe(player_tag="Your Clash of Clans player tag (e.g. #8YJ98LV2C)")
async def link(interaction: discord.Interaction, player_tag: str):
    await interaction.response.defer(thinking=True)
    tag = player_tag.replace("#", "").upper()
    data = await async_fetch_player_data(tag)
    if data:
        add_or_update_player(interaction.user.id, tag, data)
        await interaction.followup.send(f"✅ Linked **{data['name']}** (`{player_tag}`) to your account.")
    else:
        await interaction.followup.send("❌ Failed to fetch player data. Please check the tag and try again.")

@bot.tree.command(name="unlink")
@app_commands.describe(player_tag="Optional: tag to unlink (remove all if left blank)")
async def unlink(interaction: discord.Interaction, player_tag: str = None):
    await interaction.response.defer()
    tag = player_tag.replace("#", "").upper() if player_tag else None
    remove_player(interaction.user.id, tag)
    await interaction.followup.send("✅ Account unlinked.", ephemeral=True)

@bot.tree.command(name="remove")
@app_commands.describe(player_tag="Tag to forcibly remove from the leaderboard")
async def remove(interaction: discord.Interaction, player_tag: str):
    await interaction.response.defer()
    tag = player_tag.replace("#", "").upper()
    result = players_col.delete_one({"player_tag": tag})
    if result.deleted_count:
        await interaction.followup.send(f"✅ Removed player `{tag}` from leaderboard.")
    else:
        await interaction.followup.send("❌ Player not found.")

@bot.tree.command(name="leaderboard")
@app_commands.describe(
    color="Embed color (default blue)",
    name="Leaderboard title",
    force_reset="Set to True to reset offense/defense stats before showing leaderboard"
)
async def leaderboard(
    interaction: discord.Interaction,
    color: str = "0x3498db",
    name: str = "🏆 Leaderboard",
    force_reset: bool = False
):
    await interaction.response.defer(thinking=True)

    # ✅ Force reset if requested
    if force_reset:
        players_col.update_many({}, {
            "$set": {
                "offense_trophies": 0,
                "offense_attacks": 0,
                "defense_trophies": 0,
                "defense_defenses": 0
            }
        })
        print(f"⚡ Force reset done by {interaction.user} at {datetime.now().strftime('%Y-%m-%d %I:%M %p')}")

    try:
        color = int(color, 16)
    except:
        color = 0x3498db

    players = get_all_players()
    view = LeaderboardView(players, color, name)
    await interaction.followup.send(embed=view.get_embed(), view=view)

# ======================= BOT STARTUP =======================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")
    update_players_data.start()
    reset_offense_defense.start()
    backup_leaderboard.start()

try:
    bot.run(TOKEN, reconnect=True)
except Exception as e:
    print(f"❌ Bot failed to run: {e}")
