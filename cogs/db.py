"""
DB
==

Cog for SQLite local database storage management of guild-specific
configurations, blocked IDs and admin IDs.

Copyright (C) 2019-2020 Jonathan Feenstra

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
from collections import defaultdict

import discord
from discord.ext import commands

from .util import delete_msg, feedback_embed

# Pre-configured popular Nexus Games and filters
NEXUS_CONFIG_PRESETS = {
    'all': {"All games": '&include_adult=1&timeout=15000'},
    'morrowind': {"Morrowind": '&game_id=100&include_adult=1&timeout=15000'},
    'oblivion': {"Oblivion": '&game_id=101&include_adult=1&timeout=15000'},
    'skyrim': {"Skyrim Classic": '&game_id=110&include_adult=1&timeout=15000'},
    'skyrimspecialedition': {"Skyrim Special Edition": '&game_id=1704&include_adult=1&timeout=15000'},
    'skyrimboth': {
        "Skyrim Special Edition": '&game_id=1704&include_adult=1&timeout=15000',
        "Skyrim Classic": '&game_id=110&include_adult=1&timeout=15000',
    },
    'fallout3': {"Fallout 3": '&game_id=120&include_adult=1&timeout=15000'},
    'newvegas': {"Fallout New Vegas": '&game_id=130&include_adult=1&timeout=15000'},
    'fallout4': {"Fallout 4": '&game_id=1151&include_adult=1&timeout=15000'},
    'witcher3': {"The Witcher 3": '&game_id=952&include_adult=1&timeout=15000'},
    'stardewvalley': {"Stardew Valley": '&game_id=1303&include_adult=1&timeout=15000'},
    'dragonage': {"Dragon Age": '&game_id=140&include_adult=1&timeout=15000'},
    'dragonage2': {"Dragon Age 2": '&game_id=141&include_adult=1&timeout=15000'},
    'dragonageinquisition': {"Dragon Age: Inquisition": '&game_id=728&include_adult=1&timeout=15000'},
    'monsterhunterworld': {"Monster Hunter: World": '&game_id=2531&include_adult=1&timeout=15000'},
    'mountandblade2bannerlord': {"Mount & Blade II: Bannerlord": '&game_id=3174&include_adult=1&timeout=15000'},
    'darksouls': {"Dark Souls": '&game_id=162&include_adult=1&timeout=15000'},
    'kingdomcomedeliverance': {"Kingdom Come: Deliverance": '&game_id=2298&include_adult=1&timeout=15000'},
    'bladeandsorcery': {"Blade & Sorcery": '&game_id=2673&include_adult=1&timeout=15000'},
}


class DB(commands.Cog):
    """Cog to use SQLite database."""

    def __init__(self, bot):
        """Initialise cog and update guild configuration with database content."""
        self.bot = bot

    async def _block(self, _id: int):
        """Block a guild or user."""
        self.bot.blocked.add(_id)
        async with self.bot.db_connect() as db:
            await db.execute('INSERT OR IGNORE INTO blocked VALUES (?)', (_id,))
            await db.commit()

    async def set_filter(self, ctx, config: dict, game_filter: str, destination: str, channel_id=0):
        """Parse `game_filter` to set filter for game in `config`."""
        if preset := NEXUS_CONFIG_PRESETS.get(game_filter):
            config.update(preset)
            async with self.bot.db_connect() as db:
                if channel_id:
                    await db.execute('INSERT OR IGNORE INTO channel VALUES (?, ?)',
                                     (channel_id, ctx.guild.id))
                for game_name, filter in preset.items():
                    await db.execute('INSERT OR REPLACE INTO game VALUES (?, ?, ?, ?)',
                                     (ctx.guild.id, channel_id, game_name, filter))
                    await ctx.send(embed=feedback_embed(
                        "Default Nexus Mods search API filter set for "
                        f"`{game_name}` to: `{filter}` in {destination}."))
                return await db.commit()

        if len(terms := game_filter.split()) < 2:
            return await ctx.send(embed=feedback_embed("Invalid arguments.", False))

        game_name, filter = ' '.join(terms[:-1]).replace('`', "'"), terms[-1].replace('`', "'")
        if len(game_name) > 100:
            return await ctx.send(embed=feedback_embed("Game name too long (max length = 100).", False))
        if len(filter) > 1024:
            return await ctx.send(embed=feedback_embed("Filter too long (max length = 1024).", False))

        if game_name in config or len(config) <= 5:
            config[game_name] = filter
            async with self.bot.db_connect() as db:
                if channel_id:
                    await db.execute('INSERT OR REPLACE INTO channel VALUES (?, ?)', (channel_id, ctx.guild.id))
                await db.execute('INSERT OR REPLACE INTO game VALUES (?, ?, ?, ?)',
                                 (ctx.guild.id, channel_id, game_name, filter))
                await db.commit()
            await ctx.send(embed=feedback_embed(
                "Default Nexus Mods search API filter set for "
                f"`{game_name}` to: `{filter}` in {destination}."))
        else:
            await ctx.send(embed=feedback_embed("Maximum of 5 games exceeded.", False))

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Block and leave guild if the bot's app owner is banned."""
        if user.id == getattr(self.bot, 'app_owner_id', None):
            await self._block(guild.id)
            await guild.leave()

    @commands.command(aliases=['ssp', 'presets'])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    async def showsearchpresets(self, ctx):
        """Show available search configuration presets."""
        presets = [f"```{'Preset': <26}Game"]
        for preset_name, config in NEXUS_CONFIG_PRESETS.items():
            games = list(config.keys())
            presets.append(f'{preset_name: <26}{games[0]}')
            for game in games[1:]:
                presets.append(26 * ' ' + game)
        embed = discord.Embed(
            title=':mag_right: Nexus Mods Search Configuration Presets',
            description='\n'.join(presets) + '```',
            colour=ctx.guild.me.colour.value or 14323253)
        embed.set_footer(text=f'Prompted by @{ctx.author}', icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(aliases=['prefix'])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setprefix(self, ctx, prefix: str):
        """Set guild prefix for bot commands."""
        if len(prefix) <= 3:
            self.bot.guild_configs[ctx.guild.id]['prefix'] = prefix
            async with self.bot.db_connect() as db:
                await db.execute('UPDATE guild SET prefix = ? WHERE id = ?', (prefix, ctx.guild.id))
                await db.commit()
            await ctx.send(embed=feedback_embed(f"Prefix set to `{prefix}`."))
        else:
            await ctx.send(embed=feedback_embed("Prefix too long (max length = 3).", False))

    @commands.command(aliases=['searchconfig', 'ssc', 'sc'])
    @delete_msg
    async def showsearchconfig(self, ctx):
        """List configured Nexus Mods default search filters for guild."""
        embed = discord.Embed(colour=14323253)
        embed.set_author(name='Nexus Mods Search Configuration',
                         url='https://www.nexusmods.com/',
                         icon_url='https://images.nexusmods.com/favicons/ReskinOrange/favicon-32x32.png')
        embed.set_footer(text=f'Prompted by @{ctx.author}', icon_url=ctx.author.avatar_url)
        if games := self.bot.guild_configs[ctx.guild.id]['channels'][ctx.channel.id]:
            embed.add_field(name='Channel-specific game filters in:',
                            value=f'{ctx.channel.mention}',
                            inline=False)
            for game_name, filter in games.items():
                embed.add_field(name=game_name, value=f"`{filter}`", inline=False)
        if games := self.bot.guild_configs[ctx.guild.id]['games']:
            embed.add_field(name='Server default game filters in:',
                            value=f'**{ctx.guild.name}**',
                            inline=False)
            for game_name, filter in games.items():
                embed.add_field(name=game_name, value=f"`{filter}`", inline=False)
        elif not embed.fields:
            embed.description = ':x: No Nexus Mods search filters configured in this channel/server.'
        await ctx.send(embed=embed)

    @commands.command(aliases=['setguildfilter', 'setgf', 'setsf'])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setserverfilter(self, ctx, *, game_filter: str):
        """Set default Nexus Mods search API filter for game in server.

        Requires the 'Manage Server' permission or bot admin permissions.

        `game_filter` can be a game name with a Nexus Mods search API query string suffix or a preset name. Use the
        `.presets` command for a list of search configuration presets.

        Examples
        --------

        Using a game name with search filter:

        `.setsf Farming Simulator 19 &game_id=2676&include_adult=1&timeout=15000`

        Applies filter for Farming Simulator 19 with adult mods included and a request timeout of 15000. Here the last term
        (separated by spaces) is used as filter for a URL such as:

        https://search.nexusmods.com/mods?terms=skyui&game_id=0&blocked_tags=&blocked_authors=&include_adult=1

        The preceding terms make up the game name.

        Using a preset name:

        `.setsf skyrimboth`

        Applies the 'skyrimboth' search configuration preset with filters for both Skyrim Special Edition and Skyrim Classic.

        Command prefixes may vary per server.
        """
        await self.set_filter(ctx,
                              self.bot.guild_configs[ctx.guild.id]['games'],
                              game_filter,
                              f'**{discord.utils.escape_markdown(ctx.guild.name)}**')

    @commands.command(aliases=['setchf'])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.channel)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setchannelfilter(self, ctx, *, game_filter: str):
        """Set Nexus Mods search API filter for game in channel.

        Requires the 'Manage Server' permission or bot admin permissions.

        `game_filter` can be a game name with a Nexus Mods search API query string suffix or a preset name. Use the
        `.presets` command for a list of search configuration presets.

        Examples
        --------

        Using a game name with search filter:

        `.setchf Farming Simulator 19 &game_id=2676&include_adult=1&timeout=15000`

        Applies filter for Farming Simulator 19 with adult mods included and a request timeout of 15000. Here the last term
        (separated by spaces) is used as filter for a URL such as:

        https://search.nexusmods.com/mods?terms=skyui&game_id=0&blocked_tags=&blocked_authors=&include_adult=1

        The preceding terms make up the game name.

        Using a preset name:

        `.setchf skyrimboth`

        Applies the 'skyrimboth' search configuration preset with filters for both Skyrim Special Edition and Skyrim Classic.

        Command prefixes may vary per server.
        """
        await self.set_filter(ctx,
                              self.bot.guild_configs[ctx.guild.id]['channels'][ctx.channel.id],
                              game_filter,
                              ctx.channel.mention,
                              ctx.channel.id)

    @commands.command(aliases=['delsf', 'rmsf'])
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def deleteserverfilter(self, ctx, *, game_name: str):
        """Delete Nexus Mods search API filter for game in guild."""
        try:
            del self.bot.guild_configs[ctx.guild.id]['games'][game_name]
        except KeyError:
            await ctx.send(embed=feedback_embed(f"Game `{game_name}` not found in server filters.", False))
        else:
            async with self.bot.db_connect() as db:
                await db.execute('DELETE FROM game WHERE guild_id = ? AND channel_id = ? AND name = ?',
                                 (ctx.guild.id, 0, game_name))
                await db.commit()
            await ctx.send(embed=feedback_embed(f"Server filter for `{game_name}` deleted."))

    @commands.command(aliases=['delchf', 'rmchf'])
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def deletechannelfilter(self, ctx, *, game_name: str):
        """Delete Nexus Mods search API filter for game in channel."""
        try:
            del self.bot.guild_configs[ctx.guild.id]['channels'][ctx.channel.id][game_name]
        except KeyError:
            await ctx.send(embed=feedback_embed(
                f"Game `{game_name}` not found in channel filters.", False))
        else:
            async with self.bot.db_connect() as db:
                if not self.bot.guild_configs[ctx.guild.id]['channels']:
                    await db.execute('DELETE FROM channel WHERE id = ?', (ctx.channel.id,))
                else:
                    await db.execute('DELETE FROM game WHERE channel_id = ? AND name = ?', (ctx.channel.id, game_name))
                await db.commit()
            await ctx.send(embed=feedback_embed(f"Channel filter for `{game_name}` deleted."))

    @commands.command(aliases=['clearsf', 'csf'])
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def clearserverfilters(self, ctx):
        """Clear Nexus Mods search API filters in guild."""
        self.bot.guild_configs[ctx.guild.id]['games'] = defaultdict(dict)
        async with self.bot.db_connect() as db:
            await db.execute('DELETE FROM game WHERE guild_id = ? AND channel_id = 0', (ctx.guild.id,))
            await db.commit()
        await ctx.send(embed=feedback_embed("Server filters cleared."))

    @commands.command(aliases=['clearchf', 'cchf'])
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def clearchannelfilters(self, ctx):
        """Clear Nexus Mods search API filters in channel."""
        self.bot.guild_configs[ctx.guild.id]['channels'][ctx.channel.id] = defaultdict(dict)
        async with self.bot.db_connect() as db:
            await db.execute('DELETE FROM channel WHERE id = ?',  (ctx.channel.id,))
            await db.commit()
        await ctx.send(embed=feedback_embed("Channel filters cleared."))

    @commands.command(aliases=['showblacklist'])
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.channel)
    @delete_msg
    async def showblocked(self, ctx):
        """Send embed with blocked IDs."""
        description = ', '.join(str(_id) for _id in self.bot.blocked)
        if not description:
            description = "No blocked IDs yet."
        elif len(description) > 2048:
            description = f'{description[:2045]}...'
        embed = discord.Embed(title=':stop_sign: Blocked IDs',
                              description=description,
                              colour=ctx.guild.me.colour.value or 14323253)
        embed.set_footer(text=f'Prompted by @{ctx.author}',
                         icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(aliases=['blacklist'])
    @commands.is_owner()
    @delete_msg
    async def block(self, ctx, _id: int):
        """Block a guild or user from using the bot."""
        if guild := self.bot.get_guild(_id):
            await guild.leave()
        await self._block(_id)
        await ctx.send(embed=feedback_embed(f"Blocked ID `{_id}`."))

    @commands.command(aliases=['unblacklist'])
    @commands.is_owner()
    async def unblock(self, ctx, _id: int):
        """Unblock a guild or user from using the bot."""
        try:
            self.bot.blocked.remove(_id)
        except KeyError:
            await ctx.send(embed=feedback_embed(f'ID `{_id}` was not blocked.', False))
        else:
            await ctx.send(embed=feedback_embed(f"ID `{_id}` is no longer blocked."))
        finally:
            async with self.bot.db_connect() as db:
                await db.execute('DELETE FROM blocked WHERE id = (?)', (_id,))
                await db.commit()

    @commands.command(aliases=['admins'])
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.channel)
    @delete_msg
    async def showadmins(self, ctx):
        """Send embed with admin IDs."""
        description = ', '.join(str(_id) for _id in self.bot.owner_ids)
        if not description:
            description = "No admins."
        elif len(description) > 2048:
            description = f'{description[:2045]}...'
        embed = discord.Embed(title=':sunglasses: Bot Admin IDs',
                              description=description,
                              colour=ctx.guild.me.colour.value or 14323253)
        embed.set_footer(text=f'Prompted by @{ctx.author}',
                         icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(aliases=['admin'])
    @commands.is_owner()
    @delete_msg
    async def makeadmin(self, ctx, user_id: int):
        """Make user a bot admin."""
        self.bot.owner_ids.add(user_id)
        async with self.bot.db_connect() as db:
            await db.execute('INSERT OR IGNORE INTO admin VALUES (?)', (user_id,))
            await db.commit()
        await ctx.send(embed=feedback_embed(f'Added {user_id} as admin.'))

    @commands.command(aliases=['rmadmin'])
    @commands.is_owner()
    async def deladmin(self, ctx, user_id: int):
        """Remove user as bot admin if not app owner."""
        if user_id == getattr(self.bot, 'app_owner_id', None):
            return await ctx.send(embed=feedback_embed('Cannot remove app owner.', False))
        try:
            self.bot.owner_ids.remove(user_id)
            async with self.bot.db_connect() as db:
                await db.execute('DELETE FROM admin WHERE id = ?', (user_id,))
                await db.commit()
        except KeyError:
            await ctx.send(embed=feedback_embed(f'User `{user_id}` was not an admin.', False))
        else:
            await ctx.send(embed=feedback_embed(f'Removed `{user_id}` as admin.'))


def setup(bot):
    """Add this cog to bot."""
    bot.add_cog(DB(bot))
