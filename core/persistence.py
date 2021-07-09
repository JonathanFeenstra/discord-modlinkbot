"""
Persistence
===========

Persistent data storage management for modlinkbot.

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
import sqlite3
from asyncio import Lock
from os import PathLike
from typing import Any, Iterable, Optional, Union

from aiosqlite import Connection
from aiosqlite.context import contextmanager
from aiosqlite.cursor import Cursor

from core.datastructures import Game, PartialGame


class AsyncDatabaseConnection(Connection):
    """Asynchronous SQLite database connection."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._lock = Lock()

    async def enable_foreign_keys(self) -> None:
        """Enable foreign key support."""
        await self.execute("PRAGMA foreign_keys = ON")

    @contextmanager
    async def executefile(self, file: Union[str, bytes, int]) -> Cursor:
        """Execute an SQL script from a file."""
        async with self._lock:
            with open(file) as script:
                return await self.executescript(script.read())

    @contextmanager
    async def execute_fetchone(self, sql: str, parameters: Iterable[Any] = None) -> Optional[sqlite3.Row]:
        """Helper to execute a query and return a single row."""
        if parameters is None:
            parameters = []
        cursor = await self.execute(sql, parameters)
        return await cursor.fetchone()


class GuildConnection(AsyncDatabaseConnection):
    """Database connection for managing guild data."""

    async def insert_guild(self, guild_id: int) -> None:
        """Insert guild with the specified ID into the database."""
        await self.execute("INSERT OR IGNORE INTO guild VALUES (?, '.', 1)", (guild_id,))

    async def set_guild_prefix(self, guild_id: int, prefix: str) -> None:
        """Set the prefix of the guild with the specified ID."""
        await self.execute("UPDATE guild SET prefix = ? WHERE guild_id = ?", (prefix, guild_id))

    async def set_guild_nsfw_flag(self, guild_id: int, nsfw: int) -> None:
        """Set the NSFW flag of the guild with the specified ID."""
        await self.execute("UPDATE guild SET nsfw = ? WHERE guild_id = ?", (nsfw, guild_id))

    async def fetch_guild_ids(self) -> Iterable[int]:
        """Fetch all guild IDs."""
        return (row[0] for row in await self.execute_fetchall("SELECT guild_id FROM guild"))

    async def fetch_guild_prefix(self, guild_id: int) -> Optional[str]:
        """Fetch the prefix of the guild with the specified ID."""
        if row := await self.execute_fetchone("SELECT prefix FROM guild WHERE guild_id = ?", (guild_id,)):
            return row[0]
        return None

    async def fetch_guild_nsfw_flag(self, guild_id: int) -> Optional[int]:
        """Fetch the NSFW flag of the guild with the specified ID."""
        if row := await self.execute_fetchone("SELECT nsfw FROM guild WHERE guild_id = ?", (guild_id,)):
            return row[0]
        return None

    async def delete_guild(self, guild_id: int) -> None:
        """Delete guild with the specified ID from the database."""
        await self.execute("DELETE FROM guild WHERE guild_id = ?", (guild_id,))

    async def filter_guilds(self, keep_guild_ids: tuple[int, ...]):
        """Delete guilds with the specified IDs from the database."""
        if (keep_amount := len(keep_guild_ids)) < 1000:
            await self.execute(f"DELETE FROM guild WHERE guild_id NOT IN ({', '.join('?' * keep_amount)})", keep_guild_ids)
        else:
            for i in range(0, keep_amount, 999):
                await self.filter_guilds(keep_guild_ids[i : i + 999])


class ChannelConnection(AsyncDatabaseConnection):
    """Database connection for managing channel data."""

    async def insert_channel(self, channel_id: int, guild_id: int) -> None:
        """Insert channel with the specified IDs into the database."""
        await self.execute("INSERT OR IGNORE INTO channel VALUES (?, ?)", (channel_id, guild_id))

    async def fetch_channels(self) -> Iterable[sqlite3.Row]:
        """Fetch channel IDs and their guild IDs."""
        return await self.execute_fetchall("SELECT * FROM channel")

    async def delete_channel(self, channel_id: int) -> None:
        """Delete channel with the specified ID."""
        await self.execute("DELETE FROM channel WHERE channel_id = ?", (channel_id,))


