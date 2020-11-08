"""
ModSearch
=========

Cog for searching Nexus Mods.

Functionality based on:
-  u/modlinkbot for Reddit:
  https://www.reddit.com/r/modlinkbotsub/comments/dlp7d1/bot_operation_and_information/
- Nexus Mods Discord Bot quicksearch:
  https://github.com/Nexus-Mods/discord-bot/blob/master/nexus-discord.js

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
import re
from html import unescape
from urllib.parse import quote

import discord
from aiohttp import ClientResponseError
from discord.ext import commands

from .util import feedback_embed

# Regex patterns

# Match Discord markdown, see:
# https://support.discord.com/hc/en-us/articles/210298617
MARKDOWN = re.compile((r"```.*?```"                      # ```multiline code```
                       r"|`.*?`"                         # `inline code`
                       r"|^>\s.*?$"                      # > quote
                       r"|\*\*\*(?!\s).*?(?<!\s)\*\*\*"  # ***bold italics***
                       r"|\*\*(?!\s).*?(?<!\s)\*\*"      # **bold**
                       r"|\*(?!\s).*?(?<!\s)\*"          # *italics*
                       r"|__.*?__"                       # __underline__
                       r"|~~.*?~~"                       # ~~strikethrough~~
                       r"|\|\|.*?\|\|"),                 # ||spoiler||
                      re.DOTALL | re.MULTILINE)
# Match text {between braces} excluding specific characters (";:=*%$&_<>?`[])
NEXUS_SEARCH_QUERIES = re.compile(r"{([^\";:=\*%\$&_<>\?`\[\]]*?)}", re.DOTALL)
# Match if query string disables the filter for adult content, see:
# https://help.nexusmods.com/article/19-adult-content-guidelines#Adult_Content_Classifications
NEXUS_INCLUDE_ADULT = re.compile(r"&include_adult=(true|1)(&|$)", re.IGNORECASE)
# Leading/trailing characters to remove from Nexus Search queries
STRIP = re.compile(r"^[^\w]+|[^\w]+$")
# Special patterns to replace with commas in Nexus Search queries
SPECIAL = re.compile(r"[^\w]+")
# Whitespace to replace with single spaces in embeds
WHITESPACE = re.compile(r"\s+")

# Nexus Mods global search results string
NEXUS_GLOBAL_SEARCH = ("[Global Search](https://www.nexusmods.com/search/?gsearch={0}&gsearchtype=mods) | "
                       "[DuckDuckGo Search](https://duckduckgo.com/?q={0})")


def parse_query(query: str):
    """Parse Nexus Mods search query.

    :param str query: query to parse
    :return: parsed query
    :rtype: str
    """
    return SPECIAL.sub(',', STRIP.sub('', query.replace("'s", '')))


def find_queries(text: str):
    """Find unique Nexus Mods search queries in plain text.

    :param str text: text to parse
    :return: queries
    :rtype: list[str]
    """
    queries = []

    for query_text in NEXUS_SEARCH_QUERIES.findall(MARKDOWN.sub('?', text)):
        for query in query_text.split(','):
            if 2 < len(parse_query(query)) <= 120:
                queries.append(query.strip())

    return list(dict.fromkeys(queries))


class ModSearch(commands.Cog):
    """Cog for searching Nexus Mods."""

    def __init__(self, bot):
        """Initialise cog.

        :param discord.Client bot: bot to add cog to
        """
        self.bot = bot

    async def _fetch_nexus_results(self, embed, queries, game_filters):
        """Return Discord embed with mod search results from `queries`.

        :param discord.Embed embed: embed to add results to
        :param list[str] queries: queries to search for
        :param dict{str: str} game_filters: Nexus Mods search filters per game
        :return: Discord embed with Nexus Mods results
        :rtype: discord.Embed
        """
        for query in queries:
            embed.add_field(name="Search results for:", value=f"**{repr(WHITESPACE.sub(' ', query))}**", inline=False)
            any_results = False
            for game_name, filter in game_filters.items():
                try:
                    results = await self.nexus_search(query, filter)
                except Exception as e:
                    any_results = True
                    embed.add_field(name=game_name,
                                    value=(f'[`Error {e.status}: {e.message}`]({e.request_info.real_url})\n'
                                           '[Server Status](https://www.isitdownrightnow.com/nexusmods.com.html) | '
                                           if isinstance(e, ClientResponseError) else
                                           f'`{e.__class__.__name__}: {e}`\n') + NEXUS_GLOBAL_SEARCH.format(quote(query)),
                                    inline=False)
                else:
                    if n_results := len(results):
                        any_results = True
                        if len(mod_name := unescape((mod := results[0])['name'])) > 128:
                            mod_name = f"{mod_name[:125]}..."
                        search_result = f"[{mod_name}](https://nexusmods.com{mod['url']})"
                        if n_results > 1:
                            search_result = (f"{search_result} | [More results](https://www.nexusmods.com/"
                                             f"{mod['game_name']}/mods/?RH_ModList=include_adult:"
                                             f"{bool(NEXUS_INCLUDE_ADULT.search(filter))},open:true,search_filename:"
                                             f"{parse_query(query).replace(',', '+')}#permalink)")
                        embed.add_field(name=game_name, value=search_result)
            if not any_results:
                embed.add_field(name="No results.", value=NEXUS_GLOBAL_SEARCH.format(quote(query)), inline=False)
        return embed

    async def nexus_search(self, query: str, filter: str):
        """Search Nexus Mods for `query` using `filter` and return results.

        :param str query: query to search for
        :param filter: Nexus Mods search API filter
        :return: search results
        :rtype: list[dict]
        :raise aiohttp.ClientResponseError: if status code is not 200
        """
        async with self.bot.session.get(
                f"https://search.nexusmods.com/mods?terms={parse_query(query)}{filter}",
                headers={'User-Agent': 'Mozilla/5.0'}) as res:
            if res.status == 200:
                response_json = await res.json()
                return response_json.get('results')
            else:
                raise ClientResponseError(request_info=res.request_info,
                                          status=res.status,
                                          message=res.reason,
                                          headers=res.headers,
                                          history=res.history)

    async def send_nexus_results(self, ctx, queries, nexus_config):
        """Send Nexus Mods query results.

        :param discord.ext.Commands.Context ctx: event context
        :param list[str] queries: Nexus Mods queries
        :param dict nexus_config: Nexus Mods games and search API filters
        """
        embed = discord.Embed(colour=14323253)
        embed.set_author(name='Nexus Mods',
                         url='https://www.nexusmods.com/',
                         icon_url='https://images.nexusmods.com/favicons/ReskinOrange/favicon-32x32.png')
        embed.set_footer(text=f'Searched by @{ctx.author}',
                         icon_url=ctx.author.avatar_url)

        if (n_queries := len(queries)) > (max_queries := getattr(self.bot.config, 'MAX_RESULT_EMBEDS', 3) * (per_embed := 25 // (len(nexus_config) + 1))):
            embed.description = f':x: Too many queries in message (max={max_queries}).'
            return await ctx.send(embed=embed)

        for idx in range(0, n_queries, per_embed):
            embed.description = ":mag_right: Searching mods..."
            embed.clear_fields()
            result_msg = await ctx.channel.send(embed=embed)
            embed.description = None
            embed = await self._fetch_nexus_results(
                embed,
                queries[idx:idx + per_embed],
                nexus_config)
            await result_msg.edit(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, msg):
        """Check for mod search queries in valid new messages and send results.

        :param discord.Message msg: the new message
        """
        if not self.bot.validate_msg(msg):
            return

        ctx = await self.bot.get_context(msg)
        nexus_config = (guild_config := self.bot.guild_configs[ctx.guild.id])['channels'][ctx.channel.id] or guild_config['games']

        if ctx.valid or not nexus_config or not (queries := find_queries(msg.content)):
            return

        if not ctx.channel.permissions_for(ctx.me).embed_links:
            await ctx.send(":x: **Searching mods requires 'Embed Links' permission.**")
        else:
            await self.send_nexus_results(ctx, queries, nexus_config)

    @commands.command(aliases=['nexussearch', 'modsearch'])
    @commands.has_permissions(embed_links=True)
    async def nexus(self, ctx, *, query_text: str):
        """Search for query on Nexus Mods.

        :param discord.ext.Commands.Context ctx: event context
        :param str query_text: text with query/queries to search for
        """
        nexus_config = self.bot.guild_configs[ctx.guild.id]['channels'].get(
            ctx.channel.id, self.bot.guild_configs[ctx.guild.id]['games'])
        if not nexus_config:
            return await ctx.send(
                embed=feedback_embed('No search filters configured.', False)
            )
        if queries := find_queries(f'{{{query_text}}}'):
            await self.send_nexus_results(ctx, queries, nexus_config)
        else:
            await ctx.send(embed=feedback_embed('Invalid query.', False))


def setup(bot):
    """Add this cog to bot.

    :param discord.Client bot: bot to add cog to
    """
    bot.add_cog(ModSearch(bot))
