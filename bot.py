"""
discord-modlinkbot
==================

A Discord bot for linking Nexus Mods search results.

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
import asyncio
import importlib
import logging
import traceback
from datetime import timedelta
from sys import stderr
from types import ModuleType
from typing import Iterable, List

import discord
from aiohttp_client_cache import CachedSession, SQLiteBackend
from discord.ext import commands

import config
from core.aionxm import RequestHandler
from core.constants import GITHUB_URL
from core.help import ModLinkBotHelpCommand
from core.persistence import ModLinkBotConnection, connect

__version__ = "0.3a1"


class ModLinkBot(commands.Bot):
    """Discord Bot for linking Nexus Mods search results."""

    session: CachedSession
    request_handler: RequestHandler

    def __init__(self) -> None:
        # Placeholder until startup is complete
        self.app_owner_id = 0
        super().__init__(
            command_prefix=self.get_prefix,
            help_command=ModLinkBotHelpCommand(__version__),
            status=discord.Status.idle,
            intents=discord.Intents(
                guilds=True, members=True, message_content=True, guild_messages=True, guild_reactions=True
            ),
        )
        self.blocked = set()

    async def setup_hook(self) -> None:
        """Called after the bot is logged in, but before connecting to the websocket."""
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
        """Perform startup tasks: prepare storage and configurations."""
        self._initialise_request_handler()

        async with self.db_connect() as con:
            await self._prepare_storage(con)
            await self.wait_until_ready()

            await self._load_extensions("admin", "games", "general", "modsearch")
            if getattr(self.config, "server_log_webhook_url", False):
                await self._load_extensions("serverlog")

            await self._update_guilds(con)

        self.oauth_url = discord.utils.oauth_url(
            self.user.id,  # type: ignore - user should not be None after startup
            permissions=discord.Permissions(
                view_audit_log=True,
                create_instant_invite=True,
                read_messages=True,
                send_messages=True,
                embed_links=True,
                add_reactions=True,
            ),
        )
        print(f"{self.user.name} is ready.")  # type: ignore

    def _initialise_request_handler(self) -> None:
        cache = SQLiteBackend(
            cache_name="data/modlinkbot-cache.db",
            urls_expire_after={
                "nexusmods.com": timedelta(days=3),
                "data.nexusmods.com": timedelta(days=2),
                "search.nexusmods.com": timedelta(hours=12),
            },
            cache_control=False,
        )
        self.session = CachedSession(cache=cache, loop=self.loop)
        self.request_handler = RequestHandler(
            self.session,
            app_data={
                "name": "discord-modlinkbot",
                "version": __version__,
                "url": GITHUB_URL,
            },
        )

    async def _prepare_storage(self, con: ModLinkBotConnection) -> None:
        await con.executefile("data/modlinkbot.db.sql")
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
        for guild in self.guilds:
            if not self.validate_guild(guild):
                await guild.leave()
            elif guild.id not in old_guild_ids:
                await con.insert_guild(guild.id)
                if serverlog_cog := self.get_cog("ServerLog"):
                    await serverlog_cog.on_guild_join(guild)  # type: ignore - ServerLog.on_guild_join is a known method

    async def _load_extensions(self, *extensions: str) -> None:
        for extension in extensions:
            try:
                await self.load_extension(f"cogs.{extension}")
            except commands.ExtensionError as error:
                print(f"Failed to load extension {extension}: {error}", file=stderr)
                traceback.print_exc()

    async def _update_presence(self) -> None:
        guild_count = len(self.guilds)
        await self.change_presence(
            activity=discord.Activity(
                name=f"{guild_count} server{'s' if guild_count != 1 else ''} | .help",
                type=discord.ActivityType.watching,
            )
        )

    def db_connect(self) -> ModLinkBotConnection:
        """Connect to the database."""
        return connect("data/modlinkbot.db")

    def validate_guild(self, guild: discord.Guild) -> bool:
        """Check if guild and its owner are not blocked and the guild limit not exceeded."""
        return (
            guild.id not in self.blocked
            and guild.owner_id not in self.blocked
            and (not (max_guilds := getattr(self.config, "max_servers", False)) or len(self.guilds) <= max_guilds)
        )

    def validate_msg(self, msg: discord.Message) -> bool:
        """Check if message is valid to be processed (in a server and author not blocked)."""
        return msg.author.id not in self.blocked and isinstance(msg.guild, discord.Guild)

    async def get_prefix(self, msg: discord.Message) -> List[str]:
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
        """Process valid new messages if the bot has permission to send messages."""
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
                print(f"In {ctx.command.qualified_name}:", file=stderr)  # type: ignore - command is not None
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
        uvloop.install()  # type: ignore - install is a known function in uvloop


def setup_logging() -> None:
    """Setup discord.py's logger (https://discordpy.readthedocs.io/en/latest/logging.html)."""
    logger = logging.getLogger("discord")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(filename="data/modlinkbot.log", encoding="utf-8", mode="w")
    handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
    logger.addHandler(handler)


bot = ModLinkBot()


async def main() -> None:
    print("Starting...")
    install_uvloop_if_found()
    setup_logging()
    async with bot:
        await bot.start(config.token)


if __name__ == "__main__":
    asyncio.run(main())
