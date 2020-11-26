#!/usr/bin/env python3
"""
discord-modlinkbot
==================

A Discord bot for linking Nexus Mods search results.

Copyright (C) 2019-2020 Jonathan Feenstra

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
from collections import defaultdict
from datetime import datetime
from sqlite3 import connect, PARSE_COLNAMES, PARSE_DECLTYPES
from sys import stderr

import discord
from aiohttp import ClientSession
from aiosqlite import Connection
from discord.ext import commands

from itertools import groupby

import config
from cogs.util import SendErrorFeedback, feedback_embed


def _default_guild_config(**kwargs):
    """If no keyword arguments are provided, return default guild configuration, otherwise return `dict(**kwargs)`."""
    return dict(**kwargs) if kwargs else {'prefix': '.',
                                          'games': defaultdict(dict),
                                          'channels': defaultdict(dict),
                                          'joined_at': datetime.now()}


async def get_guild_invite(guild):
    """Get invite link to guild if possible."""
    if guild.me.guild_permissions.manage_guild:
        invites = await guild.invites()
        for invite in invites:
            if not (invite.max_age or invite.temporary):
                return invite.url
    if not (guild.channels and guild.me.guild_permissions.create_instant_invite):
        return ''
    if ((channel := guild.system_channel or guild.rules_channel or guild.public_updates_channel)
            and channel.permissions_for(guild.me).create_instant_invite):
        try:
            return (await channel.create_invite()).url
        except Exception:
            pass
    for channel in guild.channels:
        if channel.permissions_for(guild.me).create_instant_invite:
            try:
                return (await channel.create_invite()).url
            except Exception:
                continue
    return ''


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
            "characters: \";:=*%$&_<>?[]\\`.")
        self.single_newline = re.compile(r'(?<!\n)\n(?![\n\=-])')

    def add_command_formatting(self, command):
        """A utility function to format the non-indented block of commands and groups."""
        if command.description:
            self.paginator.add_line(command.description, empty=True)

        self.paginator.add_line(self.get_command_signature(command), empty=True)

        if help := self.single_newline.sub(' ', command.help):
            try:
                self.paginator.add_line(help, empty=True)
            except RuntimeError:
                for line in help.splitlines():
                    self.paginator.add_line(line)
                self.paginator.add_line()

    async def send_bot_help(self, mapping):
        """Send help embed for when no help arguments are specified."""
        ctx = self.context
        bot = ctx.bot
        prefix = bot.guild_configs[ctx.guild.id].get('prefix', '.')
        description = [self.description]

        if bot.get_cog('DB'):
            description.append(
                f"Use `{prefix}help setsf` for an explanation about how to configure Nexus Mods search for a server, or "
                f"`{prefix}help setchf` for a channel.")
        else:
            description.append(
                f"**Important:** Load the DB extension to enable search configuration settings using `{prefix}load db` "
                "(can only be done by bot admins).")
        if not bot.get_cog('ModSearch'):
            description.append(
                f"**Important:** Load the ModSearch extension to enable Nexus Mods search using `{prefix}load modsearch` "
                "(can only be done by bot admins).")
        embed = discord.Embed(title=f'{bot.user.name} | Help',
                              description='\n\n'.join(description),
                              colour=ctx.guild.me.colour.value or 14323253)
        embed.add_field(
            name='Links',
            value='[Discord Bot List](https://top.gg/bot/665861255051083806) | '
                  '[GitHub](https://github.com/JonathanFeenstra/discord-modlinkbot) | '
                  '[Add to your server](https://discordapp.com/oauth2/authorize?client_id='
                  f'{bot.user.id}&permissions=67202177&scope=bot)',
            inline=False)
        embed.set_footer(text=f'Prompted by @{ctx.author}', icon_url=ctx.author.avatar_url)

        await ctx.send(embed=embed)
        self.paginator.add_line(f"Commands (prefix = {repr(prefix)})", empty=True)

        def get_category(command):
            """Get command category (cog)."""
            return f'{cog.qualified_name}:' if (cog  := command.cog) is not None else 'No Category:'

        max_size = self.get_max_size(filtered := await self.filter_commands(bot.commands, sort=True, key=get_category))

        for category, cmds in groupby(filtered, key=get_category):
            self.add_indented_commands(sorted(cmds, key=lambda c: c.name), heading=category, max_size=max_size)

        self.paginator.add_line()
        self.paginator.add_line(f"Type {prefix}help command for more info on a command.\n"
                                f"Type {prefix}help category for more info on a category.")
        await self.send_pages()


class DBConnection(Connection):
    """Database connection."""
    async def __aenter__(self):
        """Enable foreign key support on connect."""
        await (db := await self).execute('PRAGMA foreign_keys = ON')
        return db


class ModLinkBot(commands.AutoShardedBot):
    """Discord Bot for linking Nexus Mods search results"""

    def __init__(self):
        """Initialise bot."""
        super().__init__(command_prefix=lambda bot, msg: commands.when_mentioned_or(
                            bot.guild_configs.get(msg.guild.id).get('prefix', '.') if msg.guild else '.')(bot, msg),
                         help_command=ModLinkBotHelpCommand(),
                         status=discord.Status.idle,
                         owner_ids=getattr(config, 'owner_ids', set()).copy(),
                         intents=discord.Intents(guilds=True,
                                                 members=True,
                                                 bans=True,
                                                 guild_messages=True))

        self.config = config
        self.guild_configs = defaultdict(_default_guild_config)
        self.blocked = set()

        for extension in ('admin', 'db', 'modsearch', 'util'):
            try:
                self.load_extension(f'cogs.{extension}')
            except Exception as e:
                print(f'Failed to load extension {extension}: {e}', file=stderr)
                traceback.print_exc()

        self.loop.create_task(self.startup())

    async def _create_db(self):
        """"Create SQLite database tables if they don't exist yet."""
        async with self.db_connect() as db:
            await db.execute("""
                CREATE TABLE
                IF NOT EXISTS guild (
                    id INTEGER NOT NULL PRIMARY KEY,
                    prefix TEXT NOT NULL DEFAULT '.',
                    joined_at TIMESTAMP NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE
                IF NOT EXISTS channel (
                    id INTEGER NOT NULL PRIMARY KEY,
                    guild_id INTEGER NOT NULL REFERENCES guild ON DELETE CASCADE
                )
            """)
            await db.execute("""
                CREATE TABLE
                IF NOT EXISTS game (
                    guild_id INTEGER NOT NULL REFERENCES guild ON DELETE CASCADE,
                    channel_id INTEGER NOT NULL DEFAULT 0 REFERENCES channel ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    filter TEXT,
                    PRIMARY KEY(guild_id, channel_id, name)
                )
            """)
            await db.execute("""
                CREATE TABLE
                IF NOT EXISTS blocked (
                    id INTEGER NOT NULL PRIMARY KEY
                )
            """)
            await db.execute("""
                CREATE TABLE
                IF NOT EXISTS admin (
                    id INTEGER NOT NULL PRIMARY KEY
                )
            """)
            await db.commit()

    async def _update_presence(self):
        """Update the bot's presence with the number of guilds."""
        await self.change_presence(activity=discord.Activity(
                name=f"messages in {'1 server' if (guild_count := len(self.guilds)) == 1 else f'{guild_count} servers'}",
                type=discord.ActivityType.watching))

    async def _update_invite_info(self, guild, limit=50):
        """Update guild configuration with data of bot invite when found."""
        guild_config = self.guild_configs[guild.id]
        if guild.me.guild_permissions.view_audit_log:
            async for log_entry in guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=limit):
                if log_entry.target == guild.me:
                    if log_entry.user.id in self.blocked:
                        return await guild.leave()
                    guild_config['inviter_name'] = str(log_entry.user)
                    guild_config['inviter_id'] = log_entry.user.id
                    guild_config['joined_at'] = log_entry.created_at
                    break
        async with self.db_connect() as db:
            await db.execute('INSERT OR IGNORE INTO guild VALUES (?, ?, ?)',
                             (guild.id, '.', guild_config.get('joined_at', datetime.now())))
            await db.commit()

    async def _update_guild_configs(self):
        """Update configurations of guilds that joined or left while offline."""
        async with self.db_connect() as db:
            await db.execute(f"DELETE FROM guild WHERE id NOT IN ({', '.join(str(guild.id) for guild in self.guilds)})")
            await db.commit()
            async with db.execute('SELECT * FROM guild') as cur:
                guilds = await cur.fetchall()
            for guild_id, prefix, joined_at in guilds:
                self.guild_configs.update({
                    guild_id: {'prefix': prefix,
                               'games': defaultdict(dict),
                               'channels': defaultdict(dict),
                               'joined_at': joined_at}
                })
            async with db.execute('SELECT * FROM game') as cur:
                games = await cur.fetchall()
            for guild_id, channel_id, game_name, filter in games:
                if not (guild := self.get_guild(guild_id)):
                    await db.execute('DELETE FROM guild WHERE id = ?', (guild_id,))
                elif not channel_id:
                    self.guild_configs[guild_id]['games'][game_name] = filter
                elif guild.get_channel(channel_id):
                    self.guild_configs[guild_id]['channels'][channel_id][game_name] = filter
                else:
                    await db.execute('DELETE FROM channel WHERE id = ?', (channel_id,))
            await db.commit()

        for guild in self.guilds:
            if guild.id not in self.guild_configs:
                await self.on_guild_join(guild)

    def db_connect(self):
        """Connect to the database."""
        return DBConnection(lambda: connect(getattr(self.config, 'db_path', 'modlinkbot.db'),
                                            detect_types=PARSE_DECLTYPES | PARSE_COLNAMES), 64)

    def validate_guild(self, guild):
        """Check if guild and its owner are not blocked and the guild limit not exceeded."""
        return (isinstance(guild, discord.Guild) and guild.id not in self.blocked and guild.owner_id not in self.blocked
                and (not (max := getattr(self.config, 'max_guilds', False)) or len(self.guilds) <= max))

    def validate_msg(self, msg):
        """Check if message is valid to be processed."""
        return (not msg.author.bot
                and msg.author.id not in self.blocked
                and self.validate_guild(msg.guild)
                and msg.channel.id not in self.blocked)

    async def startup(self):
        """Perform startup tasks, prepare database and configurations."""
        self.session = ClientSession(loop=self.loop)
        await self._create_db()
        await self.wait_until_ready()

        async with self.db_connect() as db:
            async with db.execute('SELECT id FROM blocked') as cur:
                blocked_ids = await cur.fetchall()
            self.blocked.update(*blocked_ids)

            async with db.execute('SELECT id FROM admin') as cur:
                admin_ids = await cur.fetchall()
            self.owner_ids.update(*admin_ids)

            self.app_owner_id = (await self.application_info()).owner.id
            self.owner_ids.add(self.app_owner_id)
            if self.app_owner_id not in admin_ids:
                await db.execute('INSERT OR IGNORE INTO admin VALUES (?)', (self.app_owner_id,))
                await db.commit()

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

    async def on_guild_join_or_leave(self, guild, join=True):
        """Update shown guild info on join/leave."""
        await self._update_presence()
        if not (webhook_url := getattr(self.config, 'webhook_url', False)):
            return
        guild_string = f"**{discord.utils.escape_markdown(guild.name)}** ({guild.id})"
        embed = discord.Embed(
            description=(":inbox_tray: {0} has been added to {1}." if join else
                         ":outbox_tray: {0} has been removed from {1}.").format(self.user.mention, guild_string),
            colour=guild.me.colour.value or 14323253)
        embed.set_thumbnail(url=guild.banner_url)
        embed.timestamp = guild.created_at
        if description := guild.description:
            embed.add_field(name='Description', value=description, inline=False)

        embed.add_field(name='Member count', value=str(guild.member_count))
        if owner := guild.owner:
            embed.set_footer(text=f'Owner: @{owner} ({owner.id}) | Server created', icon_url=owner.avatar_url)
        else:
            embed.set_footer(text='Server created')

        guild_config = self.guild_configs[guild.id]
        if (inviter_id := guild_config.get('inviter_id')) and (inviter := guild.get_member(inviter_id)):
            author = inviter
            if join:
                embed.description = f":inbox_tray: **@{inviter}** has added {self.user.mention} to {guild_string}."
        else:
            author = owner or self.user

        author_icon_url = guild.icon_url or guild.splash_url
        if join and (invite := await get_guild_invite(guild)):
            embed.set_author(name=guild.name,
                             url=invite,
                             icon_url=author_icon_url)
            embed.add_field(name="Invite link", value=invite, inline=False)
        else:
            embed.set_author(name=guild.name, icon_url=author_icon_url)

        try:
            discord.Webhook.partial(*webhook_url.split('/')[-2:], adapter=discord.RequestsWebhookAdapter()).send(
                                        embed=embed, username=f"{author} ({author.id})", avatar_url=author.avatar_url)
        except Exception as error:
            print(f'{error.__class__.__name__}: {error}', file=stderr)
            traceback.print_tb(error.__traceback__)

    async def on_guild_join(self, guild):
        """Set default guild configuration when joining a guild."""
        if not self.validate_guild(guild):
            return await guild.leave()
        self.guild_configs[guild.id] = _default_guild_config()
        await self._update_invite_info(guild)
        await self.on_guild_join_or_leave(guild, True)

    async def on_guild_remove(self, guild):
        """Remove guild configuration when leaving a guild."""
        if not self.validate_guild(guild):
            return
        self.guild_configs.pop(guild.id, None)
        async with self.db_connect() as db:
            await db.execute('DELETE FROM guild WHERE id = ?', (guild.id,))
            await db.commit()
        await self.on_guild_join_or_leave(guild, False)

    async def on_guild_channel_delete(self, channel):
        """Delete channel from database on deletion."""
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            del self.guild_configs[channel.guild.id]['channels'][channel.id]
        except KeyError:
            pass
        async with self.db_connect() as db:
            await db.execute('DELETE FROM channel WHERE id = ?', (channel.id,))
            await db.commit()

    async def on_command_error(self, ctx, error):
        """Handle command exceptions."""
        if isinstance(error, commands.CommandNotFound) or hasattr(ctx.command, 'on_error'):
            return

        error = getattr(error, 'original', error)

        if isinstance(error, (commands.ArgumentParsingError, commands.UserInputError, commands.CheckFailure)):
            await ctx.send(embed=feedback_embed(str(error), False))
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(embed=feedback_embed(
                           f"{ctx.author.mention} Command on cooldown. "
                           f"Try again after {round(error.retry_after, 1)} s.",
                           False))
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            if not isinstance(original, discord.HTTPException):
                print(f'In {ctx.command.qualified_name}:', file=stderr)
                traceback.print_tb(original.__traceback__)
                print(f'{original.__class__.__name__}: {original}', file=stderr)
        else:
            print(f'{error.__class__.__name__}: {error}', file=stderr)
            traceback.print_tb(error.__traceback__)

    async def close(self):
        """Close the bot."""
        await self.session.close()
        await super().close()


if __name__ == '__main__':
    print('Starting...')
    bot = ModLinkBot()

    @bot.command(aliases=['loadcog'])
    @commands.is_owner()
    async def load(ctx, *, cog: str):
        """Load extension (bot admin only).

        Available extensions:
        - admin
        - db
        - modsearch
        - util
        """
        async with SendErrorFeedback(ctx):
            bot.load_extension(f'cogs.{cog}')
        await ctx.send(embed=feedback_embed(f"Succesfully loaded '{cog}'."))

    @bot.command(aliases=['unloadcog'])
    @commands.is_owner()
    async def unload(ctx, *, cog: str):
        """Unload extension (bot admin only)."""
        async with SendErrorFeedback(ctx):
            bot.unload_extension(f'cogs.{cog}')
        await ctx.send(embed=feedback_embed(f"Succesfully unloaded '{cog}'."))

    @bot.command(aliases=['reloadcog'])
    @commands.is_owner()
    async def reload(ctx, *, cog: str):
        """Reload extension (bot admin only)."""
        async with SendErrorFeedback(ctx):
            bot.reload_extension(f'cogs.{cog}')
        await ctx.send(embed=feedback_embed(f"Succesfully reloaded '{cog}'."))

    bot.run(config.token)
