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

"""Names and identifiers, as defined in doc/file_formats.md."""

import re

_IDENT = re.compile(r"[a-z][a-z0-9_]*")
_IDENTIFIER = re.compile(r"([a-z][a-z0-9_]*)_([1-9][0-9]*)")
_TRAILING_NUMBER = re.compile(r"_[0-9]+$")

# The keywords of the selection language, which cannot be used as names in a meta model.
KEYWORDS = frozenset(
    {
        "define", "diagram", "check", "query", "let", "show", "for", "each", "in",
        "require", "otherwise", "select", "columns", "order", "by", "descending",
        "where", "between", "from", "to", "union", "intersect", "except", "and",
        "or", "not", "is", "empty", "contains", "matches", "every", "some", "no",
        "this", "true", "false", "error", "warning", "info",
    }
)  # fmt: skip


def is_ident(text: str) -> bool:
    """Whether `text` is a name: a lowercase letter, followed by lowercase letters, digits and underscores."""
    return _IDENT.fullmatch(text) is not None


def is_valid_type_name(name: str) -> bool:
    """Whether `name` can be used as the name of a type.

    Identifiers are split at their last underscore, so a type name must not end
    in an underscore followed by digits.
    """
    return is_ident(name) and _TRAILING_NUMBER.search(name) is None and name not in KEYWORDS


def split_identifier(identifier: str) -> tuple[str, int] | None:
    """The type name and number of an identifier, or None if it is not a valid identifier."""
    match = _IDENTIFIER.fullmatch(identifier)
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def make_identifier(type_name: str, number: int) -> str:
    """The identifier of element `number` of type `type_name`."""
    return f"{type_name}_{number}"


def identifier_key(identifier: str) -> tuple[str, int]:
    """A sort key for identifiers: by type name, then by number."""
    parts = split_identifier(identifier)
    if parts is None:
        raise ValueError(f"not an identifier: {identifier!r}")
    return parts
