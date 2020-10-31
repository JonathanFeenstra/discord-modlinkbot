"""
Util
====

Cog with general utilities.

:copyright: (C) 2019-2020 Jonathan Feenstra
:license: GPL-3.0

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
import functools
import time
from contextlib import suppress

import discord
from discord.ext import commands


def delete_msg(coro):
    """Delete command message of the decorated command before invoking it.

    :param coro: command coroutine
    :return: decorated command
    :rtype: function
    """
    @functools.wraps(coro)
    async def wrapper(self, ctx, *args, **kwargs):
        """Decorator wrapper.

        :param discord.ext.commands.Cog self: cog to which command belongs
        :param discord.ext.Commands.Context ctx: event context
        """
        if ctx.channel.permissions_for(ctx.me).manage_messages:
            with suppress(discord.NotFound):
                await ctx.message.delete()
        await coro(self, ctx, *args, **kwargs)
    return wrapper


def feedback_embed(description: str, success=True):
    """Return feedback embed with description.

    :param str description: embed description
    :param bool success: whether to return a positive feedback embed
    :return: feedback embed
    :rtype: discord.Embed
    """
    if success:
        return discord.Embed(description=f':white_check_mark: {description}',
                             colour=7844437)
    return discord.Embed(description=f':x: {description}', colour=14495300)


class SendErrorFeedback:
    """"Context manager to send feedback embed with error message on errors."""

    def __init__(self, ctx):
        """Initialise context manager.

        :param discord.ext.Commands.Context ctx: event context
        """
        self.ctx = ctx

    async def __aenter__(self):
        """Enter context.

        :return: self
        :rtype: SendErrorFeedback
        """
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Exit context and send feedback embed if exceptions occured.

        :param type exc_type: exception type or None
        :param Exception exc: exception or None
        :param traceback tb: traceback or None
        """
        if exc is not None:
            await self.ctx.send(embed=feedback_embed(f'`{exc_type.__name__}: {exc}`', False))


class Util(commands.Cog):
    """Cog to enable general utility commands."""

    def __init__(self, bot):
        """Initialise cog.

        :param discord.Client bot: bot to add cog to
        """
        self.bot = bot

    @commands.command()
    async def invite(self, ctx):
        """Send bot invite link.

        :param discord.ext.Commands.Context ctx: event context
        """
        me = ctx.guild.me
        invite_link = f'https://discordapp.com/oauth2/authorize?client_id={me.id}&permissions=672021779&scope=bot'
        embed = discord.Embed(
            title=f':link: Add {me.name} to your server',
            description=f'Use [this link]({invite_link}) to add {me.mention} to your server. '
                        "The permissions 'Create Invite', 'Change Nickname', "
                        "'View Audit Log' and 'Manage Messages' are optional. Use `.help` for "
                        "setup instructions.",
            colour=me.colour.value or 14323253)
        embed.set_footer(text=f'Prompted by @{ctx.author}', icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(aliases=['latency'])
    @commands.cooldown(rate=1, per=3, type=commands.BucketType.channel)
    async def ping(self, ctx):
        """Send latency in ms.

        :param discord.ext.Commands.Context ctx: event context
        """
        embed = discord.Embed(title=':satellite: Ping',
                              description="Testing ping...",
                              colour=ctx.guild.me.colour.value or 14323253)
        start = time.perf_counter()
        message = await ctx.send(embed=embed)
        end = time.perf_counter()
        embed.description = (f"**Ping:** {round((end - start) * 1000, 1)} ms\n"
                             f"**Ws:** {round(self.bot.latency * 1000, 1)} ms")
        await message.edit(embed=embed)

    @commands.command(aliases=['guildlist', 'servers', 'serverlist'])
    @commands.cooldown(rate=1, per=30, type=commands.BucketType.channel)
    async def guilds(self, ctx):
        """Send list of guilds that bot is a member of.

        :param discord.ext.Commands.Context ctx: event context
        """
        guilds_info = [f"```\n{'Name': <32}Members  Joined (d/m/y)"]

        for guild in self.bot.guilds:
            name = guild.name if len(guild.name) <= 30 else f'{guild.name[:27]}...'
            member_count = '{0:,}'.format(guild.member_count).replace(',', ' ')
            join_date = self.bot.guild_configs[guild.id]['joined_at'].strftime('%d/%m/%Y')
            guilds_info.append(f'{name: <32}{member_count: <9}{join_date}')

        description = '\n'.join(guilds_info) + '```'
        if len(description) > 2048:
            description = f'{description[:2042]}...```'

        embed = discord.Embed(title=':busts_in_silhouette: Servers',
                              description=description,
                              colour=ctx.guild.me.colour.value or 14323253)
        embed.set_footer(text=f'Prompted by @{ctx.author}', icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)


def setup(bot):
    """Add this cog to bot.

    :param discord.Client bot: bot to add cog to
    """
    bot.add_cog(Util(bot))
