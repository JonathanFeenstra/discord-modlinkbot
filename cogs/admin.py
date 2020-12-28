"""
Admin
=====

Cog for providing bot owner/admin-only commands.

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
from ast import literal_eval

import discord
from discord.ext import commands

from .util import delete_msg


class Admin(commands.Cog):
    """Cog for providing owner/admin-only commands."""

    def __init__(self, bot):
        """Initialise cog."""
        self.bot = bot

    async def cog_check(self, ctx):
        """Checks if context author is a bot admin for every command in this cog."""
        return await self.bot.is_owner(ctx.author)

    @commands.command()
    async def config(self, ctx, setting: str, *, value):
        """Set configuration setting to value."""
        try:
            setattr(self.bot.config, setting := setting.lower(), literal_eval(value))
        except Exception as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        else:
            await ctx.send(f"Succesfully set `{setting} = {value}`.")

    @commands.command(aliases=["stop", "shutdown", "close", "quit", "exit"])
    @delete_msg
    async def logout(self, ctx):
        """Log out the bot."""
        await ctx.send(":white_check_mark: Shutting down.")
        print(f"{self.bot.user.name} has been logged out by {ctx.author}.")
        await self.bot.close()

    @commands.command(aliases=["username"])
    async def changeusername(self, ctx, *, username: str):
        """Change the bot's username."""
        try:
            await self.bot.user.edit(username=username)
        except discord.HTTPException as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        else:
            await ctx.send(f":white_check_mark: Username set to {repr(username)}.")

    @commands.command(aliases=["avatar"])
    async def changeavatar(self, ctx, *, url: str = None):
        """Change the bot's avatar picture with an image attachment or URL."""
        if url is None and len(ctx.message.attachments) == 1:
            url = ctx.message.attachments[0].url
        else:
            url = url.strip("<>")
        try:
            async with self.bot.session.get(url) as res:
                await self.bot.user.edit(avatar=await res.read())
        except (discord.HTTPException, discord.InvalidArgument) as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        else:
            await ctx.send(":white_check_mark: Avatar changed.")

    @commands.command(aliases=["guildlist", "servers", "serverlist"])
    @commands.cooldown(rate=1, per=30, type=commands.BucketType.channel)
    async def guilds(self, ctx):
        """Send list of guilds that bot is a member of."""
        guilds_info = [f"{'Name': <32}Members  Joined (d/m/y)"]

        for guild in self.bot.guilds[:50]:
            name = guild.name if len(guild.name) <= 30 else f"{guild.name[:27]}..."
            join_date = self.bot.guild_configs[guild.id]["joined_at"].strftime("%d/%m/%Y")
            guilds_info.append(f"{name: <32}{f'{guild.member_count:,}': <9}{join_date}")

        description = discord.utils.escape_markdown("\n".join(guilds_info))
        embed = discord.Embed(
            title=":busts_in_silhouette: Servers",
            description=f"```{description if len(description) < 2048 else description[2045] + '...'}```",
            colour=ctx.guild.me.colour.value or 14323253,
        )
        embed.set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)


def setup(bot):
    """Add this cog to bot."""
    bot.add_cog(Admin(bot))
