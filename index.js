const express = require('express');
const { Client, GatewayIntentBits, Partials, REST, Routes, EmbedBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle, SlashCommandBuilder, PermissionsBitField } = require('discord.js');
const mongoose = require('mongoose');
const cron = require('node-cron');
const fetch = require('node-fetch');

// ENV variables
const DISCORD_TOKEN = process.env.BOT_TOKEN;
const CLIENT_ID = process.env.CLIENT_ID;
const MONGO_URI = process.env.MONGO_URI;
const CLASH_API = process.env.CLASH_API;

const EMOJI_TROPHY = "<:trophy:1400826511799484476>";
const EMOJI_OFFENSE = "<:Offence:1400826628099014676>";
const EMOJI_DEFENSE = "<:emoji_9:1252010455694835743>";

// MongoDB
mongoose.connect(MONGO_URI).then(() => console.log('✅ MongoDB connected')).catch(console.error);

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
  console.log(`🤖 Bot is ready as ${client.user.tag}`);
});

// Format player display
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
    .setColor(/^#?[0-9A-F]{6}$/i.test(color) ? color.replace('#', '') : '00FFFF')
    .setDescription(description)
    .setFooter({ text: `Last updated: ${new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} | Page ${page + 1}/${pageCount || 1}` });

  const buttons = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId('refresh').setLabel('🔁 Refresh').setStyle(ButtonStyle.Primary),
    new ButtonBuilder().setCustomId('prev').setLabel('⬅️ Prev').setStyle(ButtonStyle.Secondary).setDisabled(page === 0),
    new ButtonBuilder().setCustomId('next').setLabel('➡️ Next').setStyle(ButtonStyle.Secondary).setDisabled(page + 1 >= pageCount)
  );

  return { embed, buttons };
};

// Slash commands handler
client.on('interactionCreate', async interaction => {
  if (!interaction.isChatInputCommand()) return;

  const { commandName } = interaction;

  if (commandName === 'link') {
    const tag = interaction.options.getString('tag').toUpperCase().replace('#', '');
    console.log(`[LINK] Requested tag: ${tag} by ${interaction.user.tag}`);

    try {
      const response = await fetch(`${CLASH_API}/player/${tag}`);
      if (!response.ok) return interaction.reply({ content: 'Invalid tag or API failed.', ephemeral: true });

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
      console.log(`[LINKED] ${data.name} (${data.tag}) to ${interaction.user.tag}`);
      interaction.reply({ content: `✅ Linked to **${data.name}**`, ephemeral: true });

    } catch (err) {
      console.error('Link Error:', err);
      interaction.reply({ content: '❌ Error linking account.', ephemeral: true });
    }

  } else if (commandName === 'unlink') {
    await Player.updateOne({ discord_id: interaction.user.id }, { $unset: { discord_id: "" } });
    interaction.reply({ content: '✅ Unlinked your account.', ephemeral: true });

  } else if (commandName === 'remove') {
    if (!interaction.member.permissions.has(PermissionsBitField.Flags.Administrator)) {
      return interaction.reply({ content: '❌ Admin permission required.', ephemeral: true });
    }
    const tag = interaction.options.getString('tag').toUpperCase().replace('#', '');
    await Player.updateOne({ player_tag: tag }, { $unset: { discord_id: "" } });
    interaction.reply({ content: `✅ Removed player ${tag}`, ephemeral: true });

  } else if (commandName === 'leaderboard') {
    const name = interaction.options.getString('name') || '';
    const colorInput = interaction.options.getString('color') || '#00FFFF';
    const color = /^#?[0-9A-F]{6}$/i.test(colorInput) ? colorInput.replace('#', '') : '00FFFF';

    try {
      const players = await Player.find({ discord_id: { $ne: null } }).sort({ trophies: -1 });
      console.log(`[LEADERBOARD] Showing ${players.length} players`);

      const { embed, buttons } = await createLeaderboardEmbed(players, 0, name, color);
      await interaction.reply({ embeds: [embed], components: [buttons] });
    } catch (err) {
      console.error('Leaderboard Error:', err);
      interaction.reply({ content: '❌ Failed to load leaderboard.', ephemeral: true });
    }
  }
});

// Button interaction
client.on('interactionCreate', async interaction => {
  if (!interaction.isButton()) return;

  const oldEmbed = interaction.message.embeds[0];
  const pageMatch = oldEmbed?.footer?.text?.match(/Page (\d+)\/(\d+)/);
  const page = pageMatch ? parseInt(pageMatch[1]) - 1 : 0;
  const maxPage = pageMatch ? parseInt(pageMatch[2]) : 1;

  const players = await Player.find({ discord_id: { $ne: null } }).sort({ trophies: -1 });
  const { embed, buttons } = await createLeaderboardEmbed(
    players,
    interaction.customId === 'next' ? page + 1 : interaction.customId === 'prev' ? page - 1 : page,
    '',
    '00FFFF'
  );
  await interaction.update({ embeds: [embed], components: [buttons] });
});

// Background player updater
cron.schedule('*/2 * * * *', async () => {
  const players = await Player.find({});
  for (const p of players) {
    try {
      const res = await fetch(`${CLASH_API}/player/${p.player_tag}`);
      const data = await res.json();
      const diff = data.trophies - p.trophies;
      const update = {
        trophies: data.trophies,
        attacks: (p.attacks || 0) + 1,
        offense_trophies: (p.offense_trophies || 0) + Math.max(0, diff),
        offense_attacks: (p.offense_attacks || 0) + 1,
        defense_trophies: (p.defense_trophies || 0) + Math.max(0, -diff),
        defense_defenses: (p.defense_defenses || 0) + 1
      };
      await Player.updateOne({ player_tag: p.player_tag }, { $set: update });
    } catch (e) {
      console.log(`❌ Failed update for ${p.player_tag}`);
    }
  }
  console.log('♻️ Player stats updated');
});

// Daily reset
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

  console.log('🕙 Daily reset completed and backup saved');
}, { timezone: 'Asia/Kolkata' });

// Keep-alive server
const app = express();
app.get('/', (req, res) => res.send('Bot is alive!'));
app.listen(process.env.PORT || 3000, () => console.log('🌐 Keep-alive server running'));

client.login(DISCORD_TOKEN);
