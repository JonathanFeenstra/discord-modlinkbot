"""
ServerLog
=========

Extension for logging the addition and removal of modlinkbot to servers.

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
import traceback
from sys import stderr

import discord

from discord.ext import commands


async def get_guild_invite(guild):
    """Get invite link to guild if possible."""
    if guild.me.guild_permissions.manage_guild:
        invites = await guild.invites()
        for invite in invites:
            if not (invite.max_age or invite.temporary):
                return invite.url
    if not (guild.channels and guild.me.guild_permissions.create_instant_invite):
        return ""
    channel = guild.system_channel or guild.rules_channel or guild.public_updates_channel
    if channel and channel.permissions_for(guild.me).create_instant_invite:
        try:
            return (await channel.create_invite(unique=False)).url
        except (discord.HTTPException, discord.NotFound):
            pass
    for channel in guild.channels:
        if channel.permissions_for(guild.me).create_instant_invite:
            try:
                return (await channel.create_invite(unique=False)).url
            except (discord.HTTPException, discord.NotFound):
                continue
    return ""


def _prepare_serverlog_embed(guild):
    embed = discord.Embed()
    embed.set_thumbnail(url=guild.banner_url)
    embed.timestamp = guild.created_at

    if description := guild.description:
        embed.add_field(name="Description", value=description, inline=False)

    embed.add_field(name="Member count", value=str(guild.member_count))

    if log_author := guild.owner:
        embed.set_footer(text=f"Owner: @{log_author} ({log_author.id}) | Created at", icon_url=log_author.avatar_url)

    return embed


def _format_guild_string(guild):
    return f"**{discord.utils.escape_markdown(guild.name)}** ({guild.id})"


class ServerLog(commands.Cog):
    """Cog for logging the addition and removal of modlinkbot to servers."""

    def __init__(self, bot):
        self.bot = bot
        self.webhook_adapter = discord.AsyncWebhookAdapter(self.bot.session)

    @property
    def webhook(self):
        """Server log webhook."""
        return discord.Webhook.partial(*self.webhook_url.split("/")[-2:], adapter=self.webhook_adapter)

    @property
    def webhook_url(self):
        """Configured server log webhook URL."""
        return getattr(self.bot.config, "server_log_webhook_url", False)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Log bot addition when joining a valid guild."""
        if not self.bot.validate_guild(guild):
            return
        if self.webhook_url:
            log_entry = await self._get_bot_addition_log_entry_if_found(guild)
            await self.log_guild_addition(guild, log_entry)
        else:
            self.bot.unload_extension("cogs.serverlog")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Log bot removal when leaving a valid guild."""
        if not self.bot.validate_guild(guild):
            return
        if self.webhook_url:
            await self.log_guild_removal(guild)
        else:
            self.bot.unload_extension("cogs.serverlog")

    async def _get_bot_addition_log_entry_if_found(self, guild, max_logs_to_check=50):
        if guild.me.guild_permissions.view_audit_log:
            async for log_entry in guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=max_logs_to_check):
                if log_entry.target == guild.me:
                    if log_entry.user.id in self.bot.blocked:
                        return await guild.leave()
                    return log_entry

    async def log_guild_addition(self, guild, log_entry=None):
        """Send webhook log message when guild joins."""
        embed = _prepare_serverlog_embed(guild)
        embed.colour = guild.me.colour.value or 14323253

        guild_string = _format_guild_string(guild)
        bot_mention = guild.me.mention
        log_author = guild.owner or guild.me

        if bot_inviter := getattr(log_entry, "user", False):
            embed.description = f":inbox_tray: **@{bot_inviter}** has added {bot_mention} to {guild_string}."
            log_author = bot_inviter
        else:
            embed.description = f":inbox_tray: {bot_mention} has been added to {guild_string}."

        if invite := await get_guild_invite(guild):
            embed.set_author(name=guild.name, url=invite, icon_url=guild.icon_url)
            embed.add_field(name="Invite link", value=invite, inline=False)
        else:
            embed.set_author(name=guild.name, icon_url=guild.icon_url)

        await self.send_serverlog(embed, log_author)

    async def log_guild_removal(self, guild):
        """Send webhook log message when guild leaves."""
        embed = _prepare_serverlog_embed(guild)
        embed.description = f":outbox_tray: {guild.me.mention} has been removed from {_format_guild_string(guild)}."
        embed.colour = 14323253
        embed.set_author(name=guild.name, icon_url=guild.icon_url)
        await self.send_serverlog(embed, guild.owner or guild.me)

    async def send_serverlog(self, embed, log_author):
        """Send server log message to the configured webhook."""
        try:
            await self.webhook.send(
                embed=embed,
                username=f"{log_author} ({log_author.id})",
                avatar_url=log_author.avatar_url,
            )
        except (discord.HTTPException, discord.NotFound, discord.Forbidden) as error:
            print(f"{error.__class__.__name__}: {error}", file=stderr)
            traceback.print_tb(error.__traceback__)


def setup(bot):
    bot.add_cog(ServerLog(bot))