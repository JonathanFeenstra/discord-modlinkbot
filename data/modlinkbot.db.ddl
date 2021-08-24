/* ModLinkBotDB
 * ============
 * 
 * SQLite database creation script for modlinkbot.
 *
 * Copyright (C) 2019-2021 Jonathan Feenstra
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 * 
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 * 
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */
PRAGMA foreign_keys = ON;
CREATE TABLE
IF NOT EXISTS guild (
    guild_id INTEGER NOT NULL PRIMARY KEY,
    prefix TEXT NOT NULL DEFAULT '.',
    nsfw INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE
IF NOT EXISTS channel (
    channel_id INTEGER NOT NULL PRIMARY KEY,
    guild_id INTEGER NOT NULL REFERENCES guild ON DELETE CASCADE
);
CREATE TABLE
IF NOT EXISTS game (
    game_id INTEGER NOT NULL PRIMARY KEY,
    path TEXT,
    name TEXT NOT NULL
);
CREATE TABLE
IF NOT EXISTS search_task (
    guild_id INTEGER NOT NULL REFERENCES guild ON DELETE CASCADE,
    channel_id INTEGER NOT NULL DEFAULT 0 REFERENCES channel ON DELETE CASCADE,
    game_id INTEGER NOT NULL REFERENCES game ON DELETE CASCADE,
    PRIMARY KEY(guild_id, channel_id, game_id)
);
CREATE TABLE
IF NOT EXISTS blocked (
    blocked_id INTEGER NOT NULL PRIMARY KEY
);

INSERT OR IGNORE INTO game VALUES(0, "all", "All games");