"""
Admin
=====

Extension for providing bot owner/admin-only commands.

Copyright (C) 2019-2022 Jonathan Feenstra

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
import os
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands, menus

from bot import ModLinkBot
from core.pagination import ServerPageSource


class Admin(commands.Cog):
    """Cog for providing owner/admin-only commands."""

    def __init__(self, bot: ModLinkBot) -> None:
        self.bot = bot

    def cog_check(self, ctx: commands.Context) -> bool:
        """Check if context author is a bot owner for all commands in this cog."""
        return ctx.author.id in self.bot.owner_ids

    @commands.hybrid_command(aliases=["loadextension"])
    async def load(self, ctx: commands.Context, *, extension: str) -> None:
        """Load an extension.

        Available extensions:
        - admin
        - games
        - general
        - modsearch
        - serverlog
        """
        try:
            await self.bot.load_extension(f"cogs.{extension}")
        except commands.ExtensionError as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`", ephemeral=True)
        else:
            await ctx.send(f":white_check_mark: Successfully loaded '{extension}'.", ephemeral=True)

    @load.autocomplete("extension")
    async def _extensions_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        extensions = sorted(
            os.path.splitext(extension)[0]
            for extension in os.listdir("./cogs")
            if current.lower() in extension and extension != "admin.py"
        )[:25]
        return [app_commands.Choice(name=extension.title(), value=extension) for extension in extensions]

    @commands.hybrid_command(aliases=["unloadextension"])
    async def unload(self, ctx: commands.Context, *, extension: str) -> None:
        """Unload an extension."""
        if extension == "admin":
            await ctx.send(":x: Admin extension cannot be unloaded.")
            return
        try:
            await self.bot.unload_extension(f"cogs.{extension}")
        except commands.ExtensionError as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`", ephemeral=True)
        else:
            await ctx.send(f":white_check_mark: Successfully unloaded '{extension}'.", ephemeral=True)

    @commands.hybrid_command(aliases=["reloadextension"])
    async def reload(self, ctx: commands.Context, *, extension: str) -> None:
        """Reload an extension."""
        try:
            await self.bot.reload_extension(f"cogs.{extension}")
        except commands.ExtensionError as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`", ephemeral=True)
        else:
            await ctx.send(f":white_check_mark: Succesfully reloaded '{extension}'.", ephemeral=True)

    @unload.autocomplete("extension")
    @reload.autocomplete("extension")
    async def _loaded_extensions_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=name, value=name.lower())
            for name in self.bot.cogs.keys()
            if current.lower() in name.lower()
        ][:25]

    @commands.hybrid_command(aliases=["stop", "shutdown", "close", "quit", "exit"])
    async def logout(self, ctx: commands.Context) -> None:
        """Log out the bot."""
        await ctx.send(":white_check_mark: Shutting down.", ephemeral=True)
        print(f"{self.bot.user.name} has been logged out by {ctx.author}.")
        await self.bot.close()

    @commands.hybrid_command(aliases=["username", "rename"])
    async def changeusername(self, ctx: commands.Context, *, username: str) -> None:
        """Change the bot's username."""
        try:
            await self.bot.user.edit(username=username)
        except discord.HTTPException as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`", ephemeral=True)
        else:
            await ctx.send(f":white_check_mark: Username set to {repr(username)}.", ephemeral=True)

    @commands.hybrid_command(aliases=["avatar", "pfp"])
    async def changeavatar(self, ctx: commands.Context, *, url: Optional[str] = None) -> Optional[discord.Message]:
        """Change the bot's avatar picture with an image attachment or URL."""
        if url is None:
            if len(ctx.message.attachments) == 1:
                url = ctx.message.attachments[0].url
            else:
                return await ctx.send(":x: No URL specified and no or multiple images attached.", ephemeral=True)
        else:
            url = url.strip("<>")
        try:
            async with self.bot.session.get(url) as res:
                await self.bot.user.edit(avatar=await res.read())
        except (discord.HTTPException, ValueError) as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`", ephemeral=True)
        else:
            await ctx.send(":white_check_mark: Avatar changed.", ephemeral=True)

    @commands.hybrid_command(aliases=["guildlist", "guilds", "serverlist"])
    @commands.cooldown(rate=1, per=30, type=commands.BucketType.channel)
    async def servers(self, ctx: commands.Context) -> None:
        """Send list of servers that bot is a member of."""
        pages = menus.MenuPages(
            source=ServerPageSource(sorted(self.bot.guilds, key=lambda guild: guild.member_count, reverse=True)),
            clear_reactions_after=True,
        )
        await pages.start(ctx)

    @commands.hybrid_command()
    async def blockuser(self, ctx: commands.Context, *, user: discord.User) -> Optional[discord.Message]:
        """Block a user from using the bot."""
        if user.id == self.bot.app_owner_id:
            return await ctx.send(":x: App owner cannot be blocked.", ephemeral=True)
        if user.id in self.bot.blocked:
            return await ctx.send(":x: User is already blocked.", ephemeral=True)
        await self.bot.block_id(user.id)
        await ctx.send(f":white_check_mark: Blocked `{user}`.", ephemeral=True)

    @commands.hybrid_command(aliases=["blockguild"])
    async def blockserver(self, ctx: commands.Context, *, server: discord.Guild) -> Optional[discord.Message]:
        """Block a server from using the bot."""
        if server.id in self.bot.blocked:
            return await ctx.send(":x: Server is already blocked.", ephemeral=True)
        try:
            await server.leave()
        except discord.HTTPException:
            pass
        await self.bot.block_id(server.id)
        await ctx.send(f":white_check_mark: Blocked `{server}`.")

    @commands.hybrid_command()
    async def unblock(self, ctx: commands.Context, *, blocked_id: int) -> None:
        """Unblock a guild or user from using the bot."""
        try:
            await self.bot.unblock_id(blocked_id)
        except KeyError:
            await ctx.send(f":x: ID `{blocked_id}` was not blocked.", ephemeral=True)
        else:
            await ctx.send(f":white_check_mark: ID `{blocked_id}` is no longer blocked.", ephemeral=True)

    @commands.hybrid_command()
    async def sync(self, ctx: commands.Context) -> None:
        """Sync the application commands to Discord (owner only)."""
        commands = await self.bot.tree.sync()
        await ctx.send(f":white_check_mark: **Synced {len(commands)} commands.**", ephemeral=True)


async def setup(bot: ModLinkBot) -> None:
    await bot.add_cog(Admin(bot))
