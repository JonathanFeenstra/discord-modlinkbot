"""
ModSearch
=========

Extension for searching Nexus Mods.

Functionality based on:
-  u/modlinkbot for Reddit:
  https://www.reddit.com/r/modlinkbotsub/comments/dlp7d1/bot_operation_and_information/
- Nexus Mods Discord Bot quicksearch:
  https://github.com/Nexus-Mods/discord-bot/

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
import asyncio
import re
from html import unescape
from time import perf_counter
from urllib.parse import quote

import discord
from aiohttp import ClientResponseError
from discord.ext import commands

from aionxm import NotFound, parse_query

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


def find_queries(text: str) -> list:
    """Find unique Nexus Mods search queries in unformatted parts of text."""
    return list(
        dict.fromkeys(
            query.strip()
            for query_text in SEARCH_QUERIES_RE.findall(MARKDOWN_RE.sub("?", text))
            for query in query_text.split(",")
            if 3 <= len(parse_query(query)) <= 100
        )
    )


class ResultsEmbed(discord.Embed):
    """Discord embed with multiple Nexus Mods search results."""

    __slots__ = ("search_task",)

    GLOBAL_SEARCH_FORMAT = (
        "[Results for all games](https://www.nexusmods.com/search/?gsearch={0}&gsearchtype=mods) | "
        "[DuckDuckGo Search](https://duckduckgo.com/?q={0})"
    )
    WHITESPACE_RE = re.compile(r"\s+")

    def __init__(self, **kwargs):
        kwargs["colour"] = kwargs.get("colour", 14323253)
        super().__init__(**kwargs)
        self.search_task = kwargs.get("search_task", {})
        self.set_author(
            name="Nexus Mods",
            url="https://www.nexusmods.com/",
            icon_url="https://images.nexusmods.com/favicons/ReskinOrange/favicon-32x32.png",
        )

    def display_single_result(self, result: dict, author_icon_url: str, hide_thumbnail: bool):
        """Fill embed with single mod search result."""
        mod = result["mod"]
        self.set_author(
            name=f"{mod['username']} | {result['game_name']}",
            url=f"https://www.nexusmods.com/users/{mod['user_id']}",
            icon_url=author_icon_url,
        )
        if len(mod_name := unescape(mod["name"])) > 128:
            mod_name = f"{mod_name[:125]}..."
        self.title = mod_name
        self.url = f"https://nexusmods.com{mod['url']}"
        response = result["response"]
        if (total := response["total"]) > 1:
            self.description = (
                f"[All {total:,} results for **{repr(self.WHITESPACE_RE.sub(' ', result['query']))}**]"
                f"(https://www.nexusmods.com/{mod['game_name']}/mods/?RH_ModList=include_adult:"
                f"{response['include_adult']},open:true,search_filename:"
                f"{'+'.join(response['terms'])}#permalink)"
            )
        if not hide_thumbnail:
            self.set_thumbnail(url=f"https://staticdelivery.nexusmods.com{mod['image']}")

        self.add_field(name="Downloads", value=f"{mod['downloads']:,}")
        self.add_field(name="Endorsements", value=f"{mod['endorsements']:,}")

    def display_single_query_results(self, query_results: list):
        """Fill embed with single query mod search results."""
        query = self.search_task["queries"][0]
        self.title = f"Search results for: **{repr(self.WHITESPACE_RE.sub(' ', query))}**"
        self._add_query_results(query, query_results)

    def add_result_fields(self, results):
        """Fill embed with multiple query mod search results."""
        queries_and_results = zip(self.search_task["queries"], results)
        if len(self.search_task["games"]) > 1:
            for query, query_results in queries_and_results:
                self.add_field(
                    name="Search results for:", value=f"**{repr(self.WHITESPACE_RE.sub(' ', query))}**", inline=False
                )
                self._add_query_results(query, query_results)
        else:
            self._author["name"] += f" | {self.search_task['games'][0][1]}"
            for query, query_results in queries_and_results:
                self._add_query_results(query, query_results, f"Results for: {repr(query)}")

    def _add_query_results(self, query: str, query_results: dict, field_name=None):
        if not query_results:
            self.add_no_results_field(query)
        else:
            for result in query_results:
                self.add_result_field(result, field_name)

    def add_result_field(self, result: dict, name=None):
        """Add search result field to embed."""
        response, mod = result["response"], result["mod"]
        if isinstance(response, ClientResponseError):
            return self.add_response_error_field(result)
        if len(mod_name := unescape(mod["name"])) > 128:
            mod_name = f"{mod_name[:125]}..."
        result_hyperlinks = f"[{mod_name}](https://nexusmods.com{mod['url']})"
        if (total := response["total"]) > 1:
            result_hyperlinks = (
                f"{result_hyperlinks} | [{total:,} results](https://www.nexusmods.com/{mod['game_name']}"
                f"/mods/?RH_ModList=include_adult:{response['include_adult']},"
                f"open:true,search_filename:{'+'.join(response['terms'])}#permalink)"
            )
        self.add_field(name=name or result["game_name"], value=result_hyperlinks)

    def add_response_error_field(self, result: dict):
        """Add field to embed with info about the result's error response."""
        error = result["response"]
        self.add_field(
            name=result["game_name"],
            value=f"[`Error {error.status}: {error.message}`]({error.request_info.real_url}) | "
            + self.GLOBAL_SEARCH_FORMAT.format(quote(result["query"])),
            inline=False,
        )

    def add_no_results_field(self, query: str):
        """Add field to embed for when there are no search results."""
        self.add_field(name="No results.", value=self.GLOBAL_SEARCH_FORMAT.format(quote(query)), inline=False)

    def display_response_error(self, result: dict):
        """Display response error info in embed."""
        error = result["response"]
        self.title = f"`Error {error.status}: {error.message}`"
        self.url = str(error.request_info.real_url)
        self._author["name"] += f" | {result['game_name']}"
        self.description = (
            f"Error while searching for **{repr(self.WHITESPACE_RE.sub(' ', result['query']))}** "
            f"| {self.GLOBAL_SEARCH_FORMAT.format(result['query'])}"
        )

    def to_dict(self):
        """Converts this embed object into a dict. Overridden from `discord.Embed` to use `super().__slots__`."""
        result = {key[1:]: getattr(self, key) for key in super().__slots__ if key[0] == "_" and hasattr(self, key)}

        try:
            colour = result.pop("colour")
        except KeyError:
            pass
        else:
            if colour:
                result["color"] = colour.value

        result.update(super().to_dict())
        return result


