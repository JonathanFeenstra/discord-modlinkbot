"""
discord-modlinkbot
==================

A Discord bot for linking Nexus Mods search results.

Copyright (C) 2019-2021 Jonathan Feenstra

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
import re
import traceback
from datetime import datetime
from functools import partial
from itertools import groupby
from sqlite3 import PARSE_COLNAMES, PARSE_DECLTYPES
from sys import stderr

import discord
from aiohttp import ClientSession
from aiosqlite import connect
from discord.ext import commands

import config

__version__ = "0.1a1"


async def get_prefix(bot, msg):
    """Check `msg` for valid command prefixes."""
    if msg.guild:
        async with bot.db_connect() as con:
            async with con.execute("SELECT prefix FROM guild WHERE guild_id = ?", (msg.guild.id,)) as cur:
                return commands.when_mentioned_or(*(await cur.fetchone()) or ".")(bot, msg)
    return commands.when_mentioned_or(".")(bot, msg)


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


class ModLinkBotHelpCommand(commands.DefaultHelpCommand):
    """Help command for modlinkbot."""

    def __init__(self):
        """Initialise help command."""
        super().__init__()
        self.description = (
            "Configure a server or channel to retrieve search results from [Nexus Mods](https://www.nexusmods.com/) for "
            "search queries in messages {between braces, separated by commas}, 3 to 100 characters in length, outside of "
            "any [Discord markdown](https://support.discord.com/hc/en-us/articles/210298617) or ||[spoiler tags]"
            "(https://support.discord.com/hc/en-us/articles/360022320632)||. Queries cannot contain any of the following "
            'characters: ``\\";:=*%$&_<>?`[]``.'
        )
        self.single_newline = re.compile(r"(?<!\n)\n(?![\n\=-])")

    def add_command_formatting(self, command):
        """A utility function to format the non-indented block of commands and groups."""
        if command.description:
            self.paginator.add_line(command.description, empty=True)

        self.paginator.add_line(self.get_command_signature(command), empty=True)

        if command_help := self.single_newline.sub(" ", command.help):
            try:
                self.paginator.add_line(command_help, empty=True)
            except RuntimeError:
                for line in command_help.splitlines():
                    self.paginator.add_line(line)
                self.paginator.add_line()

    async def send_bot_help(self, mapping):
        """Send help embed for when no help arguments are specified."""
        ctx = self.context
        bot = ctx.bot
        prefix = (await get_prefix(bot, ctx.message))[-1]
        description = [self.description]

        if bot.get_cog("Games"):
            description.append(
                f"Use `{prefix}help ag s` for an explanation about how to configure Nexus Mods search for a server, or "
                f"`{prefix}help ag c` for a channel."
            )
        else:
            description.append(
                "**Important:** Load the Games extension to enable search configuration settings using "
                f"`{prefix}load games` (can only be done by bot admins)."
            )
        if not bot.get_cog("ModSearch"):
            description.append(
                f"**Important:** Load the ModSearch extension to enable Nexus Mods search using `{prefix}load modsearch` "
                "(can only be done by bot admins)."
            )
        embed = discord.Embed(
            title=f"{bot.user.name} | Help",
            description="\n\n".join(description),
            colour=ctx.guild.me.colour.value or 14323253,
        )
        embed.add_field(
            name="Links",
            value="[Discord Bot List](https://top.gg/bot/665861255051083806) | "
            "[GitHub](https://github.com/JonathanFeenstra/discord-modlinkbot) | "
            "[Add to your server](https://discordapp.com/oauth2/authorize?client_id="
            f"{bot.user.id}&permissions=67136705&scope=bot)",
            inline=False,
        )
        embed.set_footer(text=f"Prompted by @{ctx.author}", icon_url=ctx.author.avatar_url)

        await ctx.send(embed=embed)
        self.paginator.add_line(f"Commands (prefix = {repr(prefix)})", empty=True)

        def get_category(command):
            """Get command category (cog)."""
            return f"{command.cog.qualified_name}:" if command.cog is not None else "No Category:"

        max_size = self.get_max_size(filtered := await self.filter_commands(bot.commands, sort=True, key=get_category))

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

    def __init__(self):
        """Initialise bot."""
        super().__init__(
            command_prefix=get_prefix,
            help_command=ModLinkBotHelpCommand(),
            status=discord.Status.idle,
            owner_ids=getattr(config, "owner_ids", set()).copy(),
            intents=discord.Intents(guilds=True, members=True, bans=True, guild_messages=True, guild_reactions=True),
        )

        self.config = config
        self.db_connect = partial(
            connect, getattr(self.config, "db_path", "modlinkbot.db"), detect_types=PARSE_DECLTYPES | PARSE_COLNAMES
        )
        # https://help.nexusmods.com/article/114-api-acceptable-use-policy
        self.api_headers = {
            "Application-Version": __version__,
            "Application-Name": "discord-modlinkbot",
            "User-Agent": f"discord-modlinkbot/{__version__} (+https://github.com/JonathanFeenstra/discord-modlinkbot)",
            "Accept": "application/json",
            "apikey": config.nexus_api_key,
        }
        self.html_user_agent = (
            f"Mozilla/5.0 (compatible; discord-modlinkbot/{__version__};"
            " +https://github.com/JonathanFeenstra/discord-modlinkbot)"
        )
        self.blocked = set()

        self.loop.create_task(self.startup())

        for extension in ("admin", "games", "general", "modsearch"):
            try:
                self.load_extension(f"cogs.{extension}")
            except Exception as error:
                print(f"Failed to load extension {extension}: {error}", file=stderr)
                traceback.print_exc()

    async def _update_presence(self):
        """Update the bot's presence with the number of guilds."""
        await self.change_presence(
            activity=discord.Activity(
                name=f"messages in {'1 server' if (guild_count := len(self.guilds)) == 1 else f'{guild_count} servers'}",
                type=discord.ActivityType.watching,
            )
        )

    async def _get_add_info(self, guild, limit=50):
        """Get log entry of the addition of the bot to the specified guild when found."""
        if guild.me.guild_permissions.view_audit_log:
            async for log_entry in guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=limit):
                if log_entry.target == guild.me:
                    if log_entry.user.id in self.blocked:
                        return await guild.leave()
                    return log_entry
        return None

    async def _update_guild_configs(self):
        """Update configurations of guilds that joined or left while offline."""
        async with self.db_connect() as con:
            await con.execute("PRAGMA foreign_keys = ON")
            await con.execute(
                f"DELETE FROM guild WHERE guild_id NOT IN ({', '.join(str(guild.id) for guild in self.guilds)})"
            )
            await con.commit()

            db_guilds = [row[0] for row in await con.execute_fetchall("SELECT guild_id FROM guild")]

            async with con.execute("SELECT * FROM channel") as cur:
                async for channel_id, guild_id in cur:
                    if not (guild := self.get_guild(guild_id)):
                        await con.execute("DELETE FROM guild WHERE guild_id = ?", (guild_id,))
                    elif channel_id and not guild.get_channel(channel_id):
                        await con.execute("DELETE FROM channel WHERE guild_id = ?", (channel_id,))
            await con.commit()

        for guild in self.guilds:
            if guild.id not in db_guilds:
                await self.on_guild_join(guild)

    def validate_guild(self, guild):
        """Check if guild and its owner are not blocked and the guild limit not exceeded."""
        return (
            isinstance(guild, discord.Guild)
            and guild.id not in self.blocked
            and guild.owner_id not in self.blocked
            and (not (max_guilds := getattr(self.config, "max_guilds", False)) or len(self.guilds) <= max_guilds)
        )

    def validate_msg(self, msg):
        """Check if message is valid to be processed."""
        return not msg.author.bot and msg.author.id not in self.blocked and isinstance(msg.guild, discord.Guild)

    async def startup(self):
        """Perform startup tasks, prepare database and configurations."""
        self.session = ClientSession(loop=self.loop)
        self.adapter = discord.AsyncWebhookAdapter(self.session)

        async with self.db_connect() as con:
            with open("modlinkbot_db.ddl") as ddl:
                await con.executescript(ddl.read())
            await con.commit()

            self.blocked.update(*(await con.execute_fetchall("SELECT blocked_id FROM blocked")))

            admin_ids = await con.execute_fetchall("SELECT admin_id FROM admin")
            self.owner_ids.update(*admin_ids)

            self.app_owner_id = (await self.application_info()).owner.id
            self.owner_ids.add(self.app_owner_id)
            if self.app_owner_id not in admin_ids:
                await con.execute("INSERT OR IGNORE INTO admin VALUES (?)", (self.app_owner_id,))
                await con.commit()

        await self.wait_until_ready()
        await self._update_guild_configs()
        print(f"{self.user.name} has been summoned.")

    async def on_ready(self):
        """Update bot presence when ready."""
        await self._update_presence()

    async def on_message(self, msg):
        """Process new messages that are not from bots or DMs."""
        if not self.validate_msg(msg):
            return
        await self.process_commands(msg)

    async def log_guild_change(self, webhook_url, guild, add_info=True):
        """Send webhook log message when guild joins or leaves."""
        guild_string = f"**{discord.utils.escape_markdown(guild.name)}** ({guild.id})"
        embed = discord.Embed(
            description=(
                ":inbox_tray: {0} has been added to {1}." if add_info else ":outbox_tray: {0} has been removed from {1}."
            ).format(self.user.mention, guild_string),
            colour=guild.me.colour.value or 14323253,
        )
        embed.set_thumbnail(url=guild.banner_url)
        embed.timestamp = guild.created_at
        if description := guild.description:
            embed.add_field(name="Description", value=description, inline=False)

        embed.add_field(name="Member count", value=str(guild.member_count))
        if log_author := guild.owner:
            embed.set_footer(text=f"Owner: @{log_author} ({log_author.id}) | Created at", icon_url=log_author.avatar_url)
        else:
            log_author = self.user

        if add_info:
            if bot_inviter := getattr(add_info, "user", False):
                embed.description = f":inbox_tray: **@{bot_inviter}** has added {self.user.mention} to {guild_string}."
                log_author = bot_inviter
            else:
                embed.description = f":inbox_tray: {self.user.mention} has been added to {guild_string}."
            if invite := await get_guild_invite(guild):
                embed.set_author(name=guild.name, url=invite, icon_url=guild.icon_url)
                embed.add_field(name="Invite link", value=invite, inline=False)
        else:
            embed.set_author(name=guild.name, icon_url=guild.icon_url)

        try:
            await discord.Webhook.partial(*webhook_url.split("/")[-2:], adapter=self.adapter).send(
                embed=embed, username=f"{log_author} ({log_author.id})", avatar_url=log_author.avatar_url
            )
        except (discord.HTTPException, discord.NotFound, discord.Forbidden) as error:
            print(f"{error.__class__.__name__}: {error}", file=stderr)
            traceback.print_tb(error.__traceback__)

    async def on_guild_join(self, guild):
        """Set default guild configuration when joining a guild."""
        if not self.validate_guild(guild):
            return await guild.leave()
        add_info = await self._get_add_info(guild)
        async with self.db_connect() as con:
            await con.execute(
                "INSERT OR IGNORE INTO guild VALUES (?, '.', ?, 1)",
                (guild.id, getattr(add_info, "joined_at", datetime.now())),
            )
            await con.commit()
        await self._update_presence()
        if webhook_url := getattr(self.config, "webhook_url", False):
            await self.log_guild_change(webhook_url, guild, add_info or True)

    async def on_guild_remove(self, guild):
        """Remove guild configuration when leaving a guild."""
        if not self.validate_guild(guild):
            return
        async with self.db_connect() as con:
            await con.execute("PRAGMA foreign_keys = ON")
            await con.execute("DELETE FROM guild WHERE guild_id = ?", (guild.id,))
            await con.commit()
        await self._update_presence()
        if webhook_url := getattr(self.config, "webhook_url", False):
            await self.log_guild_change(webhook_url, guild, False)

    async def on_guild_channel_delete(self, channel):
        """Delete channel from database on deletion."""
        if not isinstance(channel, discord.TextChannel):
            return
        async with self.db_connect() as con:
            await con.execute("PRAGMA foreign_keys = ON")
            await con.execute("DELETE FROM channel WHERE channel_id = ?", (channel.id,))
            await con.commit()

    async def on_command_error(self, ctx, error):
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

    async def close(self):
        """Close the bot."""
        await self.session.close()
        await super().close()


