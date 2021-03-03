"""
AIONXM
======

Asynchronous Nexus Mods request handling.

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
import platform
import re

from urllib.parse import quote

from typing import Optional
from aiohttp import ClientSession


# Match Nexus Mods game name in HTML
GAME_NAME_RE = re.compile(r":: (?P<game_name>.*?)\"")
# Match Nexus Mods game ID in HTML
GAME_ID_RE = re.compile(r"https://staticdelivery\.nexusmods\.com/Images/games/4_3/tile_(?P<game_id>[0-9]{1,4})")
# Match Nexus Mods profile icon in HTML
PROFILE_ICON_RE = re.compile(
    r"<img class=\"user-avatar\" src=\"(?P<profile_icon_url>https://(?:forums\.nexusmods\.com/uploads/profile/"
    r"(?:photo-(?:thumb-)?|av-)[0-9]*\.|secure\.gravatar\.com/avatar/)\w+)(?:\"|\?)"
)

# Leading/trailing characters to remove from Nexus Search queries
STRIP_RE = re.compile(r"^[^\w]+|[^\w]+$")
# Special patterns to replace with commas in Nexus Search queries
SPECIAL_RE = re.compile(r"[^\w]+")

API_BASE_URL = "https://api.nexusmods.com/v1/"
HTML_BASE_URL = "https://www.nexusmods.com/"


def parse_query(query: str) -> str:
    """Parse raw Nexus Mods search query to API query string format."""
    return SPECIAL_RE.sub(",", STRIP_RE.sub("", query.replace("'s", "")))


class NotFound(Exception):
    """Exception raised when requested data could not be found."""


class RequestHandler:
    """Asynchronous Nexus Mods web request handler."""

    __slots__ = ("session", "api_headers", "html_user_agent")

    def __init__(
        self,
        session: ClientSession,
        app_name: str,
        app_version: str,
        app_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """Initialise request handler."""
        self.session = session
        # https://help.nexusmods.com/article/114-api-acceptable-use-policy
        self.api_headers = {
            "Application-Version": app_version,
            "Application-Name": app_name,
            "User-Agent": (
                f"{app_name}/{app_version} ({platform.platform()}; {platform.architecture()[0]}"
                f"{f'; +{app_url}' if app_url else ''}) {platform.python_implementation()}/{platform.python_version()}"
            ),
            "Accept": "application/json",
        }

        if api_key is not None:
            self.api_headers["apikey"] = api_key

        self.html_user_agent = f"Mozilla/5.0 (compatible; {app_name}/{app_version}{f'; +{app_url}' if app_url else ''})"

    async def get_game(self, game_dir: str) -> dict:
        """Get JSON response with data about the game with the specified `game_dir` from the API."""
        async with self.session.get(
            f"{API_BASE_URL}games/{game_dir}.json", headers=self.api_headers, raise_for_status=True
        ) as res:
            return await res.json()

    async def get_all_games(self) -> dict:
        """Get JSON response with data from all games from B2 file host.

        No API key required, but less data and more frequent errors.
        """
        async with self.session.get(
            "https://data.nexusmods.com/file/nexus-data/games.json",
            raise_for_status=True,
        ) as res:
            return await res.json()

    async def get_games(self, include_unapproved: bool = False) -> dict:
        """Get JSON response with data from all games from the API."""
        async with self.session.get(
            f"{API_BASE_URL}games.json",
            params={"include_unapproved": str(include_unapproved).lower()},
            headers=self.api_headers,
            raise_for_status=True,
        ) as res:
            return await res.json()

    async def scrape_game_id_and_name(self, game_dir: str) -> tuple[int, str]:
        """Scrape game ID and name from HTML."""
        async with self.session.get(
            f"{HTML_BASE_URL}{quote(game_dir)}",
            headers={"User-Agent": self.html_user_agent, "Accept": "text/html"},
            raise_for_status=True,
        ) as res:
            content = (await res.content.read(700)).decode("utf-8")
            id_match, name_match = GAME_ID_RE.search(content), GAME_NAME_RE.search(content)
            if id_match is not None and name_match is not None:
                return int(id_match.group("game_id")), name_match.group("game_name")

        raise NotFound(f"Game info could not be scraped for {repr(game_dir)}.")

    async def scrape_profile_icon_url(self, user_id: int) -> str:
        """Scrape profile icon URL for the user with the specified `user_id`."""
        async with self.session.get(
            f"{HTML_BASE_URL}users/{quote(str(user_id))}",
            headers={"User-Agent": self.html_user_agent, "Accept": "text/html"},
            raise_for_status=True,
        ) as res:
            try:
                # icon URL usually appears in the 30k bytes after the first 70k bytes of HTML
                await res.content.readexactly(70000)
                if match := PROFILE_ICON_RE.search((await res.content.read(30000)).decode("utf-8")):
                    return match.group("profile_icon_url")
            except asyncio.IncompleteReadError:
                pass
            # if it does not, search the full web page
            if match := PROFILE_ICON_RE.search(await res.text("utf-8")):
                return match.group("profile_icon_url")

        raise NotFound(f"Profile icon URL for user ID {user_id} could not be scraped.")

    async def search_mods(
        self, query: str, game_id: int, include_adult: bool = False, timeout: int = 15000, **params
    ) -> dict:
        """Search Nexus Mods and return JSON response."""
        async with self.session.get(
            "https://search.nexusmods.com/mods",
            params={
                "terms": parse_query(query),
                "game_id": game_id,
                "include_adult": str(include_adult).lower(),
                "timeout": timeout,
                **params,
            },
            headers={"User-Agent": self.html_user_agent, "Accept": "application/json"},
            raise_for_status=True,
        ) as res:
            return await res.json()
