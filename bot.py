"""
discord-modlinkbot
==================

A Discord bot for linking Nexus Mods search results.

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
import importlib
import logging
import traceback
from itertools import groupby
from sys import stderr
from types import ModuleType
from typing import Iterable, Mapping, Optional

import discord
from aiohttp import ClientSession
from discord.ext import commands

import config
from aionxm import RequestHandler
from storage import ModLinkBotConnection, connect

__version__ = "0.2a6"


GITHUB_URL = "https://github.com/JonathanFeenstra/discord-modlinkbot"


class ModLinkBotHelpCommand(commands.DefaultHelpCommand):
    """Help command for modlinkbot."""

    def __init__(self) -> None:
        super().__init__()
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
            title=f"{bot.user.name} | Help",
            description=self._format_description(prefix),
            colour=ctx.me.colour.value or bot.DEFAULT_COLOUR,
        )
        embed.add_field(
            name="Links",
            value=(
                f"[Discord Bot List](https://top.gg/bot/665861255051083806) | [GitHub]({GITHUB_URL}) | [Add to your server]"
                f"({bot.oauth_url})"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.avatar_url)

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


class ModLinkBot(commands.Bot):
    """Discord Bot for linking Nexus Mods search results"""

    DEFAULT_COLOUR = 0xDA8E35

    def __init__(self) -> None:
        # Placeholder until startup is complete
        self.app_owner_id = 0

        super().__init__(
            command_prefix=self.get_prefix,
            help_command=ModLinkBotHelpCommand(),
            status=discord.Status.idle,
            intents=discord.Intents(guilds=True, members=True, bans=True, guild_messages=True, guild_reactions=True),
        )

        self.blocked = set()
        self.loop.create_task(self.startup())

    @property
    def config(self) -> ModuleType:
        """Bot configuration module."""
        return importlib.reload(config)

    @property
    def owner_ids(self) -> set[int]:
        """Bot owner IDs."""
        return getattr(self.config, "owner_ids", set()) | {self.app_owner_id}

    @owner_ids.setter
    def owner_ids(self, value: set) -> None:
        """Owner IDs setter, to ignore new value set in constructor of the superclass."""

    async def startup(self) -> None:
        """Perform startup tasks: prepare sorage and configurations."""
        self.session = ClientSession(loop=self.loop)
        app_data = {"name": "discord-modlinkbot", "version": __version__, "url": GITHUB_URL}
        self.request_handler = RequestHandler(self.session, app_data)

        if getattr(self.config, "server_log_webhook_url", False):
            # Load before `_update_guilds()` to log servers added while offline
            self._load_extensions("serverlog")

        async with self.db_connect() as con:
            await self._prepare_storage(con)
            await self.wait_until_ready()
            await self._update_guilds(con)

        self.oauth_url = discord.utils.oauth_url(
            self.user.id,
            permissions=discord.Permissions(
                view_audit_log=True,
                create_instant_invite=True,
                read_messages=True,
                send_messages=True,
                embed_links=True,
                add_reactions=True,
            ),
        )
        self._load_extensions("admin", "games", "general", "modsearch")
        print(f"{self.user.name} is ready.")

    async def _prepare_storage(self, con: ModLinkBotConnection) -> None:
        await con.executefile("modlinkbot_db.ddl")
        await con.commit()

        self.blocked.update(await con.fetch_blocked_ids())
        self.app_owner_id = (await self.application_info()).owner.id
        self.owner_ids.add(self.app_owner_id)

    async def _update_guilds(self, con: ModLinkBotConnection) -> None:
        await con.enable_foreign_keys()
        await con.filter_guilds(tuple(guild.id for guild in self.guilds))
        await con.commit()
        old_guild_ids = await con.fetch_guild_ids()
        await self._purge_deleted_channels(con)
        await self._insert_valid_new_guilds(con, old_guild_ids)
        await con.commit()

    async def _purge_deleted_channels(self, con: ModLinkBotConnection) -> None:
        for channel_id, guild_id in await con.fetch_channels():
            if not (guild := self.get_guild(guild_id)):
                await con.delete_guild(guild_id)
            elif not guild.get_channel(channel_id):
                await con.delete_channel(channel_id)

    async def _insert_valid_new_guilds(self, con: ModLinkBotConnection, old_guild_ids: Iterable[int]) -> None:
        serverlog_cog = self.get_cog("ServerLog")
        for guild in self.guilds:
            if not self.validate_guild(guild):
                await guild.leave()
            elif guild.id not in old_guild_ids:
                await con.insert_guild(guild.id)
                if serverlog_cog:
                    await serverlog_cog.on_guild_join(guild)

    def _load_extensions(self, *extensions: str) -> None:
        for extension in extensions:
            try:
                self.load_extension(f"cogs.{extension}")
            except commands.ExtensionError as error:
                print(f"Failed to load extension {extension}: {error}", file=stderr)
                traceback.print_exc()

    async def _update_presence(self) -> None:
        await self.change_presence(
            activity=discord.Activity(
                name=f"{'1 server' if (guild_count := len(self.guilds)) == 1 else f'{guild_count} servers'} | .help",
                type=discord.ActivityType.watching,
            )
        )

    def db_connect(self) -> ModLinkBotConnection:
        """Connect to the database."""
        return connect(getattr(self.config, "database_path", "modlinkbot.db"))

    def validate_guild(self, guild: discord.Guild) -> bool:
        """Check if guild and its owner are not blocked and the guild limit not exceeded."""
        return (
            guild.id not in self.blocked
            and guild.owner_id not in self.blocked
            and (not (max_guilds := getattr(self.config, "max_servers", False)) or len(self.guilds) <= max_guilds)
        )

    def validate_msg(self, msg: discord.Message) -> bool:
        """Check if message is valid to be processed."""
        return not msg.author.bot and msg.author.id not in self.blocked and isinstance(msg.guild, discord.Guild)

    async def get_prefix(self, msg: discord.Message) -> list[str]:
        """Check `msg` for valid command prefixes."""
        if msg.guild:
            async with self.db_connect() as con:
                return commands.when_mentioned_or(await con.fetch_guild_prefix(msg.guild.id) or ".")(self, msg)
        return commands.when_mentioned_or(".")(self, msg)

    async def is_owner(self, user: discord.User) -> bool:
        """Check if `user` is a bot owner."""
        return user.id in self.owner_ids

    async def block_id(self, id_to_block: int) -> None:
        """Block a guild or user by ID."""
        self.blocked.add(id_to_block)
        async with self.db_connect() as con:
            await con.insert_blocked_id(id_to_block)
            await con.commit()

    async def unblock_id(self, id_to_unblock: int) -> None:
        """Unblock a guild or user by ID."""
        self.blocked.remove(id_to_unblock)
        async with self.db_connect() as con:
            await con.delete_blocked_id(id_to_unblock)
            await con.commit()

    async def on_ready(self) -> None:
        """Update bot presence when ready."""
        await self._update_presence()

    async def on_message(self, msg: discord.Message) -> None:
        """Process new messages that are not from bots or DMs."""
        if not self.validate_msg(msg) or not msg.channel.permissions_for(msg.guild.me).send_messages:
            return
        await self.process_commands(msg)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Set default guild configuration when joining a guild."""
        if not self.validate_guild(guild):
            return await guild.leave()
        async with self.db_connect() as con:
            await con.insert_guild(guild.id)
            await con.commit()
        await self._update_presence()

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Remove guild configuration when leaving a guild."""
        if not self.validate_guild(guild):
            return
        async with self.db_connect() as con:
            await con.enable_foreign_keys()
            await con.delete_guild(guild.id)
            await con.commit()
        await self._update_presence()

    async def on_guild_channel_delete(self, channel: discord.ChannelType) -> None:
        """Delete channel from database on deletion."""
        if not isinstance(channel, discord.TextChannel):
            return
        async with self.db_connect() as con:
            await con.enable_foreign_keys()
            await con.delete_channel(channel.id)
            await con.commit()

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """Handle command exceptions."""
        if isinstance(error, commands.CommandNotFound) or hasattr(ctx.command, "on_error"):
            return

        error = getattr(error, "original", error)

        if isinstance(error, (commands.UserInputError, commands.CheckFailure)):
            await ctx.send(f":x: {error}")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f":x: {ctx.author.mention} Command on cooldown. Try again after {round(error.retry_after, 1)} s.")
        else:
            if isinstance(error, discord.HTTPException):
                print(f"In {ctx.command.qualified_name}:", file=stderr)
            print(f"{error.__class__.__name__}: {error}", file=stderr)
            traceback.print_tb(error.__traceback__)

    async def close(self) -> None:
        """Close the bot."""
        await self.session.close()
        await super().close()


def install_uvloop_if_found() -> None:
    """Set event loop policy from https://github.com/MagicStack/uvloop if found."""
    try:
        uvloop = importlib.import_module("uvloop")
    except ModuleNotFoundError:
        pass
    else:
        uvloop.install()


def setup_logging() -> None:
    """Setup discord.py's logger (https://discordpy.readthedocs.io/en/latest/logging.html)."""
    logger = logging.getLogger("discord")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(filename=getattr(config, "log_path", "modlinkbot.log"), encoding="utf-8", mode="w")
    handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
    logger.addHandler(handler)


def main() -> None:
    print("Starting...")
    install_uvloop_if_found()
    setup_logging()
    modlinkbot = ModLinkBot()
    modlinkbot.run(config.token)


if __name__ == "__main__":
    main()
