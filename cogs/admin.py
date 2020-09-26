"""
Admin
=====

Cog for providing bot owner/admin-only commands.

Partially based on:
https://github.com/AlexFlipnote/discord_bot.py/blob/master/cogs/admin.py

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
from ast import literal_eval
from urllib import request

from discord.ext import commands

from .util import SendErrorFeedback, delete_msg, feedback_embed


class Admin(commands.Cog):
    """Cog for providing owner/admin-only commands."""

    def __init__(self, bot):
        """Initialise cog.

        :param discord.Client bot: bot to add cog to
        """
        self.bot = bot

    async def cog_check(self, ctx):
        """
        Checks if context author is a bot admin for every command in this cog.

        :param discord.ext.Commands.Context ctx: event context
        :return bool: whether context author is a bot admin
        """
        return await self.bot.is_owner(ctx.author)

    @commands.command()
    async def config(self, ctx, attribute: str, *, value):
        """Set configuration setting to value.

        :param discord.ext.Commands.Context ctx: event context
        :param str attribute: attribute to set
        :param str value: value to set
        """
        async with SendErrorFeedback(ctx):
            setattr(self.bot.config, attribute.upper(), literal_eval(value))
        await ctx.send(f'Succesfully set `{attribute.upper()}={value}`.')

    @commands.command(aliases=['stop', 'shutdown', 'close', 'quit', 'exit'])
    @delete_msg
    async def logout(self, ctx):
        """Log out the bot.

        :param discord.ext.Commands.Context ctx: event context
        """
        print(f"{self.bot.user.name} has been logged out by {ctx.author}.")
        await self.bot.close()

    @commands.command(aliases=['username'])
    async def changeusername(self, ctx, *, username: str):
        """Change the bot's username.

        :param discord.ext.Commands.Context ctx: event context
        :param str username: username to change to
        """
        async with SendErrorFeedback(ctx):
            await self.bot.user.edit(username=username)
        await ctx.send(embed=feedback_embed(f'Username set to {repr(username)}.'))

    @commands.command(aliases=['nickname', 'nick'])
    async def changenickname(self, ctx, *, nickname: str):
        """Change the bot's nickname in server.

        :param discord.ext.Commands.Context ctx: event context
        :param str nickname: nickname to change to
        """
        async with SendErrorFeedback(ctx):
            await ctx.guild.me.edit(nick=nickname)
        await ctx.send(embed=feedback_embed(f'Nickname set to {repr(nickname)}.'))

    @commands.command(aliases=['avatar'])
    async def changeavatar(self, ctx, *, url: str = None):
        """Change the bot's avatar picture.

        Can also be done with an image attachment instead of a URL.

        :param discord.ext.Commands.Context ctx: event context
        :param str url: avatar url to change to
        """
        if url is None and len(ctx.message.attachments) == 1:
            url = ctx.message.attachments[0].url
        elif url:
            url = url.strip('<>')
        async with SendErrorFeedback(ctx):
            await self.bot.user.edit(
                avatar=request.urlopen(
                    request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                ).read()
            )
        await ctx.send(embed=feedback_embed('Avatar changed.'))


def setup(bot):
    """Add this cog to bot.

    :param discord.Client bot: bot to add cog to
    """
    bot.add_cog(Admin(bot))
