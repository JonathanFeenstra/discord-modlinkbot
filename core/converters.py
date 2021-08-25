"""
Converters
==========

Custom Discord converters for modlinkbot.

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
from typing import Optional

import discord
from discord.ext import commands


async def get_member(guild: discord.Guild, username: str, discriminator: str) -> discord.Member:
    """Get guild member with the specified username and discriminator if found."""
    return discord.utils.get(guild.members, name=username, discriminator=discriminator) or discord.utils.get(
        await _query_members_using_websocket(guild, username), name=username, discriminator=discriminator
    )


async def get_member_named(guild: discord.Guild, name: str) -> discord.Member:
    """Get guild member with the specified name if found."""
    if name.startswith("@"):
        return discord.utils.find(lambda m: name[1:] in (m.name, m.nick) or name == m.nick, guild.members)
    return _find_member(name, guild.members) or _find_member(name, await _query_members_using_websocket(guild, name))


async def _query_members_using_websocket(guild: discord.Guild, name: str) -> list[discord.Member]:
    return await guild._state.query_members(
        guild, query=name, limit=100, user_ids=None, presences=False, cache=guild._state.member_cache_flags.joined
    )


def _find_member(name: str, members: list[discord.Member]) -> Optional[discord.Member]:
    return discord.utils.find(lambda m: name in (m.name, m.nick), members)


class UserOrGuildIDConverter(commands.IDConverter):
    """Converts to a `discord.User` or `dicord.Guild` ID."""

    MENTION_RE = re.compile(r"<@!?([0-9]{15,20})>$")
    DISCRIMINATOR_RE = re.compile(r"#([0-9]{4})$")

    async def convert(self, ctx: commands.Context, argument: str) -> int:
        """Convert to a `discord.User` or `dicord.Guild` ID."""
        if match := self._get_id_match(argument) or self.MENTION_RE.match(argument):
            return int(match.group(1))
        if user := await self.get_user_named(ctx, argument):
            return user.id
        raise commands.BadArgument(f"{repr(argument)} could not be converted to a guild or user ID.")

    async def get_user_named(self, ctx: commands.Context, name: str) -> discord.User:
        """Get user with the specified name if found."""
        try:
            username, discriminator = self.split_name(name)
        except ValueError:
            pass
        else:
            if result := discord.utils.find(lambda m: m.nick == name, ctx.guild.members) or await get_member(
                ctx.guild, username, discriminator
            ):
                return result
            users = ctx._state._users.values()
            return discord.utils.find(
                lambda u: u.name == username and u.discriminator == discriminator, users
            ) or discord.utils.find(lambda u: u.name == username, users)
        return await get_member_named(ctx.guild, name)

    def split_name(self, name: str) -> tuple[str, str]:
        """Split name into username and discriminator."""
        if len(name) > 5 and (match := self.DISCRIMINATOR_RE.match(name[-5:])):
            username = name[1:-5] if name.startswith("@") else name[:-5]
            discriminator = match.group(1)
            return username, discriminator
        raise ValueError("Invalid name.")
