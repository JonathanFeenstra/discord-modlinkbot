"""
General
=======

Cog with general utilities.

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
import time
from contextlib import suppress
from functools import wraps

import discord
from discord.ext import commands


def delete_msg(coro):
    """Delete command message of the decorated command before invoking it."""

    @wraps(coro)
    async def wrapper(self, ctx, *args, **kwargs):
        """Decorator wrapper."""
        if ctx.channel.permissions_for(ctx.me).manage_messages:
            with suppress(discord.NotFound):
                await ctx.message.delete()
        await coro(self, ctx, *args, **kwargs)

    return wrapper


class General(commands.Cog):
    """Cog to enable general utility commands."""

    def __init__(self, bot):
        """Initialise cog."""
        self.bot = bot

    @commands.command()
    @delete_msg
    async def invite(self, ctx):
        """Send bot invite link."""
        modlinkbot = ctx.guild.me
        embed = discord.Embed(
            title=f":link: Add {modlinkbot.name} to your server",
            description=f"Use [this link](https://discordapp.com/oauth2/authorize?client_id={modlinkbot.id}"
            f"&permissions=67136705&scope=bot) to add {modlinkbot.mention} to your server. The permissions 'Create Invite', "
            "'Change Nickname', 'View Audit Log' and 'Manage Messages' are optional. Use `.help` for setup instructions.",
            colour=modlinkbot.colour.value or 14323253,
        )
        embed.set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(aliases=["latency"])
    @commands.cooldown(rate=1, per=3, type=commands.BucketType.channel)
    @delete_msg
    async def ping(self, ctx):
        """Send latency in ms."""
        embed = discord.Embed(title=":satellite: Ping", colour=ctx.guild.me.colour.value or 14323253)
        start = time.perf_counter()
        await ctx.trigger_typing()
        end = time.perf_counter()
        embed.description = (
            f"**Ping:** {round((end - start) * 1000, 1)} ms\n" f"**Ws:** {round(self.bot.latency * 1000, 1)} ms"
        )
        embed.set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(aliases=["prefix"])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.check_any(commands.is_owner(), commands.has_permissions(manage_guild=True))
    async def setprefix(self, ctx, prefix: str):
        """Set guild prefix for bot commands."""
        if len(prefix) <= 3:
            async with self.bot.db_connect() as con:
                await con.execute("UPDATE guild SET prefix = ? WHERE guild_id = ?", (prefix, ctx.guild.id))
                await con.commit()
            await ctx.send(f":white_check_mark: Prefix set to `{prefix}`.")
        else:
            await ctx.send(":x: Prefix too long (max length = 3).")

    @commands.command()
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


def setup(bot):
    """Add this cog to bot."""
    bot.add_cog(General(bot))
