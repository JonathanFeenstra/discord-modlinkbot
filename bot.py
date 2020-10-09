#!/usr/bin/env python3
"""
discord-modlinkbot
==================

A Discord bot for linking game mods.

:copyright: (C) 2019-2020 Jonathan Feenstra
:license: GPL-3.0

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
import traceback
from collections import defaultdict
from datetime import datetime
from itertools import groupby
from sys import stderr

import discord
from aiohttp import ClientSession
from discord.ext import commands

import config
from cogs.util import SendErrorFeedback, feedback_embed
from db_service import DBService

__docformat__ = 'restructedtext'


def _prefix_callable(bot, msg):
    """Determine command prefixes to check for in `msg`.

    :param discord.Client bot: the bot to determine the prefixes for
    :param discord.Message msg: the message
    """
    if msg.guild and (guild_config := bot.guild_configs.get(msg.guild.id)):
        return commands.when_mentioned_or(guild_config.get('prefix', '.'))(bot, msg)
    return commands.when_mentioned_or('.')(bot, msg)

def _send_webhook(webhook_url: str, **kwargs):
    """Send a message using the specified webhook.

    :param str webhook_url: URL of the webhook to send to
    """
    webhook = discord.Webhook.partial(*webhook_url.split('/')[-2:],
                                      adapter=discord.RequestsWebhookAdapter())
    return webhook.send(**kwargs)

class ModLinkBotHelpCommand(commands.DefaultHelpCommand):
    """Help command for modlinkbot."""

    def add_command_formatting(self, command):
        """
        A utility function to format the non-indented block of commands and
        groups.

        :param discord.ext.commands.Command command: the command to format
        """
        if command.description:
            self.paginator.add_line(command.description, empty=True)

        signature = self.get_command_signature(command)
        self.paginator.add_line(signature, empty=True)

        if command.help:
            for line in command.help.splitlines():
                if not line.startswith(':'):
                    self.paginator.add_line(line)
                else:
                    break
            self.paginator.add_line()

    async def send_bot_help(self, mapping):
        """Send help embed for when no help arguments are specified.

        :param mapping: optional mapping of cogs to commands
        """
        ctx = self.context
        bot = ctx.bot
        prefix = bot.guild_configs[ctx.guild.id].get('prefix', '.')

        description = [
            "Configure a server or channel to retrieve search results from "
            "[Nexus Mods](https://www.nexusmods.com/) for search queries in "
            "messages {between braces, separated by commas}, 3 to 100 characters "
            "in length, outside of any [Discord markdown](https://support.discord.com/hc/en-us/articles/210298617) "
            "or ||[spoiler tags](https://support.discord.com/hc/en-us/articles/360022320632)||."
            "This includes: *{cursive text}*, **{bold text}**, __{underlined text}__, "
            "~~{strikethrough text}~~, `{inline code blocks}`,\n"
            "```\n{multiline\ncode\nblocks}```\nand\n> {block quotes}.",
            "Queries cannot contain any of the following characters: `\";:=*%$&_<>?[]`."
        ]
        if bot.get_cog('DB'):
            description.append(
                f"Use `{prefix}help setsf` for an explanation about how to configure "
                f"Nexus Mods search for a server, or `{prefix}help setchf` for a channel.")
        else:
            description.append(
                "**Important:** Load the DB extension to enable search configuration settings "
                f"using `{prefix}load db` (can only be done by bot admins).")
        if not bot.get_cog('ModSearch'):
            description.append(
                "**Important:** Load the ModSearch extension to enable Nexus Mods search "
                f"using `{prefix}load modsearch` (can only be done by bot admins).")
        embed = discord.Embed(title=f'{bot.user.name} | Help',
                              description='\n\n'.join(description),
                              colour=ctx.guild.me.colour.value or 14323253)
        embed.add_field(
            name='Links',
            value='[GitHub](https://github.com/JonathanFeenstra/discord-modlinkbot)'
                  ' | [Add to your server](https://discordapp.com/oauth2/authorize?client_id='
                  f'{bot.user.id}&permissions=67202209&scope=bot)',
            inline=False)
        embed.set_footer(text=f'Prompted by @{ctx.author}', icon_url=ctx.author.avatar_url)

        await ctx.send(embed=embed)
        self.paginator.add_line(f"Commands (prefix = {repr(prefix)})", empty=True)
        await super().send_bot_help(mapping)


class ModLinkBot(commands.AutoShardedBot):
    """Discord Bot for linking game mods"""

    def __init__(self):
        """Initialise bot."""
        super().__init__(command_prefix=_prefix_callable,
                         help_command=ModLinkBotHelpCommand(),
                         status=discord.Status.idle,
                         owner_ids=getattr(config, 'OWNER_IDS', set()).copy(),
                         intents=discord.Intents(guilds=True,
                                                 members=True,
                                                 bans=True,
                                                 guild_messages=True))

        self.config = config
        self.guild_configs = defaultdict(self._default_guild_config)
        self.blocked = set()

        for extension in getattr(config, 'INITIAL_COGS', ()):
            try:
                self.load_extension(extension)
            except Exception as e:
                print(f'Failed to load extension {extension}: {e}', file=stderr)
                traceback.print_exc()

    def _default_guild_config(self, **kwargs):
        """
        If no keyword arguments are provided, return default guild
        configuration, otherwise return `dict(**kwargs)`.

        :return: guild configuration
        :rtype: dict
        """
        if not kwargs:
            return {'prefix': '.',
                    'games': defaultdict(dict),
                    'channels': defaultdict(dict),
                    'inviter_name': 'Unknown',
                    'inviter_id': 404,
                    'joined_at': datetime.now()}
        return dict(**kwargs)

    async def _update_presence(self):
        """Update the bot's presence with the number of guilds."""
        if (guild_count := len(self.guilds)) == 1:
            await self.change_presence(activity=discord.Activity(
                    name="messages in 1 server",
                    type=discord.ActivityType.watching))
        else:
            await self.change_presence(activity=discord.Activity(
                    name=f"messages in {guild_count} servers",
                    type=discord.ActivityType.watching))

    async def _update_invite_info(self, guild, limit=50):
        """Update guild configuration with data of bot invite when found.

        :param discord.Guild guild: the guild
        :param int limit: max audit log entries to look through
        """
        guild_config = self.guild_configs[guild.id]
        if guild.me.guild_permissions.view_audit_log:
            async for log_entry in guild.audit_logs(
                    action=discord.AuditLogAction.bot_add, limit=limit):
                if log_entry.target == guild.me:
                    if log_entry.user.id in self.blocked:
                        return await guild.leave()
                    else:
                        guild_config['inviter_name'] = str(log_entry.user)
                        guild_config['inviter_id'] = log_entry.user.id
                        guild_config['joined_at'] = log_entry.created_at
                        await self.db.execute(
                            """INSERT OR IGNORE INTO guild
                               VALUES (?, ?, ?, ?, ?)""",
                            (guild.id, '.', str(log_entry.user), log_entry.user.id, log_entry.created_at))
                        await self.db.commit()
                    break
        else:
            await self.db.execute("""INSERT OR IGNORE INTO guild
                                    VALUES (?, ?, ?, ?, ?)""",
                                  (guild.id, '.', 'Unknown', 404, datetime.now()))
            await self.db.commit()

    async def _update_guild_configs(self):
        """Update configurations of guilds that joined or left while offline."""
        guilds = await (await self.db.execute('SELECT * FROM guild')).fetchall()
        for guild_id, prefix, inviter_name, inviter_id, joined_at in guilds:
            if self.get_guild(guild_id):
                self.guild_configs.update({
                    guild_id: {'prefix': prefix,
                               'games': defaultdict(dict),
                               'channels': defaultdict(dict),
                               'inviter_name': inviter_name,
                               'inviter_id': inviter_id,
                               'joined_at': joined_at}
                })
            else:
                await self.db.execute('DELETE FROM guild WHERE id = ?', (guild_id,))

        await self.db.commit()

        games = await (await self.db.execute('SELECT * FROM game')).fetchall()
        for game_name, filter, guild_id, channel_id in games:
            if not (guild := self.get_guild(guild_id)):
                await self.db.execute('DELETE FROM guild WHERE id = ?', (guild_id,))
            elif channel_id is None:
                self.guild_configs[guild_id]['games'][game_name] = filter
            elif guild.get_channel(channel_id):
                self.guild_configs[guild_id]['channels'][channel_id][game_name] = filter
            else:
                await self.db.execute('DELETE FROM channel WHERE id = ?', (channel_id,))

        await self.db.commit()

        for guild in self.guilds:
            if guild.id not in self.guild_configs:
                await self.on_guild_join(guild)

    def validate_msg(self, msg):
        """Check if message is valid to be processed.

        :param discord.Message msg: the message
        :return: whether the message is valid
        :rtype: bool
        """
        return (not msg.author.bot
                and msg.author.id not in self.blocked
                and self.validate_guild(msg.guild)
                and msg.channel.id not in self.blocked)

    def validate_guild(self, guild):
        """
        Check if guild and its owner are not blocked and the guild limit not
        exceeded.

        :param discord.Guild guild: the guild
        :return: whether the guild is satifies the conditions
        :rtype: bool
        """
        return (isinstance(guild, discord.Guild)
                and guild.id not in self.blocked
                and guild.owner_id not in self.blocked
                and (not (max := getattr(self.config, 'MAX_GUILDS', False))
                     or len(self.guilds) <= max))

    async def get_guild_invite(self, guild):
        """Get invite link to guild if possible.

        :param discord.Guild guild: the guild
        :return: guild invite link or empty string
        :rtype: str
        """
        if guild.me.guild_permissions.manage_guild:
            invites = await guild.invites()
            for invite in invites:
                if not (invite.max_age or invite.temporary):
                    return invite.url
        if not (guild.channels and guild.me.guild_permissions.create_instant_invite):
            return ''
        if (channel := guild.system_channel or guild.rules_channel or guild.public_updates_channel) and channel.permissions_for(guild.me).create_instant_invite:
            try:
                invite = await channel.create_invite()
                return invite
            except Exception:
                pass
        for channel in guild.channels:
            if channel.permissions_for(guild.me).create_instant_invite:
                try:
                    invite = await channel.create_invite()
                    return invite
                except Exception:
                    continue
        return ''

    async def on_ready(self):
        """Prepare the database and bot configurations when ready."""
        print(f"{self.user.name} has been summoned.")

        self.db = await DBService.create()
        self.session = ClientSession()

        blocked_ids = await (await self.db.execute('SELECT id FROM blocked')).fetchall()
        self.blocked.update(*blocked_ids)

        admin_ids = await (await self.db.execute('SELECT id FROM admin')).fetchall()
        self.owner_ids.update(*admin_ids)

        app_info = await self.application_info()
        self.app_owner_id = app_info.owner.id
        self.owner_ids.add(self.app_owner_id)

        await self._update_guild_configs()
        await self.change_presence(status=discord.Status.online)
        await self._update_presence()

    async def on_message(self, msg):
        """Process new messages that are not from bots or DMs.

        :param discord.Message msg: the new message
        """
        if not self.validate_msg(msg):
            return
        await self.process_commands(msg)

    async def on_guild_join(self, guild):
        """Set default guild configuration when joining a guild.

        :param discord.Guild guild: the guild
        """
        if self.validate_guild(guild):
            self.guild_configs[guild.id] = self._default_guild_config()
            await self._update_invite_info(guild)
            await self._update_presence()
            if webhook_url := getattr(self.config, 'WEBHOOK_URL', False):
                embed = discord.Embed(
                    description=f":inbox_tray: {self.user.mention} has been added to **{guild.name}**.",
                    colour=guild.me.colour.value or 14323253)
                embed.set_thumbnail(url=str(guild.banner_url))
                embed.timestamp = guild.created_at

                author_icon_url = str(guild.icon_url) or str(guild.splash_url)

                if invite := await self.get_guild_invite(guild):
                    embed.set_author(name=guild.name,
                                     url=invite,
                                     icon_url=author_icon_url)
                    embed.add_field(name="Invite link", value=invite, inline=False)
                else:
                    embed.set_author(name=guild.name, icon_url=author_icon_url)

                if description := guild.description:
                    embed.add_field(name='Description', value=guild.description, inline=False)

                embed.add_field(name='Member count', value=str(guild.member_count))

                if owner := guild.owner:
                    embed.set_footer(text=f'Owner: @{owner} | Server created at',
                                     icon_url=owner.avatar_url)
                else:
                    embed.set_footer(text='Server created at')

                guild_config = self.guild_configs[guild.id]
                if (inviter_id := guild_config['inviter_id']) != 404 and (inviter := guild.get_member(inviter_id)):
                    embed.description = f":inbox_tray: **@{inviter}** has added {self.user.mention} to **{guild.name}**."
                    username = str(inviter)
                    avatar_url = inviter.avatar_url
                elif owner:
                    username = str(owner)
                    avatar_url = owner.avatar_url
                else:
                    username = self.user.name
                    avatar_url = self.user.avatar_url

                try:
                    _send_webhook(webhook_url,
                                  embed=embed,
                                  username=username,
                                  avatar_url=avatar_url)
                except Exception as error:
                    print(f'{error.__class__.__name__}: {error}', file=stderr)
                    traceback.print_tb(error.__traceback__)
        else:
            await guild.leave()

    async def on_guild_remove(self, guild):
        """Remove guild configuration when leaving a guild.

        :param discord.Guild guild: the guild
        """
        await self._update_presence()
        try:
            del self.guild_configs[guild.id]
        except KeyError:
            pass
        await self.db.execute('DELETE FROM guild WHERE id = ?', (guild.id,))
        await self.db.commit()
        if (webhook_url := getattr(self.config, 'WEBHOOK_URL', False)) and self.validate_guild(guild):
            embed = discord.Embed(
                description=f":outbox_tray: {self.user.mention} has been removed from **{guild.name}**.",
                colour=14323253)
            embed.set_thumbnail(url=str(guild.banner_url))
            embed.set_author(name=guild.name,
                             icon_url=str(guild.icon_url) or str(guild.splash_url))
            embed.timestamp = guild.created_at

            if description := guild.description:
                embed.add_field(name='Description', value=guild.description, inline=False)

            embed.add_field(name='Member count', value=str(guild.member_count))

            if owner := guild.owner:
                embed.set_footer(text=f'Owner: @{owner} | Server created at',
                                 icon_url=owner.avatar_url)
            else:
                embed.set_footer(text='Server created at')

            guild_config = self.guild_configs[guild.id]
            if (inviter_id := guild_config['inviter_id']) != 404 and (inviter := guild.get_member(inviter_id)):
                username = str(inviter)
                avatar_url = inviter.avatar_url
            elif owner:
                username = str(owner)
                avatar_url = owner.avatar_url
            else:
                username = self.user.name
                avatar_url = self.user.avatar_url

            try:
                _send_webhook(webhook_url,
                              embed=embed,
                              username=username,
                              avatar_url=avatar_url)
            except Exception as error:
                print(f'{error.__class__.__name__}: {error}', file=stderr)
                traceback.print_tb(error.__traceback__)

    async def on_guild_channel_delete(self, channel):
        """Delete channel from database on deletion.

        :param discord.abc.GuildChannel channel: the deleted channel
        """
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            del self.guild_configs[channel.guild.id]['channels'][channel.id]
        except KeyError:
            pass
        await self.db.execute('DELETE FROM channel WHERE id = ?', (channel.id,))
        await self.db.commit()

    async def on_command_error(self, ctx, error):
        """Handle command exceptions.

        :param discord.ext.Commands.Context ctx: event context
        :param Exception error: the exception
        """
        if isinstance(error, commands.CommandNotFound) or hasattr(ctx.command, 'on_error'):
            return

        error = getattr(error, 'original', error)

        if isinstance(error, (commands.ArgumentParsingError, commands.UserInputError)):
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
        """
        Closes the aiohttp client session as well as the connections with the
        database and Discord.
        """
        if db := getattr(self, 'db', False):
            await db.close()
        if session := getattr(self, 'session', False):
            await session.close()
        return await super().close()