class ModSearch(commands.Cog):
    """Cog for searching Nexus Mods."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, msg):
        """Check for mod search queries in valid new message and send results."""
        if not self.bot.validate_msg(msg) or not (queries := find_queries(msg.content)):
            return
        if (ctx := await self.bot.get_context(msg)).valid or not (games := await self._get_games_to_search_for(ctx)):
            return
        if not ctx.channel.permissions_for(ctx.me).embed_links:
            await ctx.send(":x: Searching mods requires 'Embed Links' permission.")
        else:
            await self.send_nexus_results(ctx, queries, games)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Check for mod search queries when content of last message in channel is edited and send results."""
        if before.content != after.content and after == after.channel.last_message:
            await self.on_message(after)

    @commands.command(aliases=["search", "modsearch"])
    @commands.has_permissions(embed_links=True)
    async def nexus(self, ctx, *, query_text: str):
        """Search for query on Nexus Mods."""
        if not (games := await self._get_games_to_search_for(ctx)):
            await ctx.send(":x: No search filters configured.")
        elif queries := find_queries(f"{{{query_text}}}"):
            await self.send_nexus_results(ctx, queries, games)
        else:
            await ctx.send(":x: Invalid query.")

    async def _get_games_to_search_for(self, ctx) -> list:
        async with self.bot.db_connect() as con:
            return await con.fetch_channel_search_tasks_game_id_and_name(
                ctx.channel.id
            ) or await con.fetch_guild_search_tasks_game_id_and_name(ctx.guild.id)

    async def send_nexus_results(self, ctx, queries, games):
        """Send Nexus Mods results for the specified queries and games."""
        await ctx.trigger_typing()
        if len(queries) > (
            max_queries := getattr(self.bot.config, "max_messages_per_search", 3)
            * (queries_per_msg := 25 // (len(games) + 1))
        ):
            return await ctx.send(f":x: Too many queries in message (max={max_queries}).")
        nsfw_flag = await self._get_nsfw_flag(ctx.guild.id)
        include_adult = nsfw_flag == 1 or (nsfw_flag == 2 and ctx.channel.nsfw)
        search_task = {
            "queries": queries,
            "games": games,
            "include_adult": include_adult,
            "hide_nsfw_thumbnails": include_adult and not ctx.channel.nsfw,
        }
        await self.distribute_results(ctx, search_task, queries_per_msg)

    async def _get_nsfw_flag(self, guild_id: int) -> int:
        async with self.bot.db_connect() as con:
            return await con.fetch_guild_nsfw_flag(guild_id)

    async def distribute_results(self, ctx, search_task: dict, queries_per_msg: int):
        """Distribute search results per message."""
        result_messages = []
        all_queries = search_task["queries"]
        for i in range(0, len(all_queries), queries_per_msg):
            search_task["queries"] = all_queries[i : i + queries_per_msg]
            embed = ResultsEmbed(description=":mag_right: Searching mods...", search_task=search_task)
            result_messages.append(msg := await ctx.channel.send(embed=embed))
            await self._update_embed_with_results(embed, ctx.author)
            await msg.edit(embed=embed)
        await self._add_reaction_to_delete_messages(ctx, result_messages)

    async def _update_embed_with_results(self, embed: ResultsEmbed, searcher):
        embed.description = discord.Embed.Empty
        start_time = perf_counter()
        results = await self._collect_modsearch_results(embed.search_task)
        end_time = perf_counter()
        await self._embed_results(embed, results)
        embed.set_footer(text=f"Searched by @{searcher} | Took: {round(end_time - start_time, 2)} s")

    async def _collect_modsearch_results(self, search_task: dict) -> list[list]:
        results = []
        for query in search_task["queries"]:
            query_results = await self._search_mods_for_query(query, search_task["games"], search_task["include_adult"])
            results.append(query_results)
        return results

    async def _search_mods_for_query(self, query: str, games, include_adult: bool) -> list[dict]:
        search_results = []
        for game_id, game_name in games:
            result = {"query": query, "game_id": game_id, "game_name": game_name}
            try:
                response = await self.bot.request_handler.search_mods(query, game_id, include_adult)
                if mods := response.get("results"):
                    result["response"] = response
                    result["mod"] = mods[0]
                else:
                    continue
            except ClientResponseError as error:
                result["response"] = error
            search_results.append(result)
        return search_results

    async def _embed_results(self, embed: ResultsEmbed, results):
        if len(results) == 1:
            if len(query_results := results[0]) == 1:
                result = query_results[0]
                await self._embed_single_result(embed, result)
            else:
                embed.display_single_query_results(query_results)
        else:
            embed.add_result_fields(results)

    async def _embed_single_result(self, embed: ResultsEmbed, result: dict):
        if isinstance(response := result["response"], ClientResponseError):
            embed.display_response_error(result)
        elif not response.get("results"):
            embed.add_no_results_field(result["query"])
        else:
            hide_thumbnail = embed.search_task["hide_nsfw_thumbnails"] and await self.check_if_nsfw(response)
            try:
                author_icon_url = await self.bot.request_handler.scrape_profile_icon_url(result["mod"]["user_id"])
            except (ClientResponseError, NotFound):
                author_icon_url = "https://www.nexusmods.com/assets/images/default/avatar.png"
            embed.display_single_result(result, author_icon_url, hide_thumbnail)

    async def check_if_nsfw(self, response) -> bool:
        """Check if `response` has an NSFW mod as first result."""
        mod = response["results"][0]
        try:
            check = await self.bot.request_handler.search_mods(unescape(mod["name"]), mod["game_id"], False)
        except ClientResponseError:
            return True
        if check.get("results"):
            return check["results"][0]["mod_id"] != mod["mod_id"]
        return True

    async def _add_reaction_to_delete_messages(self, ctx, messages):
        last_msg = messages[-1]
        if ctx.channel.permissions_for(ctx.me).add_reactions:
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


def setup(bot):
    bot.add_cog(ModSearch(bot))
