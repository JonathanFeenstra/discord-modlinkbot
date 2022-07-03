"""
ModSearch
=========

Extension for searching Nexus Mods.

Functionality based on:
-  u/modlinkbot for Reddit:
  https://www.reddit.com/r/modlinkbotsub/comments/dlp7d1/bot_operation_and_information/
- Nexus Mods Discord Bot quicksearch:
  https://github.com/Nexus-Mods/discord-bot/

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
import re
from time import perf_counter
from typing import Any, Dict, List, NamedTuple, Optional, TypedDict, Union
from urllib.parse import quote

import discord
from aiohttp import ClientResponseError
from discord import app_commands
from discord.ext import commands

from bot import ModLinkBot
from core.aionxm import NotFound, parse_query
from core.constants import DEFAULT_COLOUR
from core.models import PartialGame

# Match text {between braces} excluding specific characters (";:=*%$&_<>?`[])
SEARCH_QUERIES_RE = re.compile(r"{([^\";:=\*%\$&_<>\?`\[\]{]*?)}", re.DOTALL)
# Match Discord markdown: https://support.discord.com/hc/en-us/articles/210298617
MARKDOWN_RE = re.compile(
    (
        r"```.*?```"  # ```multiline code```
        r"|`.*?`"  # `inline code`
        r"|^>\s.*?$"  # > quote
        r"|\*{3}.*?\*{3}"  # ***bold italics***
        r"|\*\*.*?\*\*"  # **bold**
        r"|\*(?!\s).*?(?<!\s)\*"  # *italics*
        r"|__.*?__"  # __underline__
        r"|~~.*?~~"  # ~~strikethrough~~
        r"|\|\|.*?\|\|"  # ||spoiler||
    ),
    re.DOTALL | re.MULTILINE,
)


def find_queries(text: str) -> List[str]:
    """Find unique Nexus Mods search queries in unformatted parts of text."""
    return list(
        dict.fromkeys(
            query.strip()
            for query_text in SEARCH_QUERIES_RE.findall(MARKDOWN_RE.sub("?", text))
            for query in query_text.split(",")
            if 3 <= len(parse_query(query)) <= 100
        )
    )


class SearchTask(TypedDict):
    """Nexus Mods search task."""

    queries: List[str]
    games: List[PartialGame]
    include_adult: bool
    hide_nsfw_thumbnails: bool


class SearchResult(NamedTuple):
    """Nexus Mods search result."""

    query: str
    game: PartialGame
    response: Union[Dict, ClientResponseError]


class ResultsEmbed(discord.Embed):
    """Discord embed with multiple Nexus Mods search results."""

    __slots__ = ("search_task",)

    GLOBAL_SEARCH_FORMAT = (
        "[Results for all games](https://www.nexusmods.com/search/?gsearch={0}&gsearchtype=mods) | "
        "[DuckDuckGo Search](https://duckduckgo.com/?q={0})"
    )
    WHITESPACE_RE = re.compile(r"\s+")

    def __init__(self, search_task: SearchTask, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_task = search_task
        self.set_author(
            name="Nexus Mods",
            url="https://www.nexusmods.com/",
            icon_url="https://images.nexusmods.com/favicons/ReskinOrange/favicon-32x32.png",
        )

    def display_single_result(self, result: SearchResult, author_icon_url: str, hide_thumbnail: bool) -> None:
        """Fill embed with single mod search result."""
        response: Dict = result.response  # type: ignore
        mod = response["results"][0]
        self.set_author(
            name=f"{mod['username']} | {result.game.name}",
            url=f"https://www.nexusmods.com/users/{mod['user_id']}",
            icon_url=author_icon_url,
        )
        if len(mod_name := mod["name"]) > 128:
            mod_name = f"{mod_name[:125]}..."
        self.title = mod_name
        self.url = f"https://nexusmods.com{mod['url']}"
        if (total := response["total"]) > 1:
            self.description = (
                f"[All {total:,} results for **{repr(self.WHITESPACE_RE.sub(' ', result.query))}**]"
                f"(https://www.nexusmods.com/{mod['game_name']}/mods/?RH_ModList=include_adult:"
                f"{response['include_adult']},open:true,search_filename:"
                f"{'+'.join(response['terms'])}#permalink)"
            )
        if not hide_thumbnail:
            self.set_thumbnail(url=f"https://staticdelivery.nexusmods.com{mod['image']}")

        self.add_field(name="Downloads", value=f"{mod['downloads']:,}")
        self.add_field(name="Endorsements", value=f"{mod['endorsements']:,}")

    def display_single_query_results(self, query_results: List[SearchResult]) -> None:
        """Fill embed with single query mod search results."""
        query = self.search_task["queries"][0]
        self._append_author_name(f"Search results for: {repr(self.WHITESPACE_RE.sub(' ', query))}")
        self._add_query_results(query, query_results)

    def _append_author_name(self, text: str) -> None:
        self._author["name"] = f"Nexus Mods | {text}"

    def add_result_fields(self, results: List[List[SearchResult]]) -> None:
        """Fill embed with multiple query mod search results."""
        queries_and_results = zip(self.search_task["queries"], results)
        if len(self.search_task["games"]) > 1:
            for query, query_results in queries_and_results:
                self.add_field(
                    name="Search results for:", value=f"**{repr(self.WHITESPACE_RE.sub(' ', query))}**", inline=False
                )
                self._add_query_results(query, query_results)
        else:
            self._append_author_name(self.search_task["games"][0][1])
            for query, query_results in queries_and_results:
                self._add_query_results(query, query_results, single_game=True)

    def _add_query_results(self, query: str, query_results: List[SearchResult], single_game: bool = False) -> None:
        if not query_results:
            self.add_no_results_field(query, f"No results for: {repr(query)}." if single_game else "No results.")
        else:
            for result in query_results:
                self.add_result_field(result, f"Results for: {repr(query)}" if single_game else None, not single_game)

    def add_result_field(self, result: SearchResult, name: Optional[str] = None, inline: bool = True) -> None:
        """Add search result field to embed."""
        if isinstance(response := result.response, ClientResponseError):
            return self.add_response_error_field(response, result.game.name, result.query)
        mod = response["results"][0]
        if len(mod_name := mod["name"]) > 128:
            mod_name = f"{mod_name[:125]}..."
        result_hyperlinks = f"[{mod_name}](https://nexusmods.com{mod['url']})"
        if (total := response["total"]) > 1:
            result_hyperlinks = (
                f"{result_hyperlinks} | [{total:,} results](https://www.nexusmods.com/{mod['game_name']}"
                f"/mods/?RH_ModList=include_adult:{response['include_adult']},"
                f"open:true,search_filename:{'+'.join(response['terms'])}#permalink)"
            )
        self.add_field(name=name or result.game.name, value=result_hyperlinks, inline=inline)

    def add_response_error_field(self, error: ClientResponseError, game_name: str, query: str) -> None:
        """Add field to embed with info about the result's error response."""
        self.add_field(
            name=game_name,
            value=f"[`Error {error.status}: {error.message}`]({error.request_info.real_url}) | "
            + self.GLOBAL_SEARCH_FORMAT.format(quote(query)),
            inline=False,
        )

    def add_no_results_field(self, query: str, name: str = "No results.") -> None:
        """Add field to embed for when there are no search results."""
        self.add_field(name=name, value=self.GLOBAL_SEARCH_FORMAT.format(quote(query)), inline=False)

    def display_response_error(self, error: ClientResponseError, game_name: str, query: str) -> None:
        """Display response error info in embed."""
        self.title = f"`Error {error.status}: {error.message}`"
        self.url = str(error.request_info.real_url)
        self._append_author_name(game_name)
        self.description = (
            f"Error while searching for **{repr(self.WHITESPACE_RE.sub(' ', query))}** "
            f"| {self.GLOBAL_SEARCH_FORMAT.format(quote(query))}"
        )

    def to_dict(self) -> Dict:
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

    DELETE_REACTION = "🗑️"

    def __init__(self, bot: ModLinkBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message) -> None:
        """Check for mod search queries in valid new message and send results."""
        if msg.author.bot or not self.bot.validate_msg(msg) or not (queries := find_queries(msg.content)):
            return
        if (ctx := await self.bot.get_context(msg)).valid or not (games := await self._get_games_to_search_for(ctx)):
            return
        permissions = ctx.channel.permissions_for(ctx.me)
        if not permissions.send_messages:
            return
        if not permissions.embed_links:
            await ctx.send(":x: Searching mods requires 'Embed Links' permission.")
        else:
            await self.send_nexus_results(ctx, queries, games)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        """Check for mod search queries when content of last message in channel is edited and send results."""
        if before.content != after.content and after == after.channel.last_message:
            await self.on_message(after)

    @commands.hybrid_command(aliases=["search", "modsearch"])
    @commands.has_permissions(embed_links=True)
    async def nexus(self, ctx: commands.Context, *, query_text: str, game_path: Optional[str] = None) -> None:
        """Search for query on Nexus Mods."""
        games = []
        if game_path is not None:
            async with self.bot.db_connect() as con:
                if (game := await con.fetch_partial_game(game_path)) is None:
                    await ctx.send(":x: Game not found.")
                    return
                games.append(game)
        if not games and not (games := await self._get_games_to_search_for(ctx)):
            await ctx.send(":x: No search filters configured.")
        elif queries := find_queries(f"{{{query_text}}}"):
            await self.send_nexus_results(ctx, queries, games)
        else:
            await ctx.send(":x: Invalid query.")

    @nexus.autocomplete("game_path")
    async def _game_path_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        current_lower = current.lower()
        async with self.bot.db_connect() as con:
            return [
                app_commands.Choice(name=game.name, value=game.path)
                for game in await con.fetch_games()
                if current_lower in game.name.lower() or current_lower in game.path or current_lower in str(game.id)
            ][:25]

    async def _get_games_to_search_for(self, ctx: commands.Context) -> List[PartialGame]:
        async with self.bot.db_connect() as con:
            return await con.fetch_channel_partial_games(ctx.channel.id) or await con.fetch_guild_partial_games(ctx.guild.id)

    async def send_nexus_results(
        self, ctx: commands.Context, queries: List[str], games: List[PartialGame]
    ) -> Optional[discord.Message]:
        """Send Nexus Mods results for the specified queries and games."""
        await ctx.typing()
        if len(queries) > (
            max_queries := getattr(self.bot.config, "max_messages_per_search", 3)
            * (queries_per_msg := 25 // (len(games) + 1))
        ):
            return await ctx.send(f":x: Too many queries in message (max={max_queries}).")
        nsfw_flag = await self._get_nsfw_flag(ctx.guild.id)
        nsfw_channel = ctx.channel.nsfw if isinstance(ctx.channel, discord.TextChannel) else ctx.channel.parent.nsfw
        include_adult = nsfw_flag == 1 or (nsfw_flag == 2 and nsfw_channel)
        search_task = SearchTask(
            queries=queries,
            games=games,
            include_adult=include_adult,
            hide_nsfw_thumbnails=include_adult and not nsfw_channel,
        )
        await self.distribute_results(ctx, search_task, queries_per_msg)

    async def _get_nsfw_flag(self, guild_id: int) -> int:
        async with self.bot.db_connect() as con:
            return await con.fetch_guild_nsfw_flag(guild_id)

    async def distribute_results(self, ctx: commands.Context, search_task: SearchTask, queries_per_msg: int):
        """Distribute search results per message."""
        result_messages = []
        all_queries = search_task["queries"]
        for i in range(0, len(all_queries), queries_per_msg):
            search_task["queries"] = all_queries[i : i + queries_per_msg]
            embed = ResultsEmbed(
                search_task,
                description=":mag_right: Searching mods...",
                colour=DEFAULT_COLOUR,
            )
            result_messages.append(msg := await ctx.send(embed=embed))
            await self._update_embed_with_results(embed, ctx.author)
            await msg.edit(embed=embed)
        await self._add_reaction_to_delete_messages(ctx, result_messages)

    async def _update_embed_with_results(self, embed: ResultsEmbed, searcher: Union[str, discord.User]) -> None:
        embed.description = None
        start_time = perf_counter()
        results = await self._collect_modsearch_results(embed.search_task)
        end_time = perf_counter()
        await self._embed_results(embed, results)
        embed.set_footer(text=f"Searched by @{searcher} | Took: {round(end_time - start_time, 2)} s")

    async def _collect_modsearch_results(self, search_task: SearchTask) -> List[List[SearchResult]]:
        results = []
        for query in search_task["queries"]:
            query_results = await self._search_mods_for_query(query, search_task["games"], search_task["include_adult"])
            results.append(query_results)
        return results

    async def _search_mods_for_query(self, query: str, games: List[PartialGame], include_adult: bool) -> List[SearchResult]:
        search_results = []
        for game in games:
            try:
                response = await self.bot.request_handler.search_mods(query, game.id, include_adult)
                if not response.get("results"):
                    continue
            except ClientResponseError as error:
                response = error
            search_results.append(SearchResult(query=query, game=game, response=response))
        return search_results

    async def _embed_results(self, embed: ResultsEmbed, results: List[List[SearchResult]]) -> None:
        if len(results) == 1:
            if len(query_results := results[0]) == 1:
                result = query_results[0]
                await self._embed_single_result(embed, result)
            else:
                embed.display_single_query_results(query_results)
        else:
            embed.add_result_fields(results)

    async def _embed_single_result(self, embed: ResultsEmbed, result: SearchResult) -> None:
        if isinstance(response := result.response, ClientResponseError):
            embed.display_response_error(response, result.game.name, result.query)
        elif not response.get("results"):
            embed.add_no_results_field(result.query)
        else:
            hide_thumbnail = embed.search_task["hide_nsfw_thumbnails"] and await self.check_if_nsfw(response)
            try:
                author_icon_url = await self.bot.request_handler.scrape_profile_icon_url(
                    result.response["results"][0]["user_id"]  # type: ignore
                )
            except (ClientResponseError, NotFound):
                author_icon_url = "https://www.nexusmods.com/assets/images/default/avatar.png"
            embed.display_single_result(result, author_icon_url, hide_thumbnail)

    async def check_if_nsfw(self, response: Dict) -> bool:
        """Check if `response` has an NSFW mod as first result."""
        mod = response["results"][0]
        try:
            check = await self.bot.request_handler.search_mods(mod["name"], mod["game_id"], False)
        except ClientResponseError:
            return True
        if check.get("results"):
            return check["results"][0]["mod_id"] != mod["mod_id"]
        return True

    async def _add_reaction_to_delete_messages(self, ctx: commands.Context, messages: List[discord.Message]) -> None:
        last_msg = messages[-1]
        if ctx.channel.permissions_for(ctx.me).add_reactions:
            await last_msg.add_reaction(self.DELETE_REACTION)
            try:
                await self.bot.wait_for(
                    "reaction_add",
                    timeout=10.0,
                    check=lambda reaction, user: user == ctx.author
                    and reaction.message == last_msg
                    and reaction.emoji == self.DELETE_REACTION,
                )
            except asyncio.TimeoutError:
                try:
                    await last_msg.remove_reaction(self.DELETE_REACTION, self.bot.user)
                except discord.NotFound:
                    pass
            else:
                for msg in messages:
                    try:
                        await msg.delete()
                    except discord.NotFound:
                        pass


async def setup(bot: ModLinkBot) -> None:
    await bot.add_cog(ModSearch(bot))
