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

"""Turning indentation into explicit block markers, before parsing.

A block opens after a line that ends with `:`, and contains the following lines that are indented further.
The first character of the block's first line is replaced by `{`, and ` }` is appended to its last line, so
that every line and column keeps its position, and error messages refer to the original text. Lines that are
indented further without a preceding `:` continue the previous line. Comments are blanked out.
"""

from archtool.errors import FormatError


def mark_blocks(text: str, path: str, first_line: int) -> str:
    """Return `text` with comments blanked out and blocks marked. `first_line` is the line number of the first
    line of `text` in its file, for error messages."""
    lines = [_blank_comment(line) for line in text.split("\n")]
    stack = [0]
    last_content = -1  # The index of the last line with content.
    opens_block = False
    for index, line in enumerate(lines):
        stripped = line.lstrip(" ")
        if stripped.strip() == "":
            continue
        if stripped.startswith("\t"):
            raise FormatError(path, first_line + index, 1, "use spaces, not tabs, for indentation")
        indent = len(line) - len(stripped)
        if opens_block:
            if indent <= stack[-1]:
                raise FormatError(path, first_line + index, indent + 1, "expected an indented block")
            stack.append(indent)
            lines[index] = "{" + line[1:]
        elif indent < stack[-1]:
            while indent < stack[-1]:
                stack.pop()
                lines[last_content] += " }"
            if indent != stack[-1]:
                raise FormatError(path, first_line + index, indent + 1, "the indentation does not match any outer block")
        opens_block = line.rstrip().endswith(":")
        last_content = index
    if opens_block:
        raise FormatError(path, first_line + last_content, 1, "expected an indented block")
    if last_content >= 0:
        lines[last_content] += " }" * (len(stack) - 1)
    return "\n".join(lines)


def _blank_comment(line: str) -> str:
    """Replace a comment (`#` outside a string, up to the end of the line) by spaces."""
    in_string = False
    i = 0
    while i < len(line):
        char = line[i]
        if in_string and char == "\\":
            i += 2
            continue
        if char == '"':
            in_string = not in_string
        elif char == "#" and not in_string:
            return line[:i] + " " * (len(line) - i)
        i += 1
    return line
