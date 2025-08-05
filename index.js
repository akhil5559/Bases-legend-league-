const { Client, GatewayIntentBits, Partials, REST, Routes, EmbedBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle, SlashCommandBuilder } = require('discord.js');
const mongoose = require('mongoose');
const cron = require('node-cron');
const fetch = require('node-fetch');

// ENV variables from Render
const DISCORD_TOKEN = process.env.BOT_TOKEN;
const CLIENT_ID = process.env.CLIENT_ID;
const GUILD_ID = process.env.GUILD_ID; // optional if global
const MONGO_URI = process.env.MONGO_URI;
const CLASH_API = process.env.CLASH_API;

// Emojis
const EMOJI_TROPHY = "<:trophy:1400826511799484476>";
const EMOJI_OFFENSE = "<:Offence:1400826628099014676>";
const EMOJI_DEFENSE = "<:emoji_9:1252010455694835743>";

// Connect MongoDB
mongoose.connect(MONGO_URI).then(() => console.log('✅ Connected to MongoDB')).catch(console.error);

// Schema
const playerSchema = new mongoose.Schema({
  player_tag: String,
  name: String,
  discord_id: String,
  trophies: Number,
  prev_trophies: Number,
  offense_trophies: Number,
  offense_attacks: Number,
  defense_trophies: Number,
  defense_defenses: Number,
  attacks: Number,
  defenses: Number,
  rank: Number,
  prev_rank: Number,
  last_reset: String
});
const Player = mongoose.model('Player', playerSchema, 'players');
const Backup = mongoose.model('Backup', new mongoose.Schema({ data: Array, timestamp: String }), 'backups');

// Discord client
const client = new Client({
  intents: [GatewayIntentBits.Guilds],
  partials: [Partials.Channel]
});

// Slash commands
const commands = [
  new SlashCommandBuilder().setName('link').setDescription('Link your Clash of Clans account')
    .addStringOption(opt => opt.setName('tag').setDescription('Your player tag').setRequired(true)),
  new SlashCommandBuilder().setName('unlink').setDescription('Unlink your Clash account from the leaderboard'),
  new SlashCommandBuilder().setName('remove').setDescription('Admin: remove a player from leaderboard')
    .addStringOption(opt => opt.setName('tag').setDescription('Player tag').setRequired(true)),
  new SlashCommandBuilder().setName('leaderboard').setDescription('Show trophy leaderboard')
    .addStringOption(opt => opt.setName('name').setDescription('Filter by name'))
    .addStringOption(opt => opt.setName('color').setDescription('Embed color (hex)'))
].map(cmd => cmd.toJSON());

// Register slash commands
client.once('ready', async () => {
  const rest = new REST({ version: '10' }).setToken(DISCORD_TOKEN);
  await rest.put(Routes.applicationCommands(CLIENT_ID), { body: commands });
  console.log(`🤖 Logged in as ${client.user.tag}`);
});

// Format leaderboard string
const formatPlayer = (player, index) => {
  const offense = `${player.offense_trophies || 0}/${player.offense_attacks || 0}`;
  const defense = `${player.defense_trophies || 0}/${player.defense_defenses || 0}`;
  return `**${index + 1}. ${player.name} (${player.player_tag})**\n${EMOJI_TROPHY} ${player.trophies} | ${EMOJI_OFFENSE} +${offense} | ${EMOJI_DEFENSE} -${defense}`;
};

// Create leaderboard embed
const createLeaderboardEmbed = async (players, page = 0, nameFilter = '', color = '#00FFFF') => {
  const perPage = 10;
  const filtered = nameFilter ? players.filter(p => p.name.toLowerCase().includes(nameFilter.toLowerCase())) : players;
  const pageCount = Math.ceil(filtered.length / perPage);
  const pagePlayers = filtered.slice(page * perPage, (page + 1) * perPage);
  const description = pagePlayers.map((p, i) => formatPlayer(p, i + page * perPage)).join('\n\n') || 'No players found.';

  const embed = new EmbedBuilder()
    .setTitle(`🏆 Trophy Leaderboard`)
    .setColor(color || '#00FFFF')
    .setDescription(description)
    .setFooter({ text: `Last refreshed: 05-08-2025 05:00 AM | Page ${page + 1}/${pageCount}` });

  const buttons = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId('refresh').setLabel('🔁 Refresh').setStyle(ButtonStyle.Primary),
    new ButtonBuilder().setCustomId('prev').setLabel('⬅️ Prev').setStyle(ButtonStyle.Secondary).setDisabled(page === 0),
    new ButtonBuilder().setCustomId('next').setLabel('➡️ Next').setStyle(ButtonStyle.Secondary).setDisabled(page + 1 >= pageCount)
  );

  return { embed, buttons };
};

