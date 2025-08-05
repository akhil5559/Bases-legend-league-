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
        players_col.delete_one({"discord_id": discord_id, "player_tag": tag})
    else:
        players_col.delete_many({"discord_id": discord_id})

# ======================= API FUNCTION =======================

def fetch_player_data(tag: str):
    tag_encoded = tag if tag.startswith("#") else f"#{tag}"
    url = f"{PROXY_URL}/player/{tag_encoded.replace('#', '%23')}"
    r = requests.get(url)
    if r.status_code != 200:
        return None
    data = r.json()
    return {
        "name": data["name"],
        "trophies": data["trophies"],
        "rank": data.get("rank", 0),
        "attacks": len(data.get("attackLog", [])),
        "defenses": len(data.get("defenseLog", []))
    }

# ======================= BACKGROUND TASKS =======================

@tasks.loop(minutes=1)
async def update_players_data():
    players = get_all_players()
    print(f"\n⏳ Background update started: {len(players)} players...")
    for player in players:
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
    print("✔️ Background update complete!")

@tasks.loop(minutes=1)
async def reset_offense_defense():
    now = datetime.now()
    if now.hour == 10 and now.minute == 30:
        players_col.update_many({}, {
            "$set": {
                "offense_trophies": 0,
                "offense_attacks": 0,
                "defense_trophies": 0,
                "defense_defenses": 0
            }
        })
        print("🔄 Daily reset done at 10:30 AM!")

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
        for i, p in enumerate(self.players[start:end], start=start + 1):
            embed.add_field(
                name=f"{i}. {p['name']} (#{p['player_tag']})",
                value=f"{EMOJI_TROPHY} {p['trophies']} | {EMOJI_OFFENSE} +{p.get('offense_trophies', 0)}/{p.get('offense_attacks', 0)} | {EMOJI_DEFENSE} -{p.get('defense_trophies', 0)}/{p.get('defense_defenses', 0)}",
                inline=False
            )
        return embed

    async def update_message(self, interaction):
        self.players = get_all_players()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

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
        self.players = get_all_players()
        await self.update_message(interaction)

# ======================= BOT EVENTS =======================

@bot.event
async def on_ready():
    print("🔄 Bot is starting...")
    try:
        players = get_all_players()
        print(f"📊 Total players: {len(players)}")
        update_players_data.start()
        reset_offense_defense.start()
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands")
        print(f"✅ Logged in as {bot.user}")
    except Exception:
        print("❌ Error in on_ready:")
        traceback.print_exc()

# ======================= COMMANDS =======================

@bot.tree.command(name="link", description="Link your Clash of Clans account")
async def link(interaction: discord.Interaction, player_tag: str):
    await interaction.response.defer()
    data = fetch_player_data(player_tag)
    if not data:
        await interaction.followup.send("❌ Failed to fetch data!")
        return
    add_or_update_player(str(interaction.user.id), player_tag.replace("#", ""), data)
    await interaction.followup.send(f"✅ Linked {data['name']} ({player_tag})")

@bot.tree.command(name="unlink", description="Unlink your account(s)")
async def unlink(interaction: discord.Interaction, player_tag: str = None):
    remove_player(str(interaction.user.id), player_tag)
    await interaction.response.send_message("✅ Account unlinked!")

@bot.tree.command(name="leaderboard", description="Show the leaderboard")
async def leaderboard(interaction: discord.Interaction, name: str = "Leaderboard", color: str = "000000"):
    players = get_all_players()
    if not players:
        await interaction.response.send_message("❌ No players linked yet.")
        return
    try:
        color_int = int(color, 16)
    except:
        color_int = 0x000000
    view = LeaderboardView(players, color_int, name)
    await interaction.response.send_message(embed=view.get_embed(), view=view)

# ======================= RUN =======================

bot.run(TOKEN)
