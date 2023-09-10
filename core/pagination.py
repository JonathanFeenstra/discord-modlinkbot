"""
Pagination
==========

Pagination for modlinkbot using discord-ext-menus.

Copyright (C) 2019-2023 Jonathan Feenstra

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
from typing import Sequence

import discord
from discord.ext import menus

from core.constants import DEFAULT_COLOUR


class ServerPageSource(menus.ListPageSource):
    """Menu pages data source for listing server member counts and names."""

    def __init__(self, data: Sequence[discord.Guild]) -> None:
        super().__init__(data, per_page=30)

    def format_page(self, menu: menus.Menu, page: list[discord.Guild]) -> discord.Embed:
        """Format a page with server member counts and names."""
        guilds_info = ["**`Members  ` Name**"]
        for guild in page:
            name = discord.utils.escape_markdown(guild.name if len(guild.name) <= 48 else f"{guild.name[:45]}...")
            guilds_info.append(f"`{f'{guild.member_count:,}': <9}` {name: <50}")
        ctx = menu.ctx
        return discord.Embed(
            title=":busts_in_silhouette: Servers",
            description="\n".join(guilds_info),
            colour=ctx.me.colour.value or DEFAULT_COLOUR,
        ).set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.display_avatar.url)


class OwnerPageSource(menus.ListPageSource):
    """Menu pages data source for listing bot owners."""

    def __init__(self, data: Sequence[int]) -> None:
        super().__init__(data, per_page=50)

    def format_page(self, menu: menus.Menu, page: list[int]) -> discord.Embed:
        """Format a page with bot owner user mentions."""
        return discord.Embed(
            title=":sunglasses: Bot owners",
            description=", ".join(f"<@{owner_id}>" for owner_id in page),
            colour=menu.ctx.me.colour.value or DEFAULT_COLOUR,
        )


class BlockedPageSource(menus.ListPageSource):
    """Menu pages data source for listing blocked IDs."""

    def __init__(self, data: Sequence[int]) -> None:
        super().__init__(data, per_page=50)

    def format_page(self, menu: menus.Menu, page: list[int]) -> discord.Embed:
        """Format a page with blocked IDs."""
        return discord.Embed(
            title=":stop_sign: Blocked IDs",
            description=", ".join(str(_id) for _id in page) or "No blocked IDs yet.",
            colour=menu.ctx.me.colour.value or DEFAULT_COLOUR,
        )
