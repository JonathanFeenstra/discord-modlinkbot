"""
Admin
=====

Cog for providing bot owner/admin-only commands.

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

import discord
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
        :return: whether context author is a bot admin
        :rtype: bool
        """
        return await self.bot.is_owner(ctx.author)

    @commands.command()
    async def config(self, ctx, attribute: str, *, value):
        """Set configuration setting to value.

        :param discord.ext.Commands.Context ctx: event context
        :param str attribute: attribute to set
        :param str value: value to set
        """
        try:
            async with SendErrorFeedback(ctx):
                setattr(self.bot.config, attribute.upper(), literal_eval(value))
        except Exception:
            pass
        else:
            await ctx.send(f'Succesfully set `{attribute.upper()}={value}`.')

    @commands.command(aliases=['stop', 'shutdown', 'close', 'quit', 'exit'])
    @delete_msg
    async def logout(self, ctx):
        """Log out the bot.

        :param discord.ext.Commands.Context ctx: event context
        """
        await ctx.send(embed=feedback_embed('Shutting down.'))
        print(f"{self.bot.user.name} has been logged out by {ctx.author}.")
        await self.bot.close()

    @commands.command(aliases=['username'])
    async def changeusername(self, ctx, *, username: str):
        """Change the bot's username.

        :param discord.ext.Commands.Context ctx: event context
        :param str username: username to change to
        """
        try:
            async with SendErrorFeedback(ctx):
                await self.bot.user.edit(username=username)
        except Exception:
            pass
        else:
            await ctx.send(embed=feedback_embed(f'Username set to {repr(username)}.'))

    @commands.command(aliases=['nickname', 'nick'])
    async def changenickname(self, ctx, *, nickname: str = None):
        """Change the bot's nickname in server.

        :param discord.ext.Commands.Context ctx: event context
        :param str nickname: nickname to change to
        """
        try:
            async with SendErrorFeedback(ctx):
                await ctx.guild.me.edit(nick=nickname)
        except Exception:
            pass
        else:
            await ctx.send(embed=feedback_embed(f'Nickname set to {repr(nickname)}.' if nickname else 'Nickname removed'))

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
        try:
            async with SendErrorFeedback(ctx):
                async with self.bot.session.get(url) as res:
                    await self.bot.user.edit(avatar=await res.read())
        except Exception:
            pass
        else:
            await ctx.send(embed=feedback_embed('Avatar changed.'))

    @commands.command(aliases=['guildlist', 'servers', 'serverlist'])
    @commands.cooldown(rate=1, per=30, type=commands.BucketType.channel)
    async def guilds(self, ctx):
        """Send list of guilds that bot is a member of.

        :param discord.ext.Commands.Context ctx: event context
        """
        guilds_info = [f"{'Name': <32}Members  Joined (d/m/y)"]

        for guild in self.bot.guilds[:50]:
            name = guild.name if len(guild.name) <= 30 else f'{guild.name[:27]}...'
            member_count = '{0:,}'.format(guild.member_count).replace(',', ' ')
            join_date = self.bot.guild_configs[guild.id]['joined_at'].strftime('%d/%m/%Y')
            guilds_info.append(f'{name: <32}{member_count: <9}{join_date}')

        description = discord.utils.escape_markdown('\n'.join(guilds_info))
        embed = discord.Embed(title=':busts_in_silhouette: Servers',
                              description=f"```{description if len(description) < 2048 else description[2045] + '...'}```",
                              colour=ctx.guild.me.colour.value or 14323253)
        embed.set_footer(text=f'Prompted by @{ctx.author}', icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)


def setup(bot):
    """Add this cog to bot.

    :param discord.Client bot: bot to add cog to
    """
    bot.add_cog(Admin(bot))
