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
from typing import Optional, Union

import discord
from aiohttp import ClientSession
from discord.ext import commands

from bot import ModLinkBot
from core.constants import DEFAULT_AVATAR_URL, DEFAULT_COLOUR


async def get_guild_invite_url(guild: discord.Guild) -> Optional[str]:
    """Get invite link to guild if possible."""
    if guild.me.guild_permissions.manage_guild and (invite_url := await _get_existing_invite_url(guild)):
        return invite_url
    if not (guild.channels and guild.me.guild_permissions.create_instant_invite):
        return None
    channel = guild.system_channel or guild.rules_channel or guild.public_updates_channel
    if channel and (invite_url := await _get_channel_invite_url(channel)):
        return invite_url
    for channel in guild.channels:
        if invite_url := await _get_channel_invite_url(channel):
            return invite_url
    return None


async def _get_existing_invite_url(guild: discord.Guild) -> Optional[str]:
    try:
        invites = await guild.invites()
        for invite in invites:
            if not (invite.max_age or invite.temporary):
                return invite.url
    except (discord.HTTPException, discord.Forbidden):
        return None


async def _get_channel_invite_url(channel: discord.abc.GuildChannel) -> Optional[str]:
    if channel.permissions_for(channel.guild.me).create_instant_invite:
        try:
            return (await channel.create_invite(unique=False, reason="modlinkbot server log")).url
        except (discord.HTTPException, discord.NotFound):
            pass
    return None


def _prepare_serverlog_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed()
    embed.set_thumbnail(url=getattr(guild.banner, "url", discord.Embed.Empty))
    embed.timestamp = guild.created_at

    if description := guild.description:
        embed.add_field(name="Description", value=description, inline=False)

    embed.add_field(name="ID", value=guild.id)
    embed.add_field(name="Member count", value=str(guild.member_count))

    if log_author := guild.owner:
        embed.set_footer(
            text=f"Owner: @{log_author} (ID: {log_author.id}) | Created at",
            icon_url=getattr(log_author.avatar, "url", DEFAULT_AVATAR_URL),
        )

    return embed


def _format_guild_string(guild: discord.Guild) -> str:
    return f"**{discord.utils.escape_markdown(guild.name)}**"


class ServerLog(commands.Cog):
    """Cog for logging the addition and removal of modlinkbot to servers."""

    session: ClientSession

    def __init__(self, bot: ModLinkBot) -> None:
        self.bot = bot
        # `self.bot.session` is a `CachedSession`, which does not work well with webhooks.
        self.bot.loop.create_task(self._create_client_session())

    async def _create_client_session(self) -> None:
        self.session = ClientSession(loop=self.bot.loop)

    @property
    def webhook(self) -> Optional[discord.Webhook]:
        """Server log webhook."""
        if webhook_url := getattr(self.bot.config, "server_log_webhook_url", None):
            return discord.Webhook.from_url(webhook_url, session=self.session)
        return None

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Log bot addition when joining a valid guild."""
        if not self.bot.validate_guild(guild):
            return
        if self.webhook is not None:
            log_entry = await self._get_bot_addition_log_entry_if_found(guild)
            await self.log_guild_addition(guild, log_entry)
        else:
            self._unload()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Log bot removal when leaving a valid guild."""
        if not self.bot.validate_guild(guild):
            return
        if self.webhook is not None:
            await self.log_guild_removal(guild)
        else:
            self._unload()

    def cog_unload(self) -> None:
        """Close client session when unloading the cog."""
        self.bot.loop.create_task(self.session.close())

    def _unload(self) -> None:
        self.bot.unload_extension("cogs.serverlog")

    async def _get_bot_addition_log_entry_if_found(
        self, guild: discord.Guild, max_logs_to_check=50
    ) -> Optional[discord.AuditLogEntry]:
        if guild.me.guild_permissions.view_audit_log:
            async for log_entry in guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=max_logs_to_check):
                if log_entry.target == guild.me:
                    if log_entry.user.id in self.bot.blocked:
                        return await guild.leave()
                    return log_entry

    async def log_guild_addition(self, guild: discord.Guild, log_entry: Optional[discord.AuditLogEntry] = None) -> None:
        """Send webhook log message when guild joins."""
        embed = _prepare_serverlog_embed(guild)
        embed.colour = guild.me.colour.value or DEFAULT_COLOUR

        guild_string = _format_guild_string(guild)
        bot_mention = guild.me.mention
        log_author = guild.owner or guild.me

        if bot_inviter := getattr(log_entry, "user", False):
            embed.description = f":inbox_tray: **@{bot_inviter}** has added {bot_mention} to {guild_string}."
            log_author = bot_inviter
        else:
            embed.description = f":inbox_tray: {bot_mention} has been added to {guild_string}."

        guild_icon_url = getattr(guild.icon, "url", None)
        if invite := await get_guild_invite_url(guild):
            embed.set_author(name=guild.name, url=invite, icon_url=guild_icon_url)
            embed.add_field(name="Invite link", value=invite, inline=False)
        else:
            embed.set_author(name=guild.name, icon_url=guild_icon_url)

        await self.send_serverlog(embed, log_author)

    async def log_guild_removal(self, guild: discord.Guild) -> None:
        """Send webhook log message when guild leaves."""
        embed = _prepare_serverlog_embed(guild)
        embed.description = f":outbox_tray: {self.bot.user.mention} has been removed from {_format_guild_string(guild)}."
        embed.colour = DEFAULT_COLOUR
        embed.set_author(name=guild.name, icon_url=getattr(guild.icon, "url", None))
        await self.send_serverlog(embed, guild.owner or self.bot.user)

    async def send_serverlog(
        self, embed: discord.Embed, log_author: Union[discord.ClientUser, discord.User, discord.Member]
    ) -> None:
        """Send server log message to the configured webhook."""
        if (webhook := self.webhook) is None:
            self._unload()
        else:
            try:
                await webhook.send(
                    embed=embed,
                    username=f"{log_author} (ID: {log_author.id})",
                    avatar_url=getattr(log_author.avatar, "url", DEFAULT_AVATAR_URL),
                )
            except (discord.HTTPException, discord.NotFound, discord.Forbidden) as error:
                print(f"{error.__class__.__name__}: {error}", file=stderr)
                traceback.print_tb(error.__traceback__)


def setup(bot: ModLinkBot) -> None:
    bot.add_cog(ServerLog(bot))
