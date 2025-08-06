import sys
import types

# ✅ Proper bypass for audioop-related crashes (e.g., on Render)
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

import discord, asyncio, requests, os, threading
from discord.ext import commands, tasks
from discord import app_commands, ui
from datetime import datetime
from flask import Flask
import traceback
from pymongo import MongoClient

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

# ======================= WEB KEEPALIVE =======================

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

# ======================= DATABASE INIT =======================

mongo_client = MongoClient(MONGO_URI)
db = mongo_client["coc_bot"]
players_col = db["players"]
players_col.create_index([("trophies", -1)])  # ✅ Ensure sorted performance

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
        print(f"🗑 Removed by tag: {tag} → Deleted: {result.deleted_count}")
    else:
        result = players_col.delete_many({"discord_id": discord_id})
        print(f"🗑 Removed all for {discord_id} → Deleted: {result.deleted_count}")

# ======================= API FUNCTION =======================

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
# ======================= BACKGROUND UPDATER =======================

@tasks.loop(minutes=1)
async def update_players_data():
    players = get_all_players()
    print(f"\n⏳ Background update started: {len(players)} players...")
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

            data = fetch_player_data(tag)
            if data:
                delta_trophies = data["trophies"] - trophies
                if delta_trophies > 0:
                    off_t += delta_trophies
                    off_a += 1
                elif delta_trophies < 0:
                    def_t += abs(delta_trophies)
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
                print(f"❌ Failed to update: {tag}")

        except Exception as e:
            print(f"⚠️ Error updating player {player.get('player_tag')}: {e}")
    print("✔️ Background update complete!")

# ======================= DISCORD COMMANDS =======================

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🤖 Bot is online as {bot.user}")
    update_players_data.start()

@bot.tree.command(name="link", description="Link your Clash of Clans account")
@app_commands.describe(player_tag="Your player tag (e.g., #ABC123)")
async def link(interaction: discord.Interaction, player_tag: str):
    tag_clean = player_tag.replace("#", "").upper()
    data = fetch_player_data(tag_clean)

    if data:
        add_or_update_player(str(interaction.user.id), tag_clean, data)
        await interaction.response.send_message(f"✅ Linked to player `{data['name']}` ({player_tag})")
    else:
        await interaction.response.send_message("❌ Failed to fetch player data.")

@bot.tree.command(name="unlink", description="Unlink your account(s)")
@app_commands.describe(player_tag="Optional: Specific tag to unlink")
async def unlink(interaction: discord.Interaction, player_tag: str = None):
    discord_id = str(interaction.user.id)
    if player_tag:
        tag_clean = player_tag.replace("#", "").upper()
        result = players_col.delete_one({"discord_id": discord_id, "player_tag": tag_clean})
        if result.deleted_count > 0:
            await interaction.response.send_message(f"✅ Unlinked player `{tag_clean}`.")
        else:
            await interaction.response.send_message(f"⚠️ No player found with tag `{tag_clean}`.")
    else:
        result = players_col.delete_many({"discord_id": discord_id})
        if result.deleted_count > 0:
            await interaction.response.send_message("✅ All linked accounts unlinked.")
        else:
            await interaction.response.send_message("⚠️ You have no linked accounts.")

class LeaderboardView(ui.View):
    def __init__(self, players, page):
        super().__init__(timeout=60)
        self.players = players
        self.page = page

    def format_page(self):
        start = self.page * LEADERBOARD_PAGE_SIZE
        end = start + LEADERBOARD_PAGE_SIZE
        lines = []
        for idx, player in enumerate(self.players[start:end], start=1+start):
            lines.append(f"**#{idx}** {player['name']} - {player['trophies']} {EMOJI_TROPHY}")
        return "\n".join(lines)

    @ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: ui.Button):
        if self.page > 0:
            self.page -= 1
            embed = discord.Embed(title="🏆 Leaderboard", description=self.format_page(), color=discord.Color.gold())
            await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: ui.Button):
        max_pages = len(self.players) // LEADERBOARD_PAGE_SIZE
        if self.page < max_pages:
            self.page += 1
            embed = discord.Embed(title="🏆 Leaderboard", description=self.format_page(), color=discord.Color.gold())
            await interaction.response.edit_message(embed=embed, view=self)

@bot.tree.command(name="leaderboard", description="View the top players")
async def leaderboard(interaction: discord.Interaction):
    players = get_all_players()
    if not players:
        await interaction.response.send_message("🚫 No players linked yet.")
        return

    view = LeaderboardView(players, page=0)
    embed = discord.Embed(title="🏆 Leaderboard", description=view.format_page(), color=discord.Color.gold())
    await interaction.response.send_message(embed=embed, view=view)

# ======================= BOT RUN =======================

bot.run(TOKEN, reconnect=True)        
