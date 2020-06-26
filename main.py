#!/usr/bin/env python3
"""
discord-modlinkbot
==================

A Discord bot for linking game mods.

:copyright: (c) 2019-2020 Jonathan Feenstra
:license: GPL-3.0
"""
import traceback
from collections import defaultdict
from datetime import datetime
from itertools import groupby
from sys import stderr

import discord
from discord.ext import commands

import config
from cogs.util import SendErrorFeedback, feedback_embed

__docformat__ = 'restructedtext'


def _prefix_callable(bot, msg):
    """Determine command prefixes to check for in `msg`.

    :param discord.Client bot: the bot to determine the prefixes for
    :param discord.Message msg: the message
    """
    base = [f'<@!{bot.user.id}> ', f'<@{bot.user.id}> ']
    if msg.guild and (guild_config := bot.guild_configs.get(msg.guild.id)):
        base.append(guild_config.get('prefix', '.'))
    else:
        base.append('.')
    return base


class ModLinkBot(commands.Bot):
    """Discord Bot for linking game mods"""

    def __init__(self):
        """Initialise bot."""
        super().__init__(command_prefix=_prefix_callable,
                         help_command=self.ModLinkBotHelpCommand())

        self.config = config
        self.guild_configs = defaultdict(self._default_guild_config)
        self.owner_ids = getattr(config, 'OWNER_IDS', set()).copy()
        self.blocked = set()

        for extension in getattr(config, 'INITIAL_COGS', ()):
            try:
                self.load_extension(extension)
            except Exception as e:
                print(f'Failed to load extension {extension}: {e}', file=stderr)
                traceback.print_exc()

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
                    f"Nexus Mods search for a server, or `{prefix}help setchf` for a channel."
                )
            else:
                description.append(
                    "**Important:** Load the DB extension to enable search configuration settings "
                    f"using `{prefix}load db` (can only be done by bot admins)."
                )
            if not bot.get_cog('ModSearch'):
                description.append(
                    "**Important:** Load the ModSearch extension to enable Nexus Mods search "
                    f"using `{prefix}load modsearch` (can only be done by bot admins)."
                )
            embed = discord.Embed(
                title=f'{bot.user.name} | Help',
                description='\n\n'.join(description),
                colour=ctx.guild.me.colour.value or 14323253
            )
            embed.add_field(
                name='Links',
                value='[GitHub](https://github.com/JonathanFeenstra/discord-modlinkbot)'
                      ' | [Invite](https://discordapp.com/oauth2/authorize?client_id='
                      f'{bot.user.id}&permissions=67202176&scope=bot)',
                inline=False)
            embed.set_footer(text=f'Prompted by @{ctx.author}', icon_url=ctx.author.avatar_url)

            await ctx.send(embed=embed)
            self.paginator.add_line(f"Commands (prefix = {repr(prefix)})", empty=True)
            await super().send_bot_help(mapping)

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
                    break

    async def _update_guild_configs(self):
        """Update configurations of guilds that joined while offline."""
        for guild in self.guilds:
            if guild.id not in self.guild_configs:
                if self.validate_guild(guild):
                    self.guild_configs[guild.id] = self._default_guild_config()
                    await self._update_invite_info(guild)
                else:
                    await guild.leave()

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
                and (not (max := getattr(self.config, 'MAX_GUILDS'))
                     or len(self.guilds) <= max))

    async def on_ready(self):
        """Print when the bot is ready."""
        print(f"{self.user.name} has been summoned.")
        app_info = await self.application_info()
        self.app_owner_id = app_info.owner.id
        self.owner_ids.add(self.app_owner_id)
        await self._update_guild_configs()
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

    async def on_command_error(self, ctx, error):
        """Handle command exceptions.

        :param discord.ext.Commands.Context ctx: event context
        :param Exception error: the exception
        """
        if isinstance(error, commands.CommandNotFound):
            pass
        elif isinstance(error, commands.ArgumentParsingError):
            await ctx.send(error)
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"{ctx.author.mention} Command on cooldown. "
                           f"Try again after {round(error.retry_after, 1)} s.")
        else:
            print(error, file=stderr)


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

    bot.run(config.DEV)
