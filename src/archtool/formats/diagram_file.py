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

"""Diagram files (`diagrams/<id>.diag`). See "Diagram files" in doc/file_formats.md."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from archtool.errors import FormatError
from archtool.formats.tables import split_lines
from archtool.identifiers import identifier_key, is_ident, split_identifier

_HEADER = re.compile(r"@diagram (\S+) : (\S+)")
_GENERATE = re.compile(r"generate ([a-z][a-z0-9_]*)(?:\((.*)\))?")
_LAYOUT = re.compile(r"layout (\S+) at (-?[0-9]+),(-?[0-9]+)(?: size ([0-9]+)x([0-9]+))?")
_PROCESS = re.compile(r"process (\S+) on (\S+)")
_STYLE = re.compile(r"style (\S+) (.+)")


@dataclass(frozen=True, slots=True)
class Generate:
    """`generate rule(name=value, …)`. Argument values are kept as text in the selection language."""

    rule: str
    arguments: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Show:
    element: str


@dataclass(frozen=True, slots=True)
class Highlight:
    chain: str


@dataclass(frozen=True, slots=True)
class Participant:
    element: str


@dataclass(frozen=True, slots=True)
class Message:
    relationship: str


@dataclass(frozen=True, slots=True)
class Process:
    element: str
    participant: str


@dataclass(frozen=True, slots=True)
class Layout:
    element: str
    x: int
    y: int
    size: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class Style:
    element: str
    css: str


type Statement = Generate | Show | Highlight | Participant | Message | Process | Layout | Style


@dataclass(slots=True)
class DiagramFile:
    id: str
    type: str
    statements: list[Statement] = field(default_factory=list)


def read_diagram_file(text: str, path: Path | str) -> DiagramFile:
    lines = split_lines(text, path)
    header = _HEADER.fullmatch(lines[0]) if lines else None
    if header is None:
        raise FormatError(path, 1, 1, "the first line must be '@diagram <id> : <diagram type>'")
    identifier, type_name = header.group(1), header.group(2)
    if split_identifier(identifier) is None:
        raise FormatError(path, 1, 10, f"'{identifier}' is not a valid identifier")
    diagram = DiagramFile(identifier, type_name)
    ended = False
    for number, line in enumerate(lines[1:], 2):
        if ended and line != "":
            raise FormatError(path, number, 1, "text after '@end'")
        if line == "":
            continue
        if line == "@end":
            ended = True
            continue
        diagram.statements.append(_parse_statement(line, path, number))
    if not ended:
        raise FormatError(path, len(lines), 1, "the diagram must end with '@end'")
    return diagram


def _parse_statement(line: str, path: Path | str, number: int) -> Statement:
    keyword, _, rest = line.partition(" ")
    if keyword == "generate":
        match = _GENERATE.fullmatch(line)
        if match is None:
            raise FormatError(path, number, 1, "expected 'generate <rule>' or 'generate <rule>(<arguments>)'")
        return Generate(match.group(1), _parse_arguments(match.group(2), path, number))
    if keyword in ("show", "highlight", "participant", "message"):
        _check_identifier(rest, path, number, len(keyword) + 2)
        if keyword == "show":
            return Show(rest)
        if keyword == "highlight":
            return Highlight(rest)
        if keyword == "participant":
            return Participant(rest)
        return Message(rest)
    if keyword == "process":
        match = _PROCESS.fullmatch(line)
        if match is None:
            raise FormatError(path, number, 1, "expected 'process <id> on <participant>'")
        _check_identifier(match.group(1), path, number, match.start(1) + 1)
        _check_identifier(match.group(2), path, number, match.start(2) + 1)
        return Process(match.group(1), match.group(2))
    if keyword == "layout":
        match = _LAYOUT.fullmatch(line)
        if match is None:
            raise FormatError(path, number, 1, "expected 'layout <id> at <x>,<y>' or 'layout <id> at <x>,<y> size <w>x<h>'")
        _check_identifier(match.group(1), path, number, match.start(1) + 1)
        size = (int(match.group(4)), int(match.group(5))) if match.group(4) else None
        return Layout(match.group(1), int(match.group(2)), int(match.group(3)), size)
    if keyword == "style":
        match = _STYLE.fullmatch(line)
        if match is None:
            raise FormatError(path, number, 1, "expected 'style <id> <CSS declarations>'")
        _check_identifier(match.group(1), path, number, match.start(1) + 1)
        return Style(match.group(1), match.group(2).strip())
    raise FormatError(path, number, 1, f"unknown statement '{keyword}'")


def _check_identifier(text: str, path: Path | str, number: int, column: int) -> None:
    if split_identifier(text) is None:
        raise FormatError(path, number, column, f"'{text}' is not a valid identifier")


def _parse_arguments(text: str | None, path: Path | str, number: int) -> tuple[tuple[str, str], ...]:
    if text is None or text.strip() == "":
        return ()
    arguments: list[tuple[str, str]] = []
    for part in _split_arguments(text):
        name, equals, value = part.partition("=")
        name, value = name.strip(), value.strip()
        if not equals or not is_ident(name) or value == "":
            raise FormatError(path, number, 1, f"argument '{part.strip()}' must be written as name=value")
        arguments.append((name, value))
    return tuple(arguments)


def _split_arguments(text: str) -> list[str]:
    """Split arguments at commas outside double-quoted strings."""
    parts: list[str] = []
    start = 0
    in_string = False
    i = 0
    while i < len(text):
        char = text[i]
        if in_string and char == "\\":
            i += 2
            continue
        if char == '"':
            in_string = not in_string
        elif char == "," and not in_string:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return parts


def format_diagram_file(diagram: DiagramFile) -> str:
    """The text of a diagram file, with its statements in canonical order."""
    lines = [f"@diagram {diagram.id} : {diagram.type}"]
    statements = diagram.statements
    for statement in statements:
        if isinstance(statement, Generate):
            lines.append(_format_generate(statement))
    lines += [f"participant {s.element}" for s in statements if isinstance(s, Participant)]
    for statement in statements:
        if isinstance(statement, Message):
            lines.append(f"message {statement.relationship}")
        elif isinstance(statement, Process):
            lines.append(f"process {statement.element} on {statement.participant}")
    shows = sorted((s.element for s in statements if isinstance(s, Show)), key=identifier_key)
    lines += [f"show {element}" for element in shows]
    highlights = sorted((s.chain for s in statements if isinstance(s, Highlight)), key=identifier_key)
    lines += [f"highlight {chain}" for chain in highlights]
    layouts = sorted((s for s in statements if isinstance(s, Layout)), key=lambda s: identifier_key(s.element))
    lines += [_format_layout(layout) for layout in layouts]
    styles = sorted((s for s in statements if isinstance(s, Style)), key=lambda s: identifier_key(s.element))
    lines += [f"style {style.element} {style.css}" for style in styles]
    lines.append("@end")
    return "\n".join(lines) + "\n"


def _format_generate(statement: Generate) -> str:
    if not statement.arguments:
        return f"generate {statement.rule}"
    arguments = ", ".join(f"{name}={value}" for name, value in statement.arguments)
    return f"generate {statement.rule}({arguments})"


def _format_layout(layout: Layout) -> str:
    text = f"layout {layout.element} at {layout.x},{layout.y}"
    if layout.size is not None:
        text += f" size {layout.size[0]}x{layout.size[1]}"
    return text
