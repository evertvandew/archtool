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

"""Tables: a header line, followed by rows of cells separated by `;`. See "Tables" in doc/file_formats.md."""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from archtool.errors import FormatError, LexicalError
from archtool.formats.datatypes import DataType, format_datatype, parse_datatype
from archtool.formats.escaping import is_control_character, split_unescaped
from archtool.formats.values import Value, format_cell, parse_cell
from archtool.identifiers import is_ident

_LAST_NUMBER = re.compile(r"@last_number (0|[1-9][0-9]*)")


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    datatype: DataType

    def header(self) -> str:
        return f"{self.name}:{format_datatype(self.datatype)}"


@dataclass(slots=True)
class Row:
    """The values of a row, by column name. Columns without a value are absent."""

    values: dict[str, Value]
    line: int


@dataclass(slots=True)
class Table:
    columns: list[Column]
    rows: list[Row] = field(default_factory=list)
    line: int = 1  # The line of the header

    def column(self, name: str) -> Column | None:
        for column in self.columns:
            if column.name == name:
                return column
        return None


def split_lines(text: str, path: Path | str) -> list[str]:
    """Split the text of a file into lines, accepting CRLF line endings and a missing final newline."""
    if text.startswith("﻿"):
        raise FormatError(path, 1, 1, "files must not start with a byte order mark")
    lines = text.replace("\r\n", "\n").split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def parse_header(line: str, path: Path | str, line_number: int) -> list[Column]:
    columns: list[Column] = []
    offset = 0
    for part in line.split(";"):
        name, colon, type_text = part.partition(":")
        if not colon:
            raise FormatError(path, line_number, offset + 1, f"column '{part}' must be written as name:type")
        if not is_ident(name):
            raise FormatError(path, line_number, offset + 1, f"'{name}' is not a valid column name")
        if any(column.name == name for column in columns):
            raise FormatError(path, line_number, offset + 1, f"column '{name}' occurs more than once")
        try:
            datatype = parse_datatype(type_text)
        except LexicalError as error:
            raise FormatError(path, line_number, offset + len(name) + 2 + error.offset, error.message) from None
        columns.append(Column(name, datatype))
        offset += len(part) + 1
    return columns


def parse_row(line: str, columns: Sequence[Column], path: Path | str, line_number: int) -> Row:
    cells = split_unescaped(line, ";")
    if len(cells) != len(columns):
        raise FormatError(path, line_number, 1, f"the row has {len(cells)} cells, but the header has {len(columns)}")
    values: dict[str, Value] = {}
    for (offset, raw), column in zip(cells, columns):
        for i, char in enumerate(raw):
            if is_control_character(char):
                raise FormatError(path, line_number, offset + i + 1, f"control character U+{ord(char):04X} is not allowed")
        try:
            value = parse_cell(raw, column.datatype)
        except LexicalError as error:
            message = f"column '{column.name}': {error.message}"
            raise FormatError(path, line_number, offset + error.offset + 1, message) from None
        if value is not None:
            values[column.name] = value
    return Row(values, line_number)


def read_table(lines: Sequence[tuple[int, str]], path: Path | str) -> Table:
    """Read a table from numbered lines: the header, followed by the rows. Blank lines are ignored."""
    content = [(number, line) for number, line in lines if line != ""]
    if not content:
        raise FormatError(path, lines[0][0] if lines else 1, 1, "the table has no header")
    header_line, header = content[0]
    table = Table(parse_header(header, path, header_line), line=header_line)
    for number, line in content[1:]:
        table.rows.append(parse_row(line, table.columns, path, number))
    return table


def format_table(columns: Sequence[Column], rows: Iterable[Mapping[str, Value]]) -> list[str]:
    """The lines of a table: the header and the rows, in the order given."""
    lines = [";".join(column.header() for column in columns)]
    for row in rows:
        lines.append(";".join(format_cell(row.get(column.name), column.datatype) for column in columns))
    return lines


def read_model_table(text: str, path: Path | str) -> tuple[int, Table]:
    """Read a model table or diagram index table: a `@last_number` line, followed by a table."""
    lines = split_lines(text, path)
    match = _LAST_NUMBER.fullmatch(lines[0]) if lines else None
    if match is None:
        raise FormatError(path, 1, 1, "the first line must be '@last_number <number>'")
    table = read_table(list(enumerate(lines, 1))[1:], path)
    return int(match.group(1)), table


def format_model_table(last_number: int, columns: Sequence[Column], rows: Iterable[Mapping[str, Value]]) -> str:
    """The text of a model table or diagram index table, in canonical form."""
    lines = [f"@last_number {last_number}", *format_table(columns, rows)]
    return "\n".join(lines) + "\n"
