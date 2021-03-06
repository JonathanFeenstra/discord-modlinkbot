"""
ModSearch
=========

Cog for searching Nexus Mods.

Functionality based on:
-  u/modlinkbot for Reddit:
  https://www.reddit.com/r/modlinkbotsub/comments/dlp7d1/bot_operation_and_information/
- Nexus Mods Discord Bot quicksearch:
  https://github.com/Nexus-Mods/discord-bot/

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
import asyncio
import re
import time
from html import unescape
from urllib.parse import quote

import discord
from aiohttp import ClientResponseError
from discord.ext import commands

# Match Discord markdown, see: https://support.discord.com/hc/en-us/articles/210298617
MARKDOWN_RE = re.compile(
    (
        r"```.*?```"  # ```multiline code```
        r"|`.*?`"  # `inline code`
        r"|^>\s.*?$"  # > quote
        r"|\*{3}(?!\s).*?(?<!\s)\*{3}"  # ***bold italics***
        r"|\*\*(?!\s).*?(?<!\s)\*\*"  # **bold**
        r"|\*(?!\s).*?(?<!\s)\*"  # *italics*
        r"|__.*?__"  # __underline__
        r"|~~.*?~~"  # ~~strikethrough~~
        r"|\|\|.*?\|\|"
    ),  # ||spoiler||
    re.DOTALL | re.MULTILINE,
)
# Match text {between braces} excluding specific characters (";:=*%$&_<>?`[])
NEXUS_SEARCH_QUERIES_RE = re.compile(r"{([^\";:=\*%\$&_<>\?`\[\]]*?)}", re.DOTALL)
# Leading/trailing characters to remove from Nexus Search queries
STRIP_RE = re.compile(r"^[^\w]+|[^\w]+$")
# Special patterns to replace with commas in Nexus Search queries
SPECIAL_RE = re.compile(r"[^\w]+")
# Whitespace to replace with single spaces in embeds
WHITESPACE_RE = re.compile(r"\s+")

# Nexus Mods global search results string
NEXUS_GLOBAL_SEARCH = (
    "[Results for all games](https://www.nexusmods.com/search/?gsearch={0}&gsearchtype=mods) | "
    "[DuckDuckGo Search](https://duckduckgo.com/?q={0})"
)
# Nexus Mods profile icon URL types
NEXUS_ICON_URLS = (
    "https://forums.nexusmods.com/uploads/profile/photo-thumb-{0}.jpg",
    "https://forums.nexusmods.com/uploads/profile/photo-{0}.jpg",
    "https://forums.nexusmods.com/uploads/av-{0}.jpg",
    "https://forums.nexusmods.com/uploads/profile/photo-thumb-{0}.png",
    "https://forums.nexusmods.com/uploads/profile/photo-{0}.png",
    "https://forums.nexusmods.com/uploads/av-{0}.png",
)
# Headers to use when making requests to nexusmods.com
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse_query(query: str):
    """Parse Nexus Mods search query."""
    return SPECIAL_RE.sub(",", STRIP_RE.sub("", query.replace("'s", "")))


def find_queries(text: str):
    """Find unique Nexus Mods search queries in plain text."""
    return list(
        dict.fromkeys(
            query.strip()
            for query_text in NEXUS_SEARCH_QUERIES_RE.findall(MARKDOWN_RE.sub("?", text))
            for query in query_text.split(",")
            if 3 <= len(parse_query(query)) <= 120
        )
    )


class ModSearch(commands.Cog):
    """Cog for searching Nexus Mods."""

    def __init__(self, bot):
        """Initialise cog."""
        self.bot = bot

    async def _get_icon_url(self, author_id, urls):
        """Recursively try to retrieve an author's Nexus Mods icon URL and return when succesful."""
        async with self.bot.session.get(icon_url := urls.pop().format(author_id), headers=REQUEST_HEADERS) as res:
            if res.status != 200:
                if urls:
                    return await self._get_icon_url(author_id, urls)
                return "https://www.nexusmods.com/assets/images/default/avatar.png"
        return icon_url

    async def _add_result_field(self, embed, game_name, response):
        """Add search result field to `embed`."""
        if response is None:
            return
        if isinstance(response, Exception):
            return embed.add_field(
                name=game_name,
                value=(
                    f"[`Error {response.status}: {response.message}`]({response.request_info.real_url})\n[Server Status]"
                    "(https://www.isitdownrightnow.com/nexusmods.com.html) | "
                    if isinstance(response, ClientResponseError)
                    else f"`{response.__class__.__name__}: {response}`\n"
                )
                + NEXUS_GLOBAL_SEARCH.format(quote(response.query)),
                inline=False,
            )
        if len(mod_name := unescape((mod := response["results"][0])["name"])) > 128:
            mod_name = f"{mod_name[:125]}..."
        search_result = f"[{mod_name}](https://nexusmods.com{mod['url']})"
        if (total := response["total"]) > 1:
            search_result = (
                f"{search_result} | [{total} results](https://www.nexusmods.com/{mod['game_name']}"
                f"/mods/?RH_ModList=include_adult:{response['include_adult']},"
                f"open:true,search_filename:{'+'.join(response['terms'])}#permalink)"
            )
        embed.add_field(name=game_name, value=search_result)

    async def _embed_single_result(self, embed, game_name, response, nsfw_channel=False):
        """"Fill Discord embed with single mod search result from `query`."""
        if isinstance(response, Exception):
            if isinstance(response, ClientResponseError):
                embed.title = f"`Error {response.status}: {response.message}`"
                embed.url = str(response.request_info.real_url)
            else:
                embed.title = f"`{response.__class__.__name__}: {response}`"
            embed._author["name"] += f" | {game_name}"
            embed.description = (
                f"Error while searching for **{repr(WHITESPACE_RE.sub(' ', response.query))}**.\n"
                "[Server Status](https://www.isitdownrightnow.com/nexusmods.com.html) | "
                + NEXUS_GLOBAL_SEARCH.format(response.query)
            )
            return
        icon_url = await self._get_icon_url(author_id := (mod := response["results"][0])["user_id"], list(NEXUS_ICON_URLS))
        embed.set_author(
            name=f"{mod['username']} | {game_name}", url=f"https://www.nexusmods.com/users/{author_id}", icon_url=icon_url
        )
        if len(mod_name := unescape(mod["name"])) > 128:
            mod_name = f"{mod_name[:125]}..."
        embed.title = mod_name
        embed.url = f"https://nexusmods.com{mod['url']}"
        if (total := response["total"]) > 1:
            embed.description = (
                f"[All {total} results for **{repr(WHITESPACE_RE.sub(' ', response['query']))}**]"
                f"(https://www.nexusmods.com/{mod['game_name']}/mods/?RH_ModList=include_adult:"
                f"{response['include_adult']},open:true,search_filename:"
                f"{'+'.join(response['terms'])}#permalink)"
            )
        if nsfw_channel or not response["include_adult"] or not await self.check_if_nsfw(response):
            embed.set_thumbnail(url=f"https://staticdelivery.nexusmods.com{mod['image']}")

        embed.add_field(name="Downloads", value=f"{mod['downloads']:,}")
        embed.add_field(name="Endorsements", value=f"{mod['endorsements']:,}")

    async def _embed_query_results(self, embed, queries, game_filters, nsfw_channel=False):
        """Fill Discord embed with mod search results from `queries`."""
        if len(queries) == 1:
            query = queries[0]
            if len(game_filters) > 1:
                responses = dict()
                for game_name, game_filter in game_filters.items():
                    responses[game_name] = await self.nexus_search(query, game_filter)
                if not responses:
                    embed.add_field(name="No results.", value=NEXUS_GLOBAL_SEARCH.format(quote(query)), inline=False)
                elif len(responses) == 1:
                    await self._embed_single_result(embed, *responses, *responses.values(), nsfw_channel)
                else:
                    embed.title = f"Search results for: **{repr(WHITESPACE_RE.sub(' ', query))}**"
                    for game_name, response in responses.items():
                        await self._add_result_field(embed, game_name, response)
            elif (response := await self.nexus_search(query, *game_filters.values())) is None:
                embed.add_field(name="No results.", value=NEXUS_GLOBAL_SEARCH.format(quote(query)), inline=False)
            else:
                await self._embed_single_result(embed, *game_filters, response, nsfw_channel)
        else:
            for query in queries:
                embed.add_field(name="Search results for:", value=f"**{repr(WHITESPACE_RE.sub(' ', query))}**", inline=False)
                n_fields = len(embed.fields)
                for game_name, game_filter in game_filters.items():
                    await self._add_result_field(embed, game_name, await self.nexus_search(query, game_filter))
                if len(embed.fields) == n_fields:
                    embed.add_field(name="No results.", value=NEXUS_GLOBAL_SEARCH.format(quote(query)), inline=False)

    async def nexus_search(self, query: str, game_filter: str):
        """Search Nexus Mods for `query` using `game_filter` and return JSON response."""
        try:
            async with self.bot.session.get(
                f"https://search.nexusmods.com/mods?terms={parse_query(query)}{game_filter}", headers=REQUEST_HEADERS
            ) as res:
                if res.status == 200:
                    if (res_json := await res.json()).get("results"):
                        res_json["query"] = query
                        return res_json
                else:
                    raise ClientResponseError(
                        request_info=res.request_info,
                        status=res.status,
                        message=res.reason,
                        headers=res.headers,
                        history=res.history,
                    )
        except Exception as error:
            error.query = query
            return error

    async def check_if_nsfw(self, response):
        """Check if `response` has an NSFW mod as first result."""
        if (
            check := await self.nexus_search(
                parse_query(unescape((mod := response["results"][0])["name"])),
                f"&game_id={mod['game_id']}&exclude_authors={','.join(response['exclude_authors'])}"
                f"&exclude_tags={','.join(response['exclude_tags'])}",
            )
        ) and not isinstance(check, Exception):
            return check["results"][0]["mod_id"] != mod["mod_id"]
        return True

    async def send_nexus_results(self, ctx, queries, game_filters):
        """Send Nexus Mods query results."""
        embed = discord.Embed(colour=14323253)
        embed.set_author(
            name="Nexus Mods",
            url="https://www.nexusmods.com/",
            icon_url="https://images.nexusmods.com/favicons/ReskinOrange/favicon-32x32.png",
        )

        if (n_queries := len(queries)) > (
            max_queries := getattr(self.bot.config, "max_result_embeds", 3) * (per_embed := 25 // (len(game_filters) + 1))
        ):
            embed.description = f":x: Too many queries in message (max={max_queries})."
            return await ctx.send(embed=embed)

        result_messages = []
        for idx in range(0, n_queries, per_embed):
            embed.description = ":mag_right: Searching mods..."
            embed.clear_fields()
            result_messages.append(result_msg := await ctx.channel.send(embed=embed))
            embed.description = None
            start = time.perf_counter()
            await self._embed_query_results(embed, queries[idx : idx + per_embed], game_filters, ctx.channel.is_nsfw())
            embed.set_footer(
                text=f"Searched by @{ctx.author} | Total time: {round(time.perf_counter() - start, 2)} s",
                icon_url=ctx.author.avatar_url,
            )
            await result_msg.edit(embed=embed)
        if (perms := ctx.channel.permissions_for(ctx.me)).add_reactions and perms.manage_messages:
            await result_msg.add_reaction("🗑️")
            try:
                await self.bot.wait_for(
                    "reaction_add",
                    timeout=10.0,
                    check=lambda reaction, user: user == ctx.author and reaction.emoji == "🗑️",
                )
            except asyncio.TimeoutError:
                await result_msg.remove_reaction("🗑️", self.bot.user)
            else:
                for msg in result_messages:
                    await msg.delete()

    @commands.Cog.listener()
    async def on_message(self, msg):
        """Check for mod search queries in valid new messages and send results."""
        if not self.bot.validate_msg(msg):
            return

        game_filters = (guild_config := self.bot.guild_configs[(ctx := await self.bot.get_context(msg)).guild.id])[
            "channels"
        ][ctx.channel.id] or guild_config["games"]

        if ctx.valid or not game_filters or not (queries := find_queries(msg.content)):
            return

        if not ctx.channel.permissions_for(ctx.me).embed_links:
            await ctx.send(":x: Searching mods requires 'Embed Links' permission.")
        else:
            await self.send_nexus_results(ctx, queries, game_filters)

    @commands.command(aliases=["nexussearch", "modsearch"])
    @commands.has_permissions(embed_links=True)
    async def nexus(self, ctx, *, query_text: str):
        """Search for query on Nexus Mods."""
        game_filters = (guild_config := self.bot.guild_configs[ctx.guild.id])["channels"][ctx.channel.id] or guild_config[
            "games"
        ]
        if not game_filters:
            return await ctx.send(":x: No search filters configured.")
        if queries := find_queries(f"{{{query_text}}}"):
            await self.send_nexus_results(ctx, queries, game_filters)
        else:
            await ctx.send(":x: Invalid query.")


def setup(bot):
    """Add this cog to bot."""
    bot.add_cog(ModSearch(bot))
