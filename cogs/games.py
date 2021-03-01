"""
Games
=====

Cog for management of server/channel-specific game configurations.

Copyright (C) 2019-2021 Jonathan Feenstra

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
import discord
from discord.ext import commands
from aiohttp import ClientResponseError

from aionxm import NotFound


INCLUDE_NSFW_MODS = {0: "Never", 1: "Always", 2: "Only in NSFW channels"}


class Games(commands.Cog):
    """Cog to manage game configurations per server/channel."""

    def __init__(self, bot):
        """Initialise cog and update guild configuration with database content."""
        self.bot = bot
        self.games = {}
        self.bot.loop.create_task(self._update_games())

    async def _add_game(self, ctx, game_dir: str, channel_id=0):
        """Add game to search for in the specified channel (or guild if `channel_id=0`)."""
        try:
            game_name, game_id = await self._get_game(game_dir)
        except (ClientResponseError, NotFound):
            return await ctx.send(f":x: Game https://www.nexusmods.com/{game_dir} not found.")

        async with self.bot.db_connect() as con:
            async with con.execute(
                "SELECT COUNT (*) FROM search_task WHERE guild_id = ? AND channel_id = ?", (ctx.guild.id, channel_id)
            ) as cur:
                if (await cur.fetchone())[0] >= 5:
                    return await ctx.send(":x: Maximum of 5 games exceeded.")

            if channel_id:
                await con.execute("INSERT OR IGNORE INTO channel VALUES (?, ?)", (channel_id, ctx.guild.id))

            await con.execute("INSERT OR REPLACE INTO search_task VALUES (?, ?, ?)", (ctx.guild.id, channel_id, game_id))
            destination = ctx.channel.mention if channel_id else f"**{ctx.guild.name}**"
            await ctx.send(f":white_check_mark: **{game_name}** added to games to search for in {destination}.")
            await con.commit()

    async def _get_game(self, game_dir: str) -> tuple[int, str]:
        """Get game ID and name for the specified `game_dir`."""
        if not (game := self.games.get(game_dir)):
            await self._update_games()
            if not (game := self.games.get(game_dir)):
                # fallback to web scraping
                return await self.bot.nxm_request_handler.scrape_game_data(game_dir)
        return game

    async def _update_games(self):
        """Update games with data from database."""
        async with self.bot.db_connect() as con:
            try:
                nexus_games = await self.bot.nxm_request_handler.get_all_games()
            except ClientResponseError:
                pass
            else:
                for game in nexus_games:
                    await con.execute(
                        "INSERT OR IGNORE INTO game VALUES (?, ?, ?)", (game["id"], game["domain_name"], game["name"])
                    )
                await con.commit()
            db_games = await con.execute_fetchall("SELECT * FROM game")
            for game_id, game_dir, game_name in db_games:
                self.games[game_dir] = (game_name, game_id)

    @commands.command(aliases=["nsfw"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setnsfw(self, ctx, value: int):
        """Set NSFW value for guild for when to include adult results (0=never; 1=always; 2=only in NSFW channels)."""
        if 0 <= value <= 2:
            async with self.bot.db_connect() as con:
                await con.execute("UPDATE guild SET nsfw = ? WHERE guild_id = ?", (value, ctx.guild.id))
                await con.commit()
            await ctx.send(f":white_check_mark: NSFW value set to {value}.")
        else:
            await ctx.send(":x: NSFW value must be 0 (never), 1 (always), or 2 (only in NSFW channels).")

    @commands.command(aliases=["games"])
    async def showgames(self, ctx):
        """List configured Nexus Mods games to search mods for in server/channel."""
        embed = discord.Embed(colour=14323253)
        embed.set_author(
            name="Nexus Mods Search Configuration",
            url="https://www.nexusmods.com/",
            icon_url="https://images.nexusmods.com/favicons/ReskinOrange/favicon-32x32.png",
        )
        async with self.bot.db_connect() as con:
            if games := await con.execute_fetchall(
                """SELECT name, channel_id
                   FROM search_task s, game g
                   ON s.game_id = g.game_id
                   WHERE guild_id = ? AND channel_id IN (0, ?)""",
                (ctx.guild.id, ctx.channel.id),
            ):
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
                async with con.execute("SELECT nsfw FROM guild WHERE guild_id = ?", (ctx.guild.id,)) as cur:
                    nsfw = (await cur.fetchone())[0]
                    embed.add_field(name="Include NSFW mods?", value=INCLUDE_NSFW_MODS[nsfw])
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
        if ctx.invoked_subcommand is None:
            if ctx.subcommand_passed:
                await self.addgame_server(ctx, ctx.subcommand_passed)
            else:
                await ctx.send(":x: No game specified.")

    @addgame.command(name="server", aliases=["guild", "s", "g"])
    async def addgame_server(self, ctx, game_dir: str):
        """Add a game to search mods for in the server using the name from the Nexus Mods URL.

        Example:
        # Add Kingdom Come Deliverance to the server's default games:
        .addgame server kingdomcomedeliverance
        """
        await self._add_game(ctx, game_dir)

    @addgame.command(name="channel", aliases=["c"])
    async def addgame_channel(self, ctx, game_dir: str):
        """Add a game to search mods for in the channel using the name from the Nexus Mods URL.

        Example:
         # Add Skyrim Special Edition to channel games (overrides the server's default games):
        .addgame channel skyrimspecialedition
        """
        await self._add_game(ctx, game_dir, ctx.channel.id)

    @commands.group(aliases=["dg"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def delgame(self, ctx):
        """Delete a game to search mods for in the server or channel."""
        if ctx.invoked_subcommand is None:
            if ctx.subcommand_passed:
                async with self.bot.db_connect() as con:
                    async with con.execute(
                        "SELECT 1 FROM search_task s, game g ON s.game_id = g.game_id WHERE channel_id = ? AND dir = ?",
                        (ctx.channel.id, game_dir := ctx.subcommand_passed),
                    ) as cur:
                        if await cur.fetchone():
                            await self.delgame_channel(ctx, game_dir)
                        else:
                            await self.delgame_server(ctx, game_dir)
            else:
                await ctx.send(":x: No game specified.")

    @delgame.command(name="server", aliases=["guild", "s", "g"])
    async def delgame_server(self, ctx, game_dir: str):
        """Delete a game to search mods for in the server."""
        async with self.bot.db_connect() as con:
            await con.execute("PRAGMA foreign_keys = ON")
            async with con.execute(
                """SELECT s.game_id, g.name
                   FROM search_task s, game g
                   ON s.game_id = g.game_id
                   WHERE guild_id = ? AND channel_id = 0 AND dir = ?""",
                (ctx.guild.id, game_dir),
            ) as cur:
                if game := await cur.fetchone():
                    await con.execute(
                        "DELETE FROM search_task WHERE guild_id = ? AND channel_id = 0 AND game_id = ?",
                        (ctx.guild.id, game[0]),
                    )
                    await con.commit()
                    await ctx.send(f":white_check_mark: Server filter for **{game[1]}** deleted.")
                else:
                    await ctx.send(f":x: Game `{game_dir}` not found in server filters.")

    @delgame.command(name="channel", aliases=["c"])
    async def delgame_channel(self, ctx, game_dir: str):
        """Delete a game to search mods for in the channel."""
        async with self.bot.db_connect() as con:
            async with con.execute(
                """SELECT s.game_id, g.name
                   FROM search_task s, game g
                   ON s.game_id = g.game_id
                   WHERE channel_id = ? AND dir = ?""",
                (ctx.channel.id, game_dir),
            ) as cur:
                if game := await cur.fetchone():
                    async with con.execute("SELECT 1 FROM search_task WHERE game_id != ?", (game[0],)) as cur:
                        if await cur.fetchone():
                            await con.execute(
                                "DELETE FROM search_task WHERE channel_id = ? AND game_id = ?", (ctx.channel.id, game[0])
                            )
                        else:
                            await con.execute("PRAGMA foreign_keys = ON")
                            await con.execute("DELETE FROM channel WHERE channel_id = ?", (ctx.channel.id,))
                        await con.commit()
                    await ctx.send(f":white_check_mark: Channel filter for **{game[1]}** deleted.")
                else:
                    await ctx.send(f":x: Game `{game_dir}` not found in channel filters.")

    @commands.group(aliases=["reset"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def clear(self, ctx):
        """Clear games to search mods for in the server or channel."""
        if ctx.invoked_subcommand is None:
            if ctx.subcommand_passed:
                await ctx.send(f":x: Invalid subcommand {repr(ctx.subcommand_passed)} (must be `channel` or `server`).")
            async with self.bot.db_connect() as con:
                async with con.execute("SELECT 1 FROM search_task WHERE channel_id = ?", (ctx.channel.id,)) as cur:
                    if await cur.fetchone():
                        await self.clear_channel(ctx)
                    else:
                        await self.clear_server(ctx)

    @clear.command(name="server", aliases=["guild", "s", "g"])
    async def clear_server(self, ctx):
        """Clear games to search mods for in the server."""
        async with self.bot.db_connect() as con:
            await con.execute("DELETE FROM search_task WHERE guild_id = ? AND channel_id = 0", (ctx.guild.id,))
            await con.commit()
        await ctx.send(":white_check_mark: Server filters cleared.")

    @clear.command(name="channel", aliases=["c"])
    async def clear_channel(self, ctx):
        """"Clear games to search mods for in the channel."""
        async with self.bot.db_connect() as con:
            await con.execute("PRAGMA foreign_keys = ON")
            await con.execute("DELETE FROM channel WHERE channel_id = ?", (ctx.channel.id,))
            await con.commit()
        await ctx.send(":white_check_mark: Channel filters cleared.")


def setup(bot):
    """Add this cog to bot."""
    bot.add_cog(Games(bot))
