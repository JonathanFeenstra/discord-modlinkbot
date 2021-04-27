"""
Games
=====

Extension for management of server/channel-specific game configurations.

Copyright (C) 2019-2021 Jonathan Feenstra

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import re

import discord
from aiohttp import ClientResponseError
from discord.ext import commands

from aionxm import NotFound

GAME_DOMAIN_RE = re.compile(r"(?:https?://(?:www\.)?nexusmods\.com/)?(?P<game_dir>[a-zA-Z0-9]+)/?$")
INCLUDE_NSFW_MODS = {0: "Never", 1: "Always", 2: "Only in NSFW channels"}


def parse_game_dir(game_query: str):
    """Parse game directory and return canonical name or raise `UserInputError` if invalid."""
    if match := GAME_DOMAIN_RE.match("".join(game_query.split()).lower()):
        return match.group("game_dir")
    raise commands.UserInputError(f"Invalid game directory {repr(game_query)}.")


class Games(commands.Cog):
    """Cog to manage game configurations per server/channel."""

    def __init__(self, bot):
        self.bot = bot
        self.games = {}
        self.bot.loop.create_task(self._update_game_data())

    async def _add_search_task(self, ctx, game_query: str, channel_id=0):
        try:
            game_dir = parse_game_dir(game_query)
            game_name, game_id = await self._get_game_id_and_name(game_dir)
        except (ClientResponseError, NotFound):
            return await ctx.send(f":x: Game https://www.nexusmods.com/{game_query} not found.")

        async with self.bot.db_connect() as con:
            if await con.fetch_search_task_count(ctx.guild.id, channel_id) >= 5:
                return await ctx.send(":x: Maximum of 5 games exceeded.")
            if channel_id:
                await con.insert_channel(channel_id, ctx.guild.id)

            await con.insert_search_task(ctx.guild.id, channel_id, game_id)
            destination = ctx.channel.mention if channel_id else f"**{ctx.guild.name}**"
            await ctx.send(f":white_check_mark: **{game_name}** added to games to search for in {destination}.")
            await con.commit()

    async def _get_game_id_and_name(self, game_dir: str) -> tuple[int, str]:
        if not (game := self.games.get(game_dir)):
            await self._update_game_data()
            if not (game := self.games.get(game_dir)):
                # fallback to web scraping
                return await self.bot.request_handler.scrape_game_id_and_name(game_dir)
        return game

    async def _update_game_data(self):
        async with self.bot.db_connect() as con:
            try:
                nexus_games = await self.bot.request_handler.get_all_games()
            except ClientResponseError:
                pass
            else:
                for game in nexus_games:
                    await con.insert_game(game["id"], game["domain_name"], game["name"])
                await con.commit()
            for game_id, game_dir, game_name in await con.fetch_games():
                self.games[game_dir] = (game_name, game_id)

    @commands.command(aliases=["nsfw"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setnsfw(self, ctx, flag: int):
        """Set NSFW flag for guild for when to include adult results (0=never; 1=always; 2=only in NSFW channels)."""
        if 0 <= flag <= 2:
            async with self.bot.db_connect() as con:
                await con.set_guild_nsfw_flag(ctx.guild.id, flag)
                await con.commit()
            await ctx.send(f":white_check_mark: NSFW flag set to {flag}.")
        else:
            await ctx.send(":x: NSFW flag must be 0 (never), 1 (always), or 2 (only in NSFW channels).")

    @commands.command(aliases=["games"])
    async def showgames(self, ctx):
        """List configured Nexus Mods games to search mods for in server/channel."""
        embed = discord.Embed(colour=self.bot.DEFAULT_COLOUR)
        embed.set_author(
            name="Nexus Mods Search Configuration",
            url="https://www.nexusmods.com/",
            icon_url="https://images.nexusmods.com/favicons/ReskinOrange/favicon-32x32.png",
        )
        async with self.bot.db_connect() as con:
            if games := await con.fetch_search_tasks_game_name_and_channel_id(ctx.guild.id, ctx.channel.id):
                channel_games, guild_games = [], []
                for game_name, channel_id in games:
                    if channel_id == ctx.channel.id:
                        channel_games.append(game_name)
                    elif channel_id == 0:
                        guild_games.append(game_name)
                if channel_games:
                    embed.add_field(name=f"Games in #{ctx.channel.name}", value=", ".join(channel_games), inline=False)
                if guild_games:
                    embed.add_field(
                        name=f"Default games in **{ctx.guild.name}**", value=", ".join(guild_games), inline=False
                    )
                embed.add_field(
                    name="Include NSFW mods?", value=INCLUDE_NSFW_MODS[await con.fetch_guild_nsfw_flag(ctx.guild.id)]
                )
            else:
                embed.description = ":x: No games are configured in this channel/server."
        await ctx.send(embed=embed)

    @commands.group(aliases=["ag"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def addgame(self, ctx):
        """Add a game to search mods for in the server or channel using the name from the Nexus Mods URL.

        Examples:

        # Add Kingdom Come Deliverance to the server's default games:
        .addgame server kingdomcomedeliverance
        # Add Skyrim Special Edition to channel games (overrides the server's default games):
        .addgame channel skyrimspecialedition
        """
        await ctx.trigger_typing()
        if ctx.invoked_subcommand is None:
            if ctx.subcommand_passed:
                await self.addgame_server(ctx, game_query=ctx.subcommand_passed)
            else:
                await ctx.send(":x: No game specified.")

    @addgame.command(name="server", aliases=["guild", "s", "g"])
    async def addgame_server(self, ctx, *, game_query: str):
        """Add a game to search mods for in the server using the name from the Nexus Mods URL.

        Example:
        # Add Kingdom Come Deliverance to the server's default games:
        .addgame server kingdomcomedeliverance
        """
        await ctx.trigger_typing()
        await self._add_search_task(ctx, game_query)

    @addgame.command(name="channel", aliases=["c"])
    async def addgame_channel(self, ctx, *, game_query: str):
        """Add a game to search mods for in the channel using the name from the Nexus Mods URL.

        Example:
         # Add Skyrim Special Edition to channel games (overrides the server's default games):
        .addgame channel skyrimspecialedition
        """
        await ctx.trigger_typing()
        await self._add_search_task(ctx, game_query, ctx.channel.id)

    @commands.group(aliases=["dg"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def delgame(self, ctx):
        """Delete a game to search mods for in the server or channel."""
        await ctx.trigger_typing()
        if ctx.invoked_subcommand is None:
            if game_query := ctx.subcommand_passed:
                game_dir = parse_game_dir(game_query)
                async with self.bot.db_connect() as con:
                    if await con.fetch_channel_has_search_task(ctx.channel.id, game_dir):
                        await self.delgame_channel(ctx, game_query=game_dir)
                    else:
                        await self.delgame_server(ctx, game_query=game_dir)
            else:
                await ctx.send(":x: No game specified.")

    @delgame.command(name="server", aliases=["guild", "s", "g"])
    async def delgame_server(self, ctx, *, game_query: str):
        """Delete a game to search mods for in the server."""
        await ctx.trigger_typing()
        game_dir = parse_game_dir(game_query)
        async with self.bot.db_connect() as con:
            await con.enable_foreign_keys()
            if game := await con.fetch_guild_search_task_game_id_and_name(ctx.guild.id, game_dir):
                game_id, game_name = game
                await con.delete_search_task(ctx.guild.id, 0, game_id)
                await con.commit()
                await ctx.send(f":white_check_mark: **{game_name}** deleted from server games.")
            else:
                await ctx.send(f":x: Game `{game_dir}` not found in server games.")

    @delgame.command(name="channel", aliases=["c"])
    async def delgame_channel(self, ctx, *, game_query: str):
        """Delete a game to search mods for in the channel."""
        await ctx.trigger_typing()
        game_dir = parse_game_dir(game_query)
        async with self.bot.db_connect() as con:
            if game := await con.fetch_channel_search_task_game_id_and_name(ctx.channel.id, game_dir):
                game_id, game_name = game
                if await con.fetch_channel_has_any_other_search_tasks(ctx.channel.id, game_id):
                    await con.delete_channel_search_task(ctx.channel.id, game_id)
                else:
                    await con.enable_foreign_keys()
                    await con.delete_channel(ctx.channel.id)
                await con.commit()
                await ctx.send(f":white_check_mark: **{game_name}** deleted from channel games.")
            else:
                await ctx.send(f":x: Game `{game_dir}` not found in channel games.")

    @commands.group(aliases=["reset"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def clear(self, ctx):
        """Clear games to search mods for in the server or channel."""
        await ctx.trigger_typing()
        if ctx.invoked_subcommand is None:
            if ctx.subcommand_passed:
                return await ctx.send(
                    f":x: Invalid subcommand {repr(ctx.subcommand_passed)} (must be `channel` or `server`)."
                )
            async with self.bot.db_connect() as con:
                if await con.fetch_channel_has_any_search_tasks(ctx.channel.id):
                    await self.clear_channel(ctx)
                else:
                    await self.clear_server(ctx)

    @clear.command(name="server", aliases=["guild", "s", "g"])
    async def clear_server(self, ctx):
        """Clear games to search mods for in the server."""
        await ctx.trigger_typing()
        async with self.bot.db_connect() as con:
            await con.clear_guild_search_tasks(ctx.guild.id)
            await con.commit()
        await ctx.send(":white_check_mark: Server games cleared.")

    @clear.command(name="channel", aliases=["c"])
    async def clear_channel(self, ctx):
        """Clear games to search mods for in the channel."""
        await ctx.trigger_typing()
        async with self.bot.db_connect() as con:
            await con.enable_foreign_keys()
            await con.delete_channel(ctx.channel.id)
            await con.commit()
        await ctx.send(":white_check_mark: Channel games cleared.")


def setup(bot):
    bot.add_cog(Games(bot))
