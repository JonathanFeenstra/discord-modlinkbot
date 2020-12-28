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
import json
import re
from collections import defaultdict

import discord
from discord.ext import commands

from .util import delete_msg, feedback_embed

GAME_NAME_RE = re.compile(r":: (?P<game_name>.*?)\"")
GAME_ID_RE = re.compile(r"https://staticdelivery\.nexusmods\.com/Images/games/4_3/tile_(?P<game_id>[0-9]{1,4})")


class DB(commands.Cog):
    """Cog to use SQLite database."""

    def __init__(self, bot):
        """Initialise cog and update guild configuration with database content."""
        self.bot = bot
        with open("games.json", encoding="utf-8") as games:
            self.games = json.load(games)

    def __del__(self):
        """Finalise cog and write game data to JSON file."""
        with open("games.json", mode="w", encoding="utf-8") as games:
            json.dump(self.games, games, indent=4)

    async def _block(self, _id: int):
        """Block a guild or user."""
        self.bot.blocked.add(_id)
        async with self.bot.db_connect() as db:
            await db.execute("INSERT OR IGNORE INTO blocked VALUES (?)", (_id,))
            await db.commit()

    async def _get_game_info(self, game_dir: str):
        """"Retrieve the Nexus Mods game info for the specified game directory."""
        async with self.bot.session.get(
            f"https://www.nexusmods.com/{game_dir}", headers={"User-Agent": "Mozilla/5.0"}
        ) as res:
            content = (await res.content.read(700)).decode("utf-8")
            if (game_name := GAME_NAME_RE.search(content)) and (game_id := GAME_ID_RE.search(content)):
                result = self.games[game_dir] = {
                    game_name.group("game_name"): f"&game_id={game_id.group('game_id')}&include_adult=1&timeout=15000"
                }
                return result
        return None

    async def set_filter(self, ctx, config: dict, game_filter: str, destination: str, channel_id=0):
        """Parse `game_filter` to set filter for game in `config`."""
        if preset := self.games.get(game_filter) or await self._get_game_info(game_filter):
            config.update(preset)
            async with self.bot.db_connect() as db:
                if channel_id:
                    await db.execute("INSERT OR IGNORE INTO channel VALUES (?, ?)", (channel_id, ctx.guild.id))
                for game_name, game_filter in preset.items():
                    await db.execute(
                        "INSERT OR REPLACE INTO game VALUES (?, ?, ?, ?)", (ctx.guild.id, channel_id, game_name, game_filter)
                    )
                    await ctx.send(
                        embed=feedback_embed(
                            "Default Nexus Mods search API filter set for "
                            f"`{game_name}` to: `{game_filter}` in {destination}."
                        )
                    )
                return await db.commit()

        if len(terms := game_filter.split()) < 2:
            return await ctx.send(embed=feedback_embed("Invalid arguments.", False))

        game_name, game_filter = " ".join(terms[:-1]).replace("`", "'"), terms[-1].replace("`", "'")
        if len(game_name) > 100:
            return await ctx.send(embed=feedback_embed("Game name too long (max length = 100).", False))
        if len(game_filter) > 1024:
            return await ctx.send(embed=feedback_embed("Filter too long (max length = 1024).", False))

        if game_name in config or len(config) <= 5:
            config[game_name] = game_filter
            async with self.bot.db_connect() as db:
                if channel_id:
                    await db.execute("INSERT OR REPLACE INTO channel VALUES (?, ?)", (channel_id, ctx.guild.id))
                await db.execute(
                    "INSERT OR REPLACE INTO game VALUES (?, ?, ?, ?)", (ctx.guild.id, channel_id, game_name, game_filter)
                )
                await db.commit()
            await ctx.send(
                embed=feedback_embed(
                    "Default Nexus Mods search API filter set for " f"`{game_name}` to: `{game_filter}` in {destination}."
                )
            )
        else:
            await ctx.send(embed=feedback_embed("Maximum of 5 games exceeded.", False))

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Block and leave guild if the bot's app owner is banned."""
        if user.id == getattr(self.bot, "app_owner_id", None):
            await self._block(guild.id)
            await guild.leave()

    @commands.command(aliases=["prefix"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setprefix(self, ctx, prefix: str):
        """Set guild prefix for bot commands."""
        if len(prefix) <= 3:
            self.bot.guild_configs[ctx.guild.id]["prefix"] = prefix
            async with self.bot.db_connect() as db:
                await db.execute("UPDATE guild SET prefix = ? WHERE id = ?", (prefix, ctx.guild.id))
                await db.commit()
            await ctx.send(embed=feedback_embed(f"Prefix set to `{prefix}`."))
        else:
            await ctx.send(embed=feedback_embed("Prefix too long (max length = 3).", False))

    @commands.command(aliases=["searchconfig", "ssc", "sc"])
    @delete_msg
    async def showsearchconfig(self, ctx):
        """List configured Nexus Mods default search filters for guild."""
        embed = discord.Embed(colour=14323253)
        embed.set_author(
            name="Nexus Mods Search Configuration",
            url="https://www.nexusmods.com/",
            icon_url="https://images.nexusmods.com/favicons/ReskinOrange/favicon-32x32.png",
        )
        embed.set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.avatar_url)
        if games := self.bot.guild_configs[ctx.guild.id]["channels"][ctx.channel.id]:
            embed.add_field(name="Channel-specific game filters in:", value=f"{ctx.channel.mention}", inline=False)
            for game_name, game_filter in games.items():
                embed.add_field(name=game_name, value=f"`{game_filter}`", inline=False)
        if games := self.bot.guild_configs[ctx.guild.id]["games"]:
            embed.add_field(name="Server default game filters in:", value=f"**{ctx.guild.name}**", inline=False)
            for game_name, game_filter in games.items():
                embed.add_field(name=game_name, value=f"`{game_filter}`", inline=False)
        elif not embed.fields:
            embed.description = ":x: No Nexus Mods search filters configured in this channel/server."
        await ctx.send(embed=embed)

    @commands.command(aliases=["setguildfilter", "setgf", "setsf"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setserverfilter(self, ctx, *, game_filter: str):
        """Set default Nexus Mods search API filter for game in server.

        Requires the 'Manage Server' permission or bot admin permissions.

        `game_filter` can be a game name with a Nexus Mods search API query string suffix, a game directory on the Nexus Mods
        site as shown in the URL, "all" for all games or "skyrimboth" for both Skyrim Classic and Special Edition.

        Examples
        --------

        Using a game name with search filter:

        `.setsf Farming Simulator 19 &game_id=2676&include_adult=1&timeout=15000`

        Applies filter for Farming Simulator 19 with adult mods included and a request timeout of 15000. Here the last term
        (separated by spaces) is used as filter for a URL such as:

        https://search.nexusmods.com/mods?terms=skyui&game_id=0&blocked_tags=&blocked_authors=&include_adult=1

        The preceding terms make up the game name.

        Using a game directory:

        `.setsf skyrimspecialedition`

        Applies the filter for Skyrim Special Edition.

        Command prefixes may vary per server.
        """
        await self.set_filter(
            ctx,
            self.bot.guild_configs[ctx.guild.id]["games"],
            game_filter,
            f"**{discord.utils.escape_markdown(ctx.guild.name)}**",
        )

    @commands.command(aliases=["setchf"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.channel)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setchannelfilter(self, ctx, *, game_filter: str):
        """Set Nexus Mods search API filter for game in channel.

        Requires the 'Manage Server' permission or bot admin permissions.

        `game_filter` can be a game name with a Nexus Mods search API query string suffix, a game directory on the Nexus Mods
        site as shown in the URL, "all" for all games or "skyrimboth" for both Skyrim Classic and Special Edition.

        Examples
        --------

        Using a game name with search filter:

        `.setchf Farming Simulator 19 &game_id=2676&include_adult=1&timeout=15000`

        Applies filter for Farming Simulator 19 with adult mods included and a request timeout of 15000. Here the last term
        (separated by spaces) is used as filter for a URL such as:

        https://search.nexusmods.com/mods?terms=skyui&game_id=0&blocked_tags=&blocked_authors=&include_adult=1

        The preceding terms make up the game name.

        Using a game directory:

        `.setsf skyrimspecialedition`

        Applies the filter for Skyrim Special Edition.

        Command prefixes may vary per server.
        """
        await self.set_filter(
            ctx,
            self.bot.guild_configs[ctx.guild.id]["channels"][ctx.channel.id],
            game_filter,
            ctx.channel.mention,
            ctx.channel.id,
        )

    @commands.command(aliases=["delsf", "rmsf"])
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def deleteserverfilter(self, ctx, *, game_name: str):
        """Delete Nexus Mods search API filter for game in guild."""
        try:
            del self.bot.guild_configs[ctx.guild.id]["games"][game_name]
        except KeyError:
            await ctx.send(embed=feedback_embed(f"Game `{game_name}` not found in server filters.", False))
        else:
            async with self.bot.db_connect() as db:
                await db.execute("PRAGMA foreign_keys = ON")
                await db.execute(
                    "DELETE FROM game WHERE guild_id = ? AND channel_id = ? AND name = ?", (ctx.guild.id, 0, game_name)
                )
                await db.commit()
            await ctx.send(embed=feedback_embed(f"Server filter for `{game_name}` deleted."))

    @commands.command(aliases=["delchf", "rmchf"])
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def deletechannelfilter(self, ctx, *, game_name: str):
        """Delete Nexus Mods search API filter for game in channel."""
        try:
            del self.bot.guild_configs[ctx.guild.id]["channels"][ctx.channel.id][game_name]
        except KeyError:
            await ctx.send(embed=feedback_embed(f"Game `{game_name}` not found in channel filters.", False))
        else:
            async with self.bot.db_connect() as db:
                await db.execute("PRAGMA foreign_keys = ON")
                if not self.bot.guild_configs[ctx.guild.id]["channels"]:
                    await db.execute("DELETE FROM channel WHERE id = ?", (ctx.channel.id,))
                else:
                    await db.execute("DELETE FROM game WHERE channel_id = ? AND name = ?", (ctx.channel.id, game_name))
                await db.commit()
            await ctx.send(embed=feedback_embed(f"Channel filter for `{game_name}` deleted."))

    @commands.command(aliases=["clearsf", "csf"])
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def clearserverfilters(self, ctx):
        """Clear Nexus Mods search API filters in guild."""
        self.bot.guild_configs[ctx.guild.id]["games"] = defaultdict(dict)
        async with self.bot.db_connect() as db:
            await db.execute("DELETE FROM game WHERE guild_id = ? AND channel_id = 0", (ctx.guild.id,))
            await db.commit()
        await ctx.send(embed=feedback_embed("Server filters cleared."))

    @commands.command(aliases=["clearchf", "cchf"])
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def clearchannelfilters(self, ctx):
        """Clear Nexus Mods search API filters in channel."""
        self.bot.guild_configs[ctx.guild.id]["channels"][ctx.channel.id] = defaultdict(dict)
        async with self.bot.db_connect() as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("DELETE FROM channel WHERE id = ?", (ctx.channel.id,))
            await db.commit()
        await ctx.send(embed=feedback_embed("Channel filters cleared."))

    @commands.command(aliases=["showblacklist"])
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.channel)
    @delete_msg
    async def showblocked(self, ctx):
        """Send embed with blocked IDs."""
        description = ", ".join(str(_id) for _id in self.bot.blocked)
        if not description:
            description = "No blocked IDs yet."
        elif len(description) > 2048:
            description = f"{description[:2045]}..."
        embed = discord.Embed(
            title=":stop_sign: Blocked IDs", description=description, colour=ctx.guild.me.colour.value or 14323253
        )
        embed.set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(aliases=["blacklist"])
    @commands.is_owner()
    @delete_msg
    async def block(self, ctx, _id: int):
        """Block a guild or user from using the bot."""
        if guild := self.bot.get_guild(_id):
            await guild.leave()
        await self._block(_id)
        await ctx.send(embed=feedback_embed(f"Blocked ID `{_id}`."))

    @commands.command(aliases=["unblacklist"])
    @commands.is_owner()
    async def unblock(self, ctx, _id: int):
        """Unblock a guild or user from using the bot."""
        try:
            self.bot.blocked.remove(_id)
        except KeyError:
            await ctx.send(embed=feedback_embed(f"ID `{_id}` was not blocked.", False))
        else:
            await ctx.send(embed=feedback_embed(f"ID `{_id}` is no longer blocked."))
        finally:
            async with self.bot.db_connect() as db:
                await db.execute("DELETE FROM blocked WHERE id = (?)", (_id,))
                await db.commit()

    @commands.command(aliases=["admins"])
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.channel)
    @delete_msg
    async def showadmins(self, ctx):
        """Send embed with admin IDs."""
        description = ", ".join(str(_id) for _id in self.bot.owner_ids)
        if not description:
            description = "No admins."
        elif len(description) > 2048:
            description = f"{description[:2045]}..."
        embed = discord.Embed(
            title=":sunglasses: Bot Admin IDs", description=description, colour=ctx.guild.me.colour.value or 14323253
        )
        embed.set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(aliases=["admin"])
    @commands.is_owner()
    @delete_msg
    async def makeadmin(self, ctx, user_id: int):
        """Make user a bot admin."""
        self.bot.owner_ids.add(user_id)
        async with self.bot.db_connect() as db:
            await db.execute("INSERT OR IGNORE INTO admin VALUES (?)", (user_id,))
            await db.commit()
        await ctx.send(embed=feedback_embed(f"Added {user_id} as admin."))

    @commands.command(aliases=["rmadmin"])
    @commands.is_owner()
    async def deladmin(self, ctx, user_id: int):
        """Remove user as bot admin if not app owner."""
        if user_id == getattr(self.bot, "app_owner_id", None):
            return await ctx.send(embed=feedback_embed("Cannot remove app owner.", False))
        try:
            self.bot.owner_ids.remove(user_id)
            async with self.bot.db_connect() as db:
                await db.execute("DELETE FROM admin WHERE id = ?", (user_id,))
                await db.commit()
        except KeyError:
            await ctx.send(embed=feedback_embed(f"User `{user_id}` was not an admin.", False))
        else:
            await ctx.send(embed=feedback_embed(f"Removed `{user_id}` as admin."))


def setup(bot):
    """Add this cog to bot."""
    bot.add_cog(DB(bot))
