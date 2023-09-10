"""
General
=======

Extension with general utilities.

Copyright (C) 2019-2023 Jonathan Feenstra

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
import time

import discord
from discord.ext import commands, menus

from bot import ModLinkBot
from core.constants import DEFAULT_COLOUR
from core.pagination import BlockedPageSource, OwnerPageSource


class General(commands.Cog):
    """Cog to enable general utility commands."""

    def __init__(self, bot: ModLinkBot) -> None:
        self.bot = bot

    @commands.hybrid_command()
    async def invite(self, ctx: commands.Context) -> None:
        """Send bot invite link."""
        modlinkbot = ctx.me
        embed = discord.Embed(
            title=f":link: Add {modlinkbot.name} to your server",
            description=f"Use [this link]({self.bot.oauth_url}) to add {modlinkbot.mention} to your server. "
            "The permissions 'Create Invite' and 'View Audit Log' are optional. Use `.help addgame` for info about setting "
            "up search tasks.",
            colour=modlinkbot.colour.value or DEFAULT_COLOUR,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(aliases=["latency"])
    @commands.cooldown(rate=1, per=3, type=commands.BucketType.channel)
    async def ping(self, ctx: commands.Context) -> None:
        """Send latency in ms."""
        embed = discord.Embed(title=":satellite: Ping", colour=ctx.me.colour.value or DEFAULT_COLOUR)
        start = time.perf_counter()
        await ctx.typing()
        end = time.perf_counter()
        embed.description = f"**Ping:** {round((end - start) * 1000, 1)} ms\n**Ws:** {round(self.bot.latency * 1000, 1)} ms"
        await ctx.send(embed=embed)

    @commands.hybrid_command(aliases=["prefix"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.guild_only()
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setprefix(self, ctx: commands.Context, prefix: str) -> None:
        """Set guild prefix for bot commands."""
        if len(prefix) <= 3:
            async with self.bot.db_connect() as con:
                await con.set_guild_prefix(ctx.guild.id, prefix)
                await con.commit()
            await ctx.send(f":white_check_mark: Prefix set to `{prefix}`.")
        else:
            await ctx.send(":x: Prefix too long (max length = 3).")

    @commands.hybrid_command(aliases=["blocked"])
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.channel)
    async def showblocked(self, ctx: commands.Context) -> None:
        """Send embed with blocked IDs."""
        await menus.MenuPages(source=BlockedPageSource(sorted(self.bot.blocked)), clear_reactions_after=True).start(ctx)

    @commands.hybrid_command(aliases=["showadmins", "owners", "admins"])
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.channel)
    async def showowners(self, ctx: commands.Context) -> None:
        """Send embed with owners."""
        await menus.MenuPages(source=OwnerPageSource(sorted(self.bot.owner_ids)), clear_reactions_after=True).start(ctx)


async def setup(bot: ModLinkBot) -> None:
    await bot.add_cog(General(bot))