class GameAndSearchTaskConnection(AsyncDatabaseConnection):
    """Database connection for managing game and search task data."""

    async def insert_game(self, game: Game) -> None:
        """Insert game into the database."""
        await self.execute("INSERT OR IGNORE INTO game VALUES (?, ?, ?)", game)

    async def fetch_games(self) -> Iterable[Game]:
        """Fetch all games."""
        return [Game(*row) for row in await self.execute_fetchall("SELECT * FROM game")]

    async def insert_search_task(self, guild_id: int, channel_id: int, game_id: int) -> None:
        """Insert search task into the database."""
        await self.execute("INSERT OR IGNORE INTO search_task VALUES (?, ?, ?)", (guild_id, channel_id, game_id))

    async def fetch_search_task_count(self, guild_id: int, channel_id: int = 0) -> int:
        """Fetch search task count in the guild and channel with the specified IDs."""
        if row := await self.execute_fetchone(
            "SELECT COUNT (*) FROM search_task WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id)
        ):
            return row[0]
        return 0

    async def fetch_search_tasks_game_name_and_channel_id(self, guild_id: int, channel_id: int) -> Iterable[sqlite3.Row]:
        """Fetch game names and channel IDs of the search tasks in the specified guild and channel."""
        return await self.execute_fetchall(
            """SELECT name, channel_id
               FROM search_task s, game g
               ON s.game_id = g.game_id
               WHERE guild_id = ? AND channel_id IN (0, ?)""",
            (guild_id, channel_id),
        )

    async def fetch_guild_search_task_game_id_and_name(self, guild_id: int, game_path: str) -> Optional[PartialGame]:
        """Fetch game ID and name from a guild search task."""
        if row := await self.execute_fetchone(
            """SELECT s.game_id, g.name
               FROM search_task s, game g
               ON s.game_id = g.game_id
               WHERE guild_id = ? AND channel_id = 0 AND path = ?""",
            (guild_id, game_path),
        ):
            return PartialGame(*row)
        return None

    async def fetch_channel_search_task_game_id_and_name(self, channel_id: int, game_path: str) -> Optional[PartialGame]:
        """Fetch game IDs and names for search task in the specified channel."""
        if row := await self.execute_fetchone(
            """SELECT g.game_id, g.name
               FROM search_task s, game g
               ON s.game_id = g.game_id
               WHERE channel_id = ? AND path = ?""",
            (channel_id, game_path),
        ):
            return PartialGame(*row)
        return None

    async def fetch_guild_search_tasks_game_id_and_name(self, guild_id: int) -> Iterable[PartialGame]:
        """Fetch game IDs and names for search tasks in the specified guild."""
        return [
            PartialGame(*row)
            for row in await self.execute_fetchall(
                """SELECT g.game_id, g.name
               FROM search_task s, game g
               ON s.game_id = g.game_id
               WHERE guild_id = ? AND channel_id = 0""",
                (guild_id,),
            )
        ]

    async def fetch_channel_search_tasks_game_id_and_name(self, channel_id: int) -> Iterable[PartialGame]:
        """Fetch game IDs and names for search tasks in the specified channel."""
        return [
            PartialGame(*row)
            for row in await self.execute_fetchall(
                """SELECT g.game_id, g.name
               FROM search_task s, game g
               ON s.game_id = g.game_id
               WHERE channel_id = ?""",
                (channel_id,),
            )
        ]

    async def fetch_channel_has_any_search_tasks(self, channel_id: int) -> bool:
        """Check if the specified channel has any search tasks."""
        return bool(
            await self.execute_fetchone(
                "SELECT 1 FROM search_task WHERE channel_id = ?",
                (channel_id,),
            )
        )

    async def fetch_channel_has_any_other_search_tasks(self, channel_id: int, game_id: int) -> bool:
        """Check if the specified channel has any search tasks besides the specified game ID."""
        return bool(
            await self.execute_fetchone(
                "SELECT 1 FROM search_task WHERE channel_id = ? AND game_id != ?", (channel_id, game_id)
            )
        )

    async def fetch_channel_has_search_task(self, channel_id: int, game_path: str) -> bool:
        """Check if the specified channel has a search task with the specified game directory."""
        return bool(
            await self.execute_fetchone(
                "SELECT 1 FROM search_task s, game g ON s.game_id = g.game_id WHERE channel_id = ? AND path = ?",
                (channel_id, game_path),
            )
        )

    async def delete_search_task(self, guild_id: int, channel_id: int, game_id: int) -> None:
        """Delete the specified search task."""
        await self.execute(
            "DELETE FROM search_task WHERE guild_id = ? AND channel_id = ? AND game_id = ?", (guild_id, channel_id, game_id)
        )

    async def delete_channel_search_task(self, channel_id: int, game_id: int) -> None:
        """Delete channel search task for the specified game."""
        await self.execute("DELETE FROM search_task WHERE channel_id = ? AND game_id = ?", (channel_id, game_id))

    async def clear_guild_search_tasks(self, guild_id: int) -> None:
        """Delete all guild search tasks for the specified guild."""
        await self.execute("DELETE FROM search_task WHERE guild_id = ? AND channel_id = 0", (guild_id,))


class BlockedConnection(AsyncDatabaseConnection):
    """Database connection for managing blocked IDs."""

    async def insert_blocked_id(self, blocked_id: int) -> None:
        """Insert blocked ID into the database."""
        await self.execute("INSERT OR IGNORE INTO blocked VALUES (?)", (blocked_id,))

    async def fetch_blocked_ids(self) -> Iterable[int]:
        """Fetch all blocked IDs."""
        return (row[0] for row in await self.execute_fetchall("SELECT blocked_id FROM blocked"))

    async def delete_blocked_id(self, blocked_id: int) -> None:
        """Delete a blocked ID from the database."""
        await self.execute("DELETE FROM blocked WHERE blocked_id = ?", (blocked_id,))


class ModLinkBotConnection(
    GuildConnection,
    ChannelConnection,
    GameAndSearchTaskConnection,
    BlockedConnection,
):
    """modlinkbot's database connection."""

    async def __aenter__(self) -> "ModLinkBotConnection":
        con = await self
        await con.execute("PRAGMA journal_mode = WAL")
        return con


def connect(database: Union[str, bytes, PathLike], iter_chunk_size: int = 64) -> ModLinkBotConnection:
    """Connect to the database."""
    return ModLinkBotConnection(
        lambda: sqlite3.connect(database, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES),
        iter_chunk_size=iter_chunk_size,
    )
