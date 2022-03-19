"""
Help
====

Help command for modlinkbot.

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
from itertools import groupby
from typing import Mapping, Optional

import discord
from discord.ext import commands

from core.constants import DEFAULT_COLOUR, GITHUB_URL


class ModLinkBotHelpCommand(commands.DefaultHelpCommand):
    """Help command for modlinkbot."""

    def __init__(self, version: str) -> None:
        super().__init__()
        self.version = version
        self.description = (
            "Configure a server or channel to retrieve search results from [Nexus Mods](https://www.nexusmods.com/) for "
            "search queries in messages {between braces, separated by commas}, 3 to 100 characters in length, outside of "
            "any [Discord markdown](https://support.discord.com/hc/en-us/articles/210298617) or ||[spoiler tags]"
            "(https://support.discord.com/hc/en-us/articles/360022320632)||. Queries cannot contain any of the following "
            'characters: ``\\";:=*%$&_<>?`[]{}``.'
        )

    async def send_bot_help(self, mapping: Mapping[Optional[commands.Cog], list[commands.Command]]) -> None:
        """Send help embed for when no help arguments are specified."""
        ctx = self.context
        bot = ctx.bot
        prefix = (await bot.get_prefix(ctx.message))[-1]

        embed = discord.Embed(
            title=f"modlinkbot v{self.version} | Help",
            description=self._format_description(prefix),
            colour=ctx.me.colour.value or DEFAULT_COLOUR,
        )
        embed.add_field(
            name="Links",
            value=(
                "[Discord Bot List](https://top.gg/bot/665861255051083806)"
                f" | [GitHub]({GITHUB_URL})"
                f" | [Add to your server]({bot.oauth_url})"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.avatar.url)

        await ctx.send(embed=embed)
        await self._send_commands_info(prefix)

    def _format_description(self, prefix: str) -> str:
        description = [self.description]

        if self.context.bot.get_cog("Games"):
            description.append(f"Use `{prefix}help addgame` for info about configuring games to search Nexus Mods for. ")
        else:
            description.append(
                "**Important:** Load the Games extension to enable search configuration settings using "
                f"`{prefix}load games` (can only be done by bot owners)."
            )
        if not self.context.bot.get_cog("ModSearch"):
            description.append(
                f"**Important:** Load the ModSearch extension to enable Nexus Mods search using `{prefix}load modsearch` "
                "(can only be done by bot owners)."
            )

        return "\n\n".join(description)

    async def _send_commands_info(self, prefix: str) -> None:
        self.paginator.add_line(f"Commands (prefix = {repr(prefix)})", empty=True)

        def get_category(command: commands.Command) -> str:
            """Get command category (cog)."""
            return f"{command.cog.qualified_name}:" if command.cog is not None else "Help:"

        max_size = self.get_max_size(
            filtered := await self.filter_commands(self.context.bot.commands, sort=True, key=get_category)
        )

        for category, cmds in groupby(filtered, key=get_category):
            self.add_indented_commands(sorted(cmds, key=lambda c: c.name), heading=category, max_size=max_size)

        self.paginator.add_line()
        self.paginator.add_line(
            f"Type {prefix}help command for more info on a command.\n"
            f"Type {prefix}help category for more info on a category."
        )
        await self.send_pages()
