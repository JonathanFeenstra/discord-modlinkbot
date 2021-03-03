"""
ModSearch
=========

Cog for searching Nexus Mods.

Functionality based on:
-  u/modlinkbot for Reddit:
  https://www.reddit.com/r/modlinkbotsub/comments/dlp7d1/bot_operation_and_information/
- Nexus Mods Discord Bot quicksearch:
  https://github.com/Nexus-Mods/discord-bot/

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
import asyncio
import re
import time
from html import unescape
from urllib.parse import quote

import discord
from aiohttp import ClientResponse, ClientResponseError
from discord.ext import commands

from aionxm import parse_query, NotFound

# Match text {between braces} excluding specific characters (";:=*%$&_<>?`[])
SEARCH_QUERIES_RE = re.compile(r"{([^\";:=\*%\$&_<>\?`\[\]]*?)}", re.DOTALL)
# Match Discord markdown: https://support.discord.com/hc/en-us/articles/210298617
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
        r"|\|\|.*?\|\|"  # ||spoiler||
    ),
    re.DOTALL | re.MULTILINE,
)
# Whitespace to replace with single spaces in embeds
WHITESPACE_RE = re.compile(r"\s+")

# Nexus Mods global search results format string
NEXUS_GLOBAL_SEARCH = (
    "[Results for all games](https://www.nexusmods.com/search/?gsearch={0}&gsearchtype=mods) | "
    "[DuckDuckGo Search](https://duckduckgo.com/?q={0})"
)


def find_queries(text: str) -> list:
    """Find unique Nexus Mods search queries in plain text."""
    return list(
        dict.fromkeys(
            query.strip()
            for query_text in SEARCH_QUERIES_RE.findall(MARKDOWN_RE.sub("?", text))
            for query in query_text.split(",")
            if 3 <= len(parse_query(query)) <= 120
        )
    )


def add_result_field(embed: discord.Embed, game_name: str, response: ClientResponse):
    """Add search result field to embed."""
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


def add_response_error_field(embed: discord.Embed, error: ClientResponseError, query: str, game_name: str):
    """Add field to embed for when a `ClientResponseError` occurs."""
    embed.add_field(
        name=game_name,
        value=f"[`Error {error.status}: {error.message}`]({error.request_info.real_url}) | "
        + NEXUS_GLOBAL_SEARCH.format(quote(query)),
        inline=False,
    )


def add_no_results_field(embed: discord.Embed, query: str):
    """Add field to embed for when there are no search results."""
    embed.add_field(name="No results.", value=NEXUS_GLOBAL_SEARCH.format(quote(query)), inline=False)


def embed_response_error(embed: discord.Embed, error: ClientResponseError, query: str, game_name: str):
    """Display response error info in embed."""
    embed.title = f"`Error {error.status}: {error.message}`"
    embed.url = str(error.request_info.real_url)
    embed._author["name"] += f" | {game_name}"
    embed.description = (
        f"Error while searching for **{repr(WHITESPACE_RE.sub(' ', query))}** | {NEXUS_GLOBAL_SEARCH.format(query)}"
    )


class ModSearch(commands.Cog):
    """Cog for searching Nexus Mods."""

    def __init__(self, bot):
        """Initialise cog."""
        self.bot = bot
        self.nexus_search = self.bot.nxm_request_handler.search_mods

    async def _add_delete_reaction(self, ctx, messages):
        """Add reaction that allows the user to delete search result messages."""
        last_msg = messages[-1]
        if (perms := ctx.channel.permissions_for(ctx.me)).add_reactions and perms.manage_messages:
            await last_msg.add_reaction("🗑️")
            try:
                await self.bot.wait_for(
                    "reaction_add",
                    timeout=10.0,
                    check=lambda reaction, user: user == ctx.author and reaction.emoji == "🗑️",
                )
            except asyncio.TimeoutError:
                await last_msg.remove_reaction("🗑️", self.bot.user)
            else:
                for msg in messages:
                    await msg.delete()

    async def _get_nsfw_flag(self, ctx) -> int:
        """Determine whether NSFW mods should be included in the search (0=no; 1=yes, but hide NSFW thumbnails; 2=yes)."""
        async with self.bot.db_connect() as con:
            async with con.execute("SELECT nsfw FROM guild WHERE guild_id = ?", (ctx.guild.id,)) as cur:
                return {0: 0, 1: 1 + ctx.channel.is_nsfw(), 2: 2 * ctx.channel.is_nsfw()}[(await cur.fetchone())[0]]

    async def _get_games(self, ctx) -> list:
        """Get games to search for in the given guild message context."""
        async with self.bot.db_connect() as con:
            return await con.execute_fetchall(
                """SELECT g.game_id, g.name
                   FROM search_task s, game g
                   ON s.game_id = g.game_id
                   WHERE channel_id = ?""",
                (ctx.channel.id,),
            ) or await con.execute_fetchall(
                """SELECT g.game_id, g.name
                   FROM search_task s, game g
                   ON s.game_id = g.game_id
                   WHERE guild_id = ? AND channel_id = 0""",
                (ctx.guild.id,),
            )

    async def _embed_single_result(self, embed, query, game_name, response, nsfw_flag):
        """"Fill Discord embed with single mod search result from `query`."""
        mod = response["results"][0]
        try:
            author_icon_url = await self.bot.nxm_request_handler.scrape_profile_icon_url(author_id := mod["user_id"])
        except (ClientResponseError, NotFound):
            author_icon_url = "https://www.nexusmods.com/assets/images/default/avatar.png"
        embed.set_author(
            name=f"{mod['username']} | {game_name}",
            url=f"https://www.nexusmods.com/users/{author_id}",
            icon_url=author_icon_url,
        )
        if len(mod_name := unescape(mod["name"])) > 128:
            mod_name = f"{mod_name[:125]}..."
        embed.title = mod_name
        embed.url = f"https://nexusmods.com{mod['url']}"
        if (total := response["total"]) > 1:
            embed.description = (
                f"[All {total} results for **{repr(WHITESPACE_RE.sub(' ', query))}**]"
                f"(https://www.nexusmods.com/{mod['game_name']}/mods/?RH_ModList=include_adult:"
                f"{response['include_adult']},open:true,search_filename:"
                f"{'+'.join(response['terms'])}#permalink)"
            )
        if nsfw_flag in (0, 2) or not await self.check_if_nsfw(response):
            embed.set_thumbnail(url=f"https://staticdelivery.nexusmods.com{mod['image']}")

        embed.add_field(name="Downloads", value=f"{mod['downloads']:,}")
        embed.add_field(name="Endorsements", value=f"{mod['endorsements']:,}")

    async def _embed_multi_query_results(self, embed, queries, games, include_adult):
        """Embed search results of multiple queries."""
        for query in queries:
            embed.add_field(name="Search results for:", value=f"**{repr(WHITESPACE_RE.sub(' ', query))}**", inline=False)
            n_fields = len(embed.fields)
            for game_id, game_name in games:
                try:
                    if (response := await self.nexus_search(query, game_id, include_adult)).get("results"):
                        add_result_field(embed, game_name, response)
                except ClientResponseError as error:
                    add_response_error_field(embed, error, query, game_name)
            if len(embed.fields) == n_fields:
                add_no_results_field(embed, query)

    async def _embed_single_query_results(self, embed, query, games, nsfw_flag):
        """Embed search results of single query with multiple games."""
        responses = {}
        for game_id, game_name in games:
            try:
                if (response := await self.nexus_search(query, game_id, bool(nsfw_flag))).get("results"):
                    responses[game_name] = response
            except ClientResponseError as error:
                responses[game_name] = error
        if not responses:
            add_no_results_field(embed, query)
        elif len(responses) == 1:
            ((game_name, response),) = responses.items()
            if isinstance(response, ClientResponseError):
                embed_response_error(embed, response, query, game_name)
            else:
                await self._embed_single_result(embed, query, game_name, response, nsfw_flag)
        else:
            for game_name, response in responses.items():
                if isinstance(response, ClientResponseError):
                    add_response_error_field(embed, response, query, game_name)
                else:
                    add_result_field(embed, game_name, response)

    async def _embed_results(self, embed, queries, games, nsfw_flag):
        """Fill Discord embed with mod search results for the specified queries per game."""
        if len(queries) == 1:
            query = queries[0]
            if len(games) > 1:
                embed.title = f"Search results for: **{repr(WHITESPACE_RE.sub(' ', query))}**"
                await self._embed_single_query_results(embed, query, games, nsfw_flag)
            else:
                game_id, game_name = games[0]
                try:
                    response = await self.nexus_search(query, game_id, bool(nsfw_flag))
                except ClientResponseError as error:
                    embed_response_error(embed, error, query, game_name)
                if response.get("results"):
                    await self._embed_single_result(embed, query, game_name, response, nsfw_flag)
                else:
                    add_no_results_field(embed, query)
        else:
            await self._embed_multi_query_results(embed, queries, games, bool(nsfw_flag))

    async def check_if_nsfw(self, response) -> bool:
        """Check if `response` has an NSFW mod as first result."""
        mod = response["results"][0]
        try:
            check = await self.nexus_search(unescape(mod["name"]), mod["game_id"], False)
        except ClientResponseError:
            return True
        if check.get("results"):
            return check["results"][0]["mod_id"] != mod["mod_id"]
        return True

    async def send_nexus_results(self, ctx, queries, games):
        """Send Nexus Mods query results."""
        embed = discord.Embed(colour=14323253)
        embed.set_author(
            name="Nexus Mods",
            url="https://www.nexusmods.com/",
            icon_url="https://images.nexusmods.com/favicons/ReskinOrange/favicon-32x32.png",
        )

        if (n_queries := len(queries)) > (
            max_queries := getattr(self.bot.config, "max_result_embeds", 3) * (per_embed := 25 // (len(games) + 1))
        ):
            embed.description = f":x: Too many queries in message (max={max_queries})."
            return await ctx.send(embed=embed)

        result_messages = []
        for idx in range(0, n_queries, per_embed):
            embed.description = ":mag_right: Searching mods..."
            embed.clear_fields()
            result_messages.append(msg := await ctx.channel.send(embed=embed))
            embed.description = None
            start = time.perf_counter()
            await self._embed_results(embed, queries[idx : idx + per_embed], games, await self._get_nsfw_flag(ctx))
            embed.set_footer(
                text=f"Searched by @{ctx.author} | Total time: {round(time.perf_counter() - start, 2)} s",
                icon_url=ctx.author.avatar_url,
            )
            await msg.edit(embed=embed)
        await self._add_delete_reaction(ctx, result_messages)

    @commands.Cog.listener()
    async def on_message(self, msg):
        """Check for mod search queries in valid new messages and send results."""
        if not self.bot.validate_msg(msg) or not (queries := find_queries(msg.content)):
            return
        if (ctx := await self.bot.get_context(msg)).valid or not (games := await self._get_games(ctx)):
            return
        if not ctx.channel.permissions_for(ctx.me).embed_links:
            await ctx.send(":x: Searching mods requires 'Embed Links' permission.")
        else:
            await self.send_nexus_results(ctx, queries, games)

    @commands.command(aliases=["search", "modsearch"])
    @commands.has_permissions(embed_links=True)
    async def nexus(self, ctx, *, query_text: str):
        """Search for query on Nexus Mods."""
        if not (games := await self._get_games(ctx)):
            await ctx.send(":x: No search filters configured.")
        elif queries := find_queries(f"{{{query_text}}}"):
            await self.send_nexus_results(ctx, queries, games)
        else:
            await ctx.send(":x: Invalid query.")


def setup(bot):
    """Add this cog to bot."""
    bot.add_cog(ModSearch(bot))