if __name__ == "__main__":
    print("Starting...")
    modlinkbot = ModLinkBot()

    @modlinkbot.command(aliases=["loadcog"])
    @commands.is_owner()
    async def load(ctx, *, cog: str):
        """Load extension (bot admin only).

        Available extensions:
        - admin
        - db
        - modsearch
        - util
        """
        try:
            modlinkbot.load_extension(f"cogs.{cog}")
        except Exception as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        await ctx.send(f":white_check_mark: Successfully loaded '{cog}'.")

    @modlinkbot.command(aliases=["unloadcog"])
    @commands.is_owner()
    async def unload(ctx, *, cog: str):
        """Unload extension (bot admin only)."""
        try:
            modlinkbot.unload_extension(f"cogs.{cog}")
        except Exception as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        await ctx.send(f":white_check_mark: Successfully unloaded '{cog}'.")

    @modlinkbot.command(aliases=["reloadcog"])
    @commands.is_owner()
    async def reload(ctx, *, cog: str):
        """Reload extension (bot admin only)."""
        try:
            modlinkbot.reload_extension(f"cogs.{cog}")
        except Exception as error:
            await ctx.send(f":x: `{error.__class__.__name__}: {error}`")
        await ctx.send(f":white_check_mark: Succesfully reloaded '{cog}'.")

    modlinkbot.run(config.token)
