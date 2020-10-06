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
from aiohttp.web import HTTPException
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

    plain_text = MARKDOWN.sub('?', text)

    for query_text in NEXUS_SEARCH_QUERIES.findall(plain_text):
        for query in query_text.split(','):
            parsed_query_length = len(parse_query(query))
            if parsed_query_length > 2 and parsed_query_length <= 120:
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
            shown_query = repr(WHITESPACE.sub(' ', query))
            quoted_query = quote(query)
            global_search = f"[Nexus Mods Global Search](https://www.nexusmods.com/search/?gsearch={quoted_query}&gsearchtype=mods) | [DuckDuckGo Search](https://duckduckgo.com/?q={quoted_query})"
            embed.add_field(name="Search results for:",
                            value=f"**{shown_query}**",
                            inline=False)
            any_results = False
            for game_name, filter in game_filters.items():
                include_adult = bool(NEXUS_INCLUDE_ADULT.search(filter))
                try:
                    results = await self.nexus_search(query, filter)
                    if results:
                        any_results = True
                        mod = results[0]
                        mod_name = unescape(mod['name'])
                        if len(mod_name) > 128:
                            mod_name = f"{mod_name[:125]}..."
                        search_result = f"[{mod_name}](https://nexusmods.com{mod['url']})"
                        if len(results) > 1:
                            search_result = f"{search_result} | [More results](https://www.nexusmods.com/{results[0]['game_name']}/mods/?RH_ModList=nav:true,home:false,type:0,user_id:0,advfilt:true,include_adult:{include_adult},page_size:20,open:true,search_filename:{parse_query(query).replace(',', '+')}#permalink)"
                        embed.add_field(name=game_name, value=search_result)
                except HTTPException as e:
                    any_results = True
                    embed.add_field(name=game_name,
                                    value=f"[`{e}`]({e.url})\n[Server Status]"
                                          "(https://www.isitdownrightnow.com/nexusmods.com.html)"
                                          f" | {global_search}",
                                    inline=False)
                except Exception as e:
                    any_results = True
                    embed.add_field(name=game_name,
                                    value=f"`{e.__class__.__name__}: {e}`\n{global_search}",
                                    inline=False)
            if not any_results:
                embed.add_field(name=f"No results.",
                                value=global_search,
                                inline=False)
        return embed

    async def nexus_search(self, query: str, filter: str):
        """Search Nexus Mods for `query` using `filter` and return results.

        :param str query: query to search for
        :param filter: Nexus Mods search API filter
        :return: search results
        :rtype: list[dict]
        :raise aiohttp.web.HTTPException: if status code is not 200
        """
        async with self.bot.session.get(
                f"https://search.nexusmods.com/mods?terms={parse_query(query)}{filter}",
                headers={'User-Agent': 'Mozilla/5.0'}) as res:
            if res.status == 200:
                response_json = await res.json()
                return response_json.get('results')
            else:
                raise HTTPException(status=res.status, reason=res.reason, url=res.url)

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
        if len(queries) > 20:
            embed.description = ':x: Too many queries in message (max=20).'
            return await ctx.send(embed=embed)

        queries_per_embed = 25 // (len(nexus_config) + 1)
        for idx in range(0, len(queries), queries_per_embed):
            embed.description = ":mag_right: Searching mods..."
            embed.clear_fields()
            result_msg = await ctx.channel.send(embed=embed)
            embed.description = None
            embed = await self._fetch_nexus_results(
                embed,
                queries[idx:idx + queries_per_embed],
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
        nexus_config = self.bot.guild_configs[ctx.guild.id]['channels'].get(
            ctx.channel.id, self.bot.guild_configs[ctx.guild.id]['games'])

        if ctx.valid or not nexus_config:
            return

        queries = find_queries(msg.content)

        if not queries:
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
        queries = find_queries(f'{{{query_text}}}')
        if queries:
            await self.send_nexus_results(ctx, queries, nexus_config)
        else:
            await ctx.send(embed=feedback_embed('Invalid query.', False))


def setup(bot):
    """Add this cog to bot.

    :param discord.Client bot: bot to add cog to
    """
    bot.add_cog(ModSearch(bot))
