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

"""Parsing command lines.

A command line is a command name, followed by arguments: positional arguments (names and identifiers), and
`key=value` arguments. A value is written as in a table cell, e.g. `high`, `42`, `[function_3, function_7]`, or
as a string in double quotes, with `\\"`, `\\\\` and `\\n` as escape sequences: `name="Compute position"`.
"""

from dataclasses import dataclass, field

from archtool.errors import LexicalError

_STRING_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}


@dataclass(frozen=True, slots=True)
class RawValue:
    """The value of a `key=value` argument, as written. `quoted` tells whether it was a string in quotes."""

    text: str
    quoted: bool = False


@dataclass(slots=True)
class Command:
    name: str
    positional: list[str] = field(default_factory=list)
    keywords: dict[str, RawValue] = field(default_factory=dict)
    line: int = 0


def parse_command(text: str, line: int = 0) -> Command | None:
    """Parse a command line. Returns None for a blank line or a comment. Raises LexicalError."""
    tokens = _tokens(text)
    if not tokens:
        return None
    (name, name_quoted), *arguments = tokens
    if name_quoted:
        raise LexicalError(0, "a command must start with its name")
    command = Command(name, line=line)
    for token, quoted in arguments:
        if quoted:
            raise LexicalError(0, f"a string must be the value of an argument: key=\"{token}\"")
        key, equals, value = token.partition("=")
        if equals:
            if key in command.keywords:
                raise LexicalError(0, f"'{key}' is given more than once")
            command.keywords[key] = _value(value)
        else:
            command.positional.append(token)
    return command


def _value(text: str) -> RawValue:
    if text.startswith('"'):
        return RawValue(_unquote(text), quoted=True)
    return RawValue(text)


def _tokens(text: str) -> list[tuple[str, bool]]:
    """Split a line into tokens at spaces outside strings and square brackets. Returns each token, and whether it
    is a quoted string on its own."""
    tokens: list[tuple[str, bool]] = []
    current: list[str] = []
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        char = text[i]
        if in_string:
            current.append(char)
            if char == "\\" and i + 1 < len(text):
                current.append(text[i + 1])
                i += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            current.append(char)
        elif char == "#" and depth == 0 and not current:
            break
        elif char in " \t" and depth == 0:
            if current:
                tokens.append(_token(current))
                current = []
        else:
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            current.append(char)
        i += 1
    if in_string:
        raise LexicalError(len(text), "unterminated string")
    if depth != 0:
        raise LexicalError(len(text), "unbalanced square brackets")
    if current:
        tokens.append(_token(current))
    return tokens


def _token(characters: list[str]) -> tuple[str, bool]:
    token = "".join(characters)
    if token.startswith('"') and token.endswith('"') and len(token) >= 2:
        return _unquote(token), True
    return token, False


def _unquote(token: str) -> str:
    if len(token) < 2 or not token.endswith('"'):
        raise LexicalError(0, f"unterminated string {token}")
    body = token[1:-1]
    result: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            code = body[i + 1]
            if code not in _STRING_ESCAPES:
                raise LexicalError(i, f"unknown escape sequence '\\{code}'")
            result.append(_STRING_ESCAPES[code])
            i += 2
        else:
            result.append(body[i])
            i += 1
    return "".join(result)
