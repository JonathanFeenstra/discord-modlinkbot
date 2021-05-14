"""
General
=======

Extension with general utilities.

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
import time

import discord
from discord.ext import commands


class General(commands.Cog):
    """Cog to enable general utility commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command()
    async def invite(self, ctx: commands.Context) -> None:
        """Send bot invite link."""
        modlinkbot = ctx.me
        embed = discord.Embed(
            title=f":link: Add {modlinkbot.name} to your server",
            description=f"Use [this link]({self.bot.oauth_url}) to add {modlinkbot.mention} to your server. "
            "The permissions 'Create Invite' and 'View Audit Log' are optional. Use `.help addgame` for info about setting "
            "up search tasks.",
            colour=modlinkbot.colour.value or self.bot.DEFAULT_COLOUR,
        )
        await ctx.send(embed=embed)

    @commands.command(aliases=["latency"])
    @commands.cooldown(rate=1, per=3, type=commands.BucketType.channel)
    async def ping(self, ctx: commands.Context) -> None:
        """Send latency in ms."""
        embed = discord.Embed(title=":satellite: Ping", colour=ctx.me.colour.value or self.bot.DEFAULT_COLOUR)
        start = time.perf_counter()
        await ctx.trigger_typing()
        end = time.perf_counter()
        embed.description = (
            f"**Ping:** {round((end - start) * 1000, 1)} ms\n" f"**Ws:** {round(self.bot.latency * 1000, 1)} ms"
        )
        await ctx.send(embed=embed)

    @commands.command(aliases=["prefix"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
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

    @commands.command(aliases=["blocked"])
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.channel)
    async def showblocked(self, ctx: commands.Context) -> None:
        """Send embed with blocked IDs."""
        description = ", ".join(str(_id) for _id in self.bot.blocked)
        if not description:
            description = "No blocked IDs yet."
        elif len(description) > 2048:
            description = f"{description[:2045]}..."
        embed = discord.Embed(
            title=":stop_sign: Blocked IDs", description=description, colour=ctx.me.colour.value or self.bot.DEFAULT_COLOUR
        )
        await ctx.send(embed=embed)

    @commands.command(aliases=["showadmins", "owners", "admins"])
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.channel)
    async def showowners(self, ctx: commands.Context) -> None:
        """Send embed with owners."""
        description = ", ".join(f"<@{owner_id}>" for owner_id in self.bot.owner_ids)
        if len(description) > 2048:
            description = f"{description[:2045]}..."
        embed = discord.Embed(
            title=":sunglasses: Bot owners", description=description, colour=ctx.me.colour.value or self.bot.DEFAULT_COLOUR
        )
        await ctx.send(embed=embed)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(General(bot))
