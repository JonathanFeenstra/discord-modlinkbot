"""
Games
=====

Extension for management of server/channel-specific game configurations.

Copyright (C) 2019-2022 Jonathan Feenstra

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
from contextlib import AsyncExitStack
from typing import Dict, List, Optional

import discord
from aiohttp import ClientResponseError
from discord import app_commands
from discord.ext import commands

from bot import ModLinkBot
from core.aionxm import NotFound
from core.constants import DEFAULT_COLOUR
from core.models import Game, PartialGame

GAME_PATH_RE = re.compile(r"(?:https?://(?:www\.)?nexusmods\.com/)?(?P<path>[a-zA-Z0-9]+)/?$")
INCLUDE_NSFW_MODS = {0: "Never", 1: "Always", 2: "Only in NSFW channels"}


def parse_game_path(game_query: str) -> str:
    """Parse game directory and return canonical name or raise `UserInputError` if invalid."""
    if match := GAME_PATH_RE.match("".join(game_query.split())):
        return match.group("path")
    raise commands.UserInputError(f"Invalid game path {repr(game_query)}.")


class Games(commands.Cog):
    """Cog to manage game configurations per server/channel."""

    def __init__(self, bot: ModLinkBot) -> None:
        self.bot = bot
        self.games: Dict[str, PartialGame] = {}

    async def cog_load(self) -> None:
        """Called whent the cog gets loaded."""
        await self._update_game_data()

    async def _add_search_task(
        self, ctx: commands.Context, game_query: str, channel: Optional[discord.TextChannel] = None
    ) -> Optional[discord.Message]:
        try:
            game_path = parse_game_path(game_query)
            game_id, game_name = await self._get_game_id_and_name(game_path)
        except (ClientResponseError, NotFound):
            return await ctx.send(f":x: Game https://www.nexusmods.com/{game_query} not found.")

        async with self.bot.db_connect() as con:
            db_channel_id = channel.id if channel else 0
            if await con.fetch_search_task_count(ctx.guild.id, db_channel_id) >= 5:
                return await ctx.send(":x: Maximum of 5 games exceeded.")
            if channel is not None:
                await con.insert_channel(channel.id, ctx.guild.id)

            await con.insert_search_task(ctx.guild.id, db_channel_id, game_id)
            destination = channel.mention if channel else f"**{ctx.guild.name}**"
            await self._send_add_game_embed(ctx, Game(game_id, game_path, game_name), destination)
            await con.commit()

    async def _send_add_game_embed(self, ctx: commands.Context, game: Game, destination: str) -> None:
        game_url = f"https://nexusmods.com/{game.path}"
        embed = discord.Embed(
            description=f":white_check_mark: [**{game.name}**]({game_url}) added to games to search for in {destination}.",
            colour=DEFAULT_COLOUR,
        )
        embed.set_author(
            name=f"Nexus Mods | {game.name}",
            url=game_url,
            icon_url="https://images.nexusmods.com/favicons/ReskinOrange/favicon-32x32.png",
        )
        embed.set_thumbnail(url=f"https://staticdelivery.nexusmods.com/Images/games/4_3/tile_{game.id}.jpg")
        if game_info := await self._get_game_info(game.id):
            embed.add_field(name="Genre", value=game_info["genre"])
            embed.add_field(name="Mods", value=f"{game_info['mods']:,}")
            embed.add_field(name="Downloads", value=f"{game_info['downloads']:,}")
        await ctx.send(embed=embed)

    async def _get_game_id_and_name(self, game_path: str) -> PartialGame:
        if not (game := self.games.get(game_path)):
            await self._update_game_data(ignore_cache=True)
            if not (game := self.games.get(game_path)):
                # fallback to web scraping
                return await self.bot.request_handler.scrape_game_id_and_name(game_path)
        return game

    async def _get_game_info(self, game_id: int) -> Optional[Dict]:
        nexus_games = await self.bot.request_handler.get_all_games()
        for game in nexus_games:
            if game["id"] == game_id:
                return game
        return None

    async def _update_game_data(self, ignore_cache: bool = False) -> None:
        async with self.bot.db_connect() as con:
            try:
                async with AsyncExitStack() as exit_stack:
                    if ignore_cache:
                        await exit_stack.enter_async_context(self.bot.session.disabled())
                    nexus_games = await self.bot.request_handler.get_all_games()
            except ClientResponseError:
                pass
            else:
                for game in nexus_games:
                    await con.insert_game(Game(game["id"], game["domain_name"], game["name"]))
                await con.commit()
            for game_id, game_path, game_name in await con.fetch_games():
                self.games[game_path] = PartialGame(game_id, game_name)

    @commands.hybrid_command(aliases=["nsfw"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setnsfw(self, ctx: commands.Context, flag: int) -> None:
        """Set NSFW flag for guild for when to include adult results.

        0 = Never
        1 = Always
        2 = Only in NSFW channels
        """
        if 0 <= flag <= 2:
            async with self.bot.db_connect() as con:
                await con.set_guild_nsfw_flag(ctx.guild.id, flag)
                await con.commit()
            await ctx.send(f":white_check_mark: NSFW flag set to {flag}.")
        else:
            await ctx.send(":x: NSFW flag must be 0 (never), 1 (always), or 2 (only in NSFW channels).")

    @setnsfw.autocomplete("flag")
    async def _setnsfw_autocomplete(self, interaction: discord.Interaction, current: int) -> List[app_commands.Choice[int]]:
        return [
            app_commands.Choice(name="Never", value=0),
            app_commands.Choice(name="Always", value=1),
            app_commands.Choice(name="Only in NSFW channels", value=2),
        ]

    @commands.hybrid_command(aliases=["games"])
    async def showgames(self, ctx: commands.Context) -> None:
        """List configured Nexus Mods games to search mods for in server/channel."""
        embed = discord.Embed(colour=DEFAULT_COLOUR)
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

    @commands.hybrid_group(aliases=["ag"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def addgame(self, ctx: commands.Context) -> None:
        """Add a game to search mods for in the server or channel using the name from the Nexus Mods URL.

        Examples:

        - Add Kingdom Come Deliverance to the server's default games:
          .addgame server kingdomcomedeliverance
        - Add Skyrim Special Edition to channel games (overrides the server's default games):
          .addgame channel skyrimspecialedition
        """
        await ctx.typing()
        if ctx.invoked_subcommand is None:
            if ctx.subcommand_passed:
                await self.addgame_server(ctx, game_query=ctx.subcommand_passed)
            else:
                await ctx.send(":x: No game specified.")

    @addgame.command(name="server", aliases=["guild", "s", "g"])
    async def addgame_server(self, ctx: commands.Context, *, game_query: str) -> None:
        """Add a game to search mods for in the server using the name from the Nexus Mods URL.

        Example:
        - Add Kingdom Come Deliverance to the server's default games:
          .addgame server kingdomcomedeliverance
        """
        await ctx.typing()
        await self._add_search_task(ctx, game_query)

    @addgame.command(name="channel", aliases=["c"])
    async def addgame_channel(self, ctx: commands.Context, *, game_query: str) -> None:
        """Add a game to search mods for in the channel using the name from the Nexus Mods URL.

        Example:
        - Add Skyrim Special Edition to channel games (overrides the server's default games):
          .addgame channel skyrimspecialedition
        """
        await ctx.typing()
        await self._add_search_task(ctx, game_query, ctx.channel)

    @addgame_server.autocomplete("game_query")
    @addgame_channel.autocomplete("game_query")
    async def _addgame_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        current_lower = current.lower()
        return [
            app_commands.Choice(name=game.name, value=path)
            for path, game in self.games.items()
            if current_lower in path or current_lower in game.name.lower() or current_lower in str(game.id)
        ][:25]

    @commands.hybrid_group(aliases=["dg"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def delgame(self, ctx: commands.Context) -> None:
        """Delete a game to search mods for in the server or channel."""
        await ctx.typing()
        if ctx.invoked_subcommand is None:
            if game_query := ctx.subcommand_passed:
                game_path = parse_game_path(game_query)
                async with self.bot.db_connect() as con:
                    if await con.fetch_channel_has_search_task(ctx.channel.id, game_path):
                        await self.delgame_channel(ctx, game_query=game_path)
                    else:
                        await self.delgame_server(ctx, game_query=game_path)
            else:
                await ctx.send(":x: No game specified.")

    @delgame.command(name="server", aliases=["guild", "s", "g"])
    async def delgame_server(self, ctx: commands.Context, *, game_query: str) -> None:
        """Delete a game to search mods for in the server."""
        await ctx.typing()
        game_path = parse_game_path(game_query)
        async with self.bot.db_connect() as con:
            await con.enable_foreign_keys()
            if game := await con.fetch_guild_partial_game(ctx.guild.id, game_path):
                game_id, game_name = game
                await con.delete_search_task(ctx.guild.id, 0, game_id)
                await con.commit()
                await ctx.send(f":white_check_mark: **{game_name}** deleted from server games.")
            else:
                await ctx.send(f":x: Game `{game_path}` not found in server games.")

    @delgame.command(name="channel", aliases=["c"])
    async def delgame_channel(self, ctx: commands.Context, *, game_query: str) -> None:
        """Delete a game to search mods for in the channel."""
        await ctx.typing()
        game_path = parse_game_path(game_query)
        async with self.bot.db_connect() as con:
            if game := await con.fetch_channel_partial_game(ctx.channel.id, game_path):
                game_id, game_name = game
                if await con.fetch_channel_has_any_other_search_tasks(ctx.channel.id, game_id):
                    await con.delete_channel_search_task(ctx.channel.id, game_id)
                else:
                    await con.enable_foreign_keys()
                    await con.delete_channel(ctx.channel.id)
                await con.commit()
                await ctx.send(f":white_check_mark: **{game_name}** deleted from channel games.")
            else:
                await ctx.send(f":x: Game `{game_path}` not found in channel games.")

    @delgame_server.autocomplete("game_query")
    async def _delgame_server_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        current_lower = current.lower()
        async with self.bot.db_connect() as con:
            return [
                app_commands.Choice(name=game.name, value=game.path)
                for game in await con.fetch_guild_games(interaction.guild_id)
                if current_lower in game.name.lower() or current_lower in str(game.id)
            ][:25]

    @delgame_channel.autocomplete("game_query")
    async def _delgame_channel_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        current_lower = current.lower()
        async with self.bot.db_connect() as con:
            return [
                app_commands.Choice(name=game.name, value=game.path)
                for game in await con.fetch_channel_games(interaction.channel_id)
                if current_lower in game.name.lower() or current_lower in str(game.id)
            ][:25]

    @commands.hybrid_group(aliases=["reset"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def clear(self, ctx: commands.Context) -> Optional[discord.Message]:
        """Clear games to search mods for in the server or channel."""
        await ctx.typing()
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
    async def clear_server(self, ctx: commands.Context) -> None:
        """Clear games to search mods for in the server."""
        await ctx.typing()
        async with self.bot.db_connect() as con:
            await con.clear_guild_search_tasks(ctx.guild.id)
            await con.commit()
        await ctx.send(":white_check_mark: Server games cleared.")

    @clear.command(name="channel", aliases=["c"])
    async def clear_channel(self, ctx: commands.Context) -> None:
        """Clear games to search mods for in the channel."""
        await ctx.typing()
        async with self.bot.db_connect() as con:
            await con.enable_foreign_keys()
            await con.delete_channel(ctx.channel.id)
            await con.commit()
        await ctx.send(":white_check_mark: Channel games cleared.")


async def setup(bot: ModLinkBot) -> None:
    await bot.add_cog(Games(bot))
