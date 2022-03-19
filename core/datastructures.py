"""
DataStructures
==============

Common data structures for modlinkbot.

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
from typing import NamedTuple


class Game(NamedTuple):
    """Nexus Mods game."""

    id: int
    path: str
    name: str


class PartialGame(NamedTuple):
    """Partial Nexus Mods game."""

    id: int
    name: str
