"""
Util
====

Cog with general utilities.

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


class Util(commands.Cog):
    """Cog to enable general utility commands."""

    def __init__(self, bot):
        """Initialise cog."""
        self.bot = bot

    @commands.command()
    @delete_msg
    async def invite(self, ctx):
        """Send bot invite link."""
        me = ctx.guild.me
        embed = discord.Embed(
            title=f":link: Add {me.name} to your server",
            description=f"Use [this link](https://discordapp.com/oauth2/authorize?client_id={me.id}&permissions=67136705"
            f"&scope=bot) to add {me.mention} to your server. The permissions 'Create Invite', 'Change Nickname'"
            ", 'View Audit Log' and 'Manage Messages' are optional. Use `.help` for setup instructions.",
            colour=me.colour.value or 14323253,
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


def setup(bot):
    """Add this cog to bot."""
    bot.add_cog(Util(bot))
