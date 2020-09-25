"""
DB_Service
==========

Database service for modlinkbot.

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
from sqlite3 import PARSE_COLNAMES, PARSE_DECLTYPES

from aiosqlite import connect


class DBService:
    """modlinkbot database service."""

    @classmethod
    async def create(cls):
        """"Factory method to create a database service."""
        self = DBService()
        self.conn = await connect('modlinkbot.db', detect_types=PARSE_DECLTYPES | PARSE_COLNAMES)
        self.c = await self.conn.cursor()

        await self.c.execute("""
            CREATE TABLE
            IF NOT EXISTS guild (
                id INTEGER NOT NULL PRIMARY KEY,
                prefix TEXT DEFAULT '.' NOT NULL,
                inviter_name TEXT DEFAULT 'Unknown' NOT NULL,
                inviter_id INTEGER DEFAULT 404 NOT NULL,
                joined_at TIMESTAMP NOT NULL
            )
        """)
        await self.c.execute("""
            CREATE TABLE
            IF NOT EXISTS channel (
                id INTEGER NOT NULL PRIMARY KEY,
                guild_id INTEGER NOT NULL REFERENCES guild ON DELETE CASCADE
            )
        """)
        await self.c.execute("""
            CREATE TABLE
            IF NOT EXISTS game (
                name TEXT NOT NULL,
                filter TEXT,
                guild_id INTEGER NOT NULL REFERENCES guild ON DELETE CASCADE,
                channel_id INTEGER REFERENCES channel ON DELETE CASCADE
            )
        """)
        await self.c.execute("""
            CREATE TABLE
            IF NOT EXISTS blocked (
                id INTEGER NOT NULL PRIMARY KEY
            )
        """)
        await self.c.execute("""
            CREATE TABLE
            IF NOT EXISTS admin (
                id INTEGER NOT NULL PRIMARY KEY
            )
        """)
        return self

    async def execute(self, sql: str, *args):
        """"Wraps `self.c.execute`.

        :param str sql: SQL to execute
        """
        return await self.c.execute(sql, *args)

    async def commit(self):
        """Wraps `self.conn.commit`."""
        return await self.conn.commit()