// Slash command handler
client.on('interactionCreate', async interaction => {
  if (!interaction.isChatInputCommand()) return;

  const { commandName } = interaction;

  if (commandName === 'link') {
    const tag = interaction.options.getString('tag').toUpperCase().replace('#', '');
    const response = await fetch(`${CLASH_API}/player/${tag}`);
    if (!response.ok) return interaction.reply({ content: 'Invalid player tag.', ephemeral: true });

    const data = await response.json();
    const playerData = {
      player_tag: data.tag,
      name: data.name,
      discord_id: interaction.user.id,
      trophies: data.trophies,
      prev_trophies: data.trophies,
      last_reset: new Date().toISOString().slice(0, 10)
    };

    await Player.updateOne({ player_tag: data.tag }, { $set: playerData }, { upsert: true });
    interaction.reply({ content: `Linked to **${data.name}**!`, ephemeral: true });

  } else if (commandName === 'unlink') {
    await Player.updateOne({ discord_id: interaction.user.id }, { $unset: { discord_id: "" } });
    interaction.reply({ content: `Unlinked your account from leaderboard.`, ephemeral: true });

  } else if (commandName === 'remove') {
    if (!interaction.member.permissions.has('Administrator')) {
      return interaction.reply({ content: 'You need admin permission.', ephemeral: true });
    }
    const tag = interaction.options.getString('tag').toUpperCase().replace('#', '');
    await Player.updateOne({ player_tag: tag }, { $unset: { discord_id: "" } });
    interaction.reply({ content: `Removed player ${tag} from leaderboard.`, ephemeral: true });

  } else if (commandName === 'leaderboard') {
    const name = interaction.options.getString('name');
    const color = interaction.options.getString('color') || '#00FFFF';
    const players = await Player.find({ discord_id: { $ne: null } }).sort({ trophies: -1 });

    const { embed, buttons } = await createLeaderboardEmbed(players, 0, name, color);
    await interaction.reply({ embeds: [embed], components: [buttons] });
  }
});

// Button interactions
client.on('interactionCreate', async interaction => {
  if (!interaction.isButton()) return;

  const message = interaction.message;
  const oldEmbed = message.embeds[0];
  const pageMatch = oldEmbed?.footer?.text?.match(/Page (\d+)\/(\d+)/);
  const page = pageMatch ? parseInt(pageMatch[1]) - 1 : 0;
  const maxPage = pageMatch ? parseInt(pageMatch[2]) : 1;
  const name = ''; const color = '#00FFFF';

  const players = await Player.find({ discord_id: { $ne: null } }).sort({ trophies: -1 });

  if (interaction.customId === 'refresh') {
    const { embed, buttons } = await createLeaderboardEmbed(players, page, name, color);
    await interaction.update({ embeds: [embed], components: [buttons] });

  } else if (interaction.customId === 'next' && page + 1 < maxPage) {
    const { embed, buttons } = await createLeaderboardEmbed(players, page + 1, name, color);
    await interaction.update({ embeds: [embed], components: [buttons] });

  } else if (interaction.customId === 'prev' && page > 0) {
    const { embed, buttons } = await createLeaderboardEmbed(players, page - 1, name, color);
    await interaction.update({ embeds: [embed], components: [buttons] });
  }
});

// Background: update players every 2 minutes
cron.schedule('*/2 * * * *', async () => {
  const players = await Player.find({});
  for (const p of players) {
    try {
      const res = await fetch(`${CLASH_API}/player/${p.player_tag}`);
      const data = await res.json();
      const trophyDiff = data.trophies - p.trophies;
      const update = {
        trophies: data.trophies,
        attacks: (p.attacks || 0) + 1,
        offense_trophies: (p.offense_trophies || 0) + Math.max(0, trophyDiff),
        offense_attacks: (p.offense_attacks || 0) + 1,
        defense_trophies: (p.defense_trophies || 0) + Math.max(0, -trophyDiff),
        defense_defenses: (p.defense_defenses || 0) + 1
      };
      await Player.updateOne({ player_tag: p.player_tag }, { $set: update });
    } catch (e) {
      console.log('Update failed for', p.player_tag);
    }
  }
  console.log('[UPDATE] Player stats refreshed');
});

// Daily 10:30 AM IST reset
cron.schedule('0 10 * * *', async () => {
  const players = await Player.find({});
  const backup = new Backup({ data: players, timestamp: new Date().toISOString() });
  await backup.save();
  for (const p of players) {
    await Player.updateOne({ player_tag: p.player_tag }, {
      $set: {
        prev_trophies: p.trophies,
        offense_trophies: 0,
        offense_attacks: 0,
        defense_trophies: 0,
        defense_defenses: 0,
        last_reset: new Date().toISOString().slice(0, 10)
      }
    });
  }
  console.log('[DAILY RESET] Offense/Defense stats reset and backup created');
}, {
  timezone: 'Asia/Kolkata'
});

client.login(DISCORD_TOKEN);
      
