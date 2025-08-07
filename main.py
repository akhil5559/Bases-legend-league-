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
from datetime import datetime
from pymongo import MongoClient
from keep_alive import keep_alive
import pytz

keep_alive()

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
backups_col = db["backups"]
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
    now = datetime.now(pytz.timezone("Asia/Kolkata"))

    if now.hour == 10 and now.minute == 25:
        try:
            backup_data = get_all_players()
            backups_col.insert_one({
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "players": backup_data
            })
            print("📦 Leaderboard backup created.")
        except Exception as e:
            print(f"❌ Backup failed: {e}")

    elif now.hour == 10 and now.minute == 30:
        try:
            players_col.update_many({}, {
                "$set": {
                    "offense_trophies": 0,
                    "offense_attacks": 0,
                    "defense_trophies": 0,
                    "defense_defenses": 0
                }
            })
            print("🔁 Daily reset done (10:30 AM IST)")
        except Exception as e:
            print(f"❌ Reset failed: {e}")

    elif now.hour == 10 and now.minute == 42:
        print("🔄 Post-reset refresh starting...")
        players = get_all_players()
        for player in players:
            try:
                discord_id = player["discord_id"]
                tag = player["player_tag"]
                data = await async_fetch_player_data(tag)
                if data:
                    data.update({
                        "prev_trophies": data["trophies"],
                        "prev_rank": data.get("rank", 0),
                        "offense_trophies": 0,
                        "offense_attacks": 0,
                        "defense_trophies": 0,
                        "defense_defenses": 0,
                        "last_reset": now.strftime("%Y-%m-%d")
                    })
                    add_or_update_player(discord_id, tag, data)
            except Exception as e:
                print(f"❌ Failed refresh for {player['player_tag']}: {e}")
        print("✅ Post-reset refresh finished.")

# ======================= UI LEADERBOARD =======================
class LeaderboardView(ui.View):
    def __init__(self, players, color, name, page=0):
        super().__init__(timeout=None)
        self.players = players
        self.color = color
        self.name = name
        self.page = page
        self.last_refreshed = datetime.now().strftime("%d-%m-%Y %I:%M %p")

    def get_embed(self):
        start = self.page * LEADERBOARD_PAGE_SIZE
        end = start + LEADERBOARD_PAGE_SIZE
        embed = discord.Embed(title=self.name, color=self.color)

        for i, p in enumerate(self.players[start:end], start=start + 1):
            embed.add_field(
                name=f"{i}. {p['name']} (#{p['player_tag']})",
                value=(
                    f"{EMOJI_TROPHY} {p['trophies']} | "
                    f"{EMOJI_OFFENSE} +{p.get('offense_trophies', 0)}/{p.get('offense_attacks', 0)} | "
                    f"{EMOJI_DEFENSE} -{p.get('defense_trophies', 0)}/{p.get('defense_defenses', 0)}\n\u200b"
                ),
                inline=False
            )

        embed.set_footer(text=f"Last refreshed: {self.last_refreshed}")
        return embed

    async def update_message(self, interaction):
        await interaction.response.defer()
        self.players = get_all_players()
        self.last_refreshed = datetime.now().strftime("%d-%m-%Y %I:%M %p")
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
        # ======================= SLASH COMMANDS =======================
@bot.tree.command(name="leaderboard", description="Show Clash of Clans leaderboard with stats.")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    players = get_all_players()
    color = discord.Color.gold()
    view = LeaderboardView(players, color, "🏆 Clan Leaderboard")
    await interaction.followup.send(embed=view.get_embed(), view=view)

@bot.tree.command(name="link", description="Link your Clash of Clans player tag to the bot.")
@app_commands.describe(tag="Your Clash of Clans player tag (e.g. #ABC123)")
async def link(interaction: discord.Interaction, tag: str):
    await interaction.response.defer()
    tag = tag.replace("#", "").upper()
    data = await async_fetch_player_data(tag)
    if not data:
        await interaction.followup.send("❌ Invalid or unavailable player tag.")
        return

    data.update({
        "prev_trophies": data["trophies"],
        "prev_rank": data.get("rank", 0),
        "offense_trophies": 0,
        "offense_attacks": 0,
        "defense_trophies": 0,
        "defense_defenses": 0,
        "last_reset": datetime.now().strftime("%Y-%m-%d")
    })

    add_or_update_player(interaction.user.id, tag, data)
    await interaction.followup.send(f"✅ Linked to {data['name']} (#{tag})")

@bot.tree.command(name="unlink", description="Unlink your player tag or all tags from your account.")
@app_commands.describe(tag="Optional: specific player tag to unlink (e.g. #ABC123)")
async def unlink(interaction: discord.Interaction, tag: str = None):
    tag = tag.replace("#", "").upper() if tag else None
    remove_player(interaction.user.id, tag)
    await interaction.response.send_message(f"✅ Unlinked {'tag ' + tag if tag else 'all tags'}.")

@bot.tree.command(name="remove", description="(Admin) Remove a player by tag.")
@app_commands.describe(tag="Player tag to remove (e.g. #ABC123)")
async def remove(interaction: discord.Interaction, tag: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return
    tag = tag.replace("#", "").upper()
    result = players_col.delete_one({"player_tag": tag})
    if result.deleted_count > 0:
        await interaction.response.send_message(f"🗑️ Removed player with tag #{tag}.")
    else:
        await interaction.response.send_message("⚠️ Player not found.")

# ======================= STARTUP =======================
@bot.event
async def on_ready():
    await bot.tree.sync()
    update_players_data.start()
    reset_offense_defense.start()
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    bot.run(TOKEN)