if __name__ == '__main__':
    print('Starting...')
    bot = ModLinkBot()

    @bot.command(aliases=['loadcog'])
    @commands.check(commands.is_owner())
    async def load(ctx, *, cog: str):
        """Load extension (bot admin only).

        Available extensions:
        - admin
        - db
        - modsearch
        - util

        :param discord.ext.Commands.Context ctx: event context
        :param str cog: cog to load
        """
        async with SendErrorFeedback(ctx):
            bot.load_extension(f'cogs.{cog}')
        await ctx.send(embed=feedback_embed(f"Succesfully loaded '{cog}'."))

    @bot.command(aliases=['unloadcog'])
    @commands.check(commands.is_owner())
    async def unload(ctx, *, cog: str):
        """Unload extension (bot admin only).

        :param discord.ext.Commands.Context ctx: event context
        :param str cog: cog to unload
        """
        async with SendErrorFeedback(ctx):
            bot.unload_extension(f'cogs.{cog}')
        await ctx.send(embed=feedback_embed(f"Succesfully unloaded '{cog}'."))

    @bot.command(aliases=['reloadcog'])
    @commands.check(commands.is_owner())
    async def reload(ctx, *, cog: str):
        """Reload extension (bot admin only).

        :param discord.ext.Commands.Context ctx: event context
        :param str cog: cog to reload
        """
        async with SendErrorFeedback(ctx):
            bot.reload_extension(f'cogs.{cog}')
        await ctx.send(embed=feedback_embed(f"Succesfully reloaded '{cog}'."))

    bot.run(config.TOKEN)
