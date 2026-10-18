# Copyright (C) 2026 Evert van de Waal
#
# This file is part of archtool, the architecting tool.
#
# archtool is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# archtool is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with archtool. If not, see
# <https://www.gnu.org/licenses/>.

"""The structure of the meta-model file: `@table` sections, and `@rules`, `@style` and `@defs` sections.

This module only reads the structure. The meaning of the tables is interpreted
by archtool.metamodel.
"""

from dataclasses import dataclass, field
from pathlib import Path

from archtool.errors import FormatError
from archtool.formats.tables import Table, read_table, split_lines

_TEXT_SECTIONS = ("@rules", "@style", "@defs")


@dataclass(frozen=True, slots=True)
class TextSection:
    """The text between a section line and `@end`. `line` is the line of the first line of text."""

    text: str
    line: int


@dataclass(slots=True)
class MetaModelFile:
    path: str
    tables: dict[str, Table] = field(default_factory=dict)
    rules: list[TextSection] = field(default_factory=list)
    styles: list[TextSection] = field(default_factory=list)
    defs: list[TextSection] = field(default_factory=list)


def read_metamodel_file(text: str, path: Path | str) -> MetaModelFile:
    result = MetaModelFile(str(path))
    lines = split_lines(text, path)
    i = 0
    while i < len(lines):
        line = lines[i]
        number = i + 1
        if line == "" or line.startswith("#"):
            i += 1
        elif line.startswith("@table "):
            name = line[len("@table ") :]
            if name in result.tables:
                raise FormatError(path, number, 8, f"table '{name}' occurs more than once")
            end = i + 1
            while end < len(lines) and not lines[end].startswith("@"):
                end += 1
            numbered = [(n + 1, lines[n]) for n in range(i + 1, end) if not lines[n].startswith("#")]
            if not any(content for _, content in numbered):
                raise FormatError(path, number, 1, f"table '{name}' has no header")
            result.tables[name] = read_table(numbered, path)
            i = end
        elif line in _TEXT_SECTIONS:
            end = i + 1
            while end < len(lines) and lines[end] != "@end":
                end += 1
            if end == len(lines):
                raise FormatError(path, number, 1, f"'{line}' section without '@end'")
            section = TextSection("\n".join(lines[i + 1 : end]) + "\n", number + 1)
            {"@rules": result.rules, "@style": result.styles, "@defs": result.defs}[line].append(section)
            i = end + 1
        else:
            raise FormatError(path, number, 1, "expected '@table', '@rules', '@style', '@defs', a comment or a blank line")
    return result
