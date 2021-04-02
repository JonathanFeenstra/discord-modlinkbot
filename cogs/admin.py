"""
Admin
=====

Extension for providing bot owner/admin-only commands.

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
import re

import discord
from discord.ext import commands


class UserOrGuildIDConverter(commands.MemberConverter):
    """Converts to a `discord.User` or `dicord.Guild` ID."""

    MENTION_RE = re.compile(r"<@!?([0-9]+)>$")

    async def convert(self, ctx: commands.Context, argument: str) -> int:
        """Convert to a `discord.User` or `dicord.Guild` ID."""
        if match := self._get_id_match(argument) or self.MENTION_RE.match(argument):
            return int(match.group(1))
        if guild := ctx.guild:
            if member := guild.get_member_named(argument) or await self.query_member_named(guild, argument):
                return member.id
        raise commands.BadArgument(f"{repr(argument)} could not be converted to a guild or user ID.")


class Admin(commands.Cog):
    """Cog for providing owner/admin-only commands."""

    def __init__(self, bot):
        self.bot = bot

    def cog_check(self, ctx):
        """Checks if context author is a bot owner for all commands in this cog."""
        return ctx.author.id in self.bot.owner_ids

    @commands.command(aliases=["loadextension"])
    async def load(self, ctx, *, extension: str):
        """Load extension.

        Available extensions:
        - admin
        - games
        - general
        - modsearch
        - serverlog
        """
        try:
            self.bot.load_extension(f"cogs.{extension}")
        except commands.ExtensionError as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        else:
            await ctx.send(f":white_check_mark: Successfully loaded '{extension}'.")

    @commands.command(aliases=["unloadextension"])
    async def unload(self, ctx, *, extension: str):
        """Unload extension."""
        if extension == "admin":
            return await ctx.send(":x: Admin extension cannot be unloaded.")
        try:
            self.bot.unload_extension(f"cogs.{extension}")
        except commands.ExtensionError as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        else:
            await ctx.send(f":white_check_mark: Successfully unloaded '{extension}'.")

    @commands.command(aliases=["reloadextension"])
    async def reload(self, ctx, *, extension: str):
        """Reload extension."""
        try:
            self.bot.reload_extension(f"cogs.{extension}")
        except commands.ExtensionError as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        else:
            await ctx.send(f":white_check_mark: Succesfully reloaded '{extension}'.")

    @commands.command(aliases=["stop", "shutdown", "close", "quit", "exit"])
    async def logout(self, ctx):
        """Log out the bot."""
        await ctx.send(":white_check_mark: Shutting down.")
        print(f"{self.bot.user.name} has been logged out by {ctx.author}.")
        await self.bot.close()

    @commands.command(aliases=["username", "rename"])
    async def changeusername(self, ctx, *, username: str):
        """Change the bot's username."""
        try:
            await self.bot.user.edit(username=username)
        except discord.HTTPException as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        else:
            await ctx.send(f":white_check_mark: Username set to {repr(username)}.")

    @commands.command(aliases=["avatar", "pfp"])
    async def changeavatar(self, ctx, *, url: str = None):
        """Change the bot's avatar picture with an image attachment or URL."""
        if url is None:
            if len(ctx.message.attachments) == 1:
                url = ctx.message.attachments[0].url
            else:
                return await ctx.send(":x: No URL specified and no or multiple images attached.")
        else:
            url = url.strip("<>")
        try:
            async with self.bot.session.get(url) as res:
                await self.bot.user.edit(avatar=await res.read())
        except (discord.HTTPException, discord.InvalidArgument) as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        else:
            await ctx.send(":white_check_mark: Avatar changed.")

    @commands.command(aliases=["guildlist", "guilds", "serverlist"])
    @commands.cooldown(rate=1, per=30, type=commands.BucketType.channel)
    async def servers(self, ctx):
        """Send list of servers that bot is a member of."""
        guilds_info = [f"{'Name': <32}Members"]

        for guild in self.bot.guilds:
            name = guild.name if len(guild.name) <= 30 else f"{guild.name[:27]}..."
            guilds_info.append(f"{name: <32}{f'{guild.member_count:,}': <9}")

        description = discord.utils.escape_markdown("\n".join(guilds_info))
        embed = discord.Embed(
            title=":busts_in_silhouette: Servers",
            description=f"```{description if len(description) < 2048 else description[2045] + '...'}```",
            colour=ctx.me.colour.value or self.bot.DEFAULT_COLOUR,
        )
        embed.set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command()
    async def block(self, ctx, *, id_to_block: UserOrGuildIDConverter):
        """Block a guild or user from using the bot."""
        if id_to_block == self.bot.app_owner_id:
            return await ctx.send(":x: App owner cannot be blocked.")
        if guild := self.bot.get_guild(id_to_block):
            await guild.leave()
        await self.bot.block_id(id_to_block)
        await ctx.send(f":white_check_mark: Blocked ID `{id_to_block}`.")

    @commands.command()
    async def unblock(self, ctx, *, blocked_id: UserOrGuildIDConverter):
        """Unblock a guild or user from using the bot."""
        try:
            await self.bot.unblock_id(blocked_id)
        except KeyError:
            await ctx.send(f":x: ID `{blocked_id}` was not blocked.")
        else:
            await ctx.send(f":white_check_mark: ID `{blocked_id}` is no longer blocked.")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Block and leave guild if the bot's app owner is banned."""
        if user.id == getattr(self.bot, "app_owner_id", None):
            await self.bot.block(guild.id)
            await guild.leave()


def setup(bot):
    bot.add_cog(Admin(bot))
