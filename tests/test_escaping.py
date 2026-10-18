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

import pytest

from archtool.errors import LexicalError
from archtool.formats.escaping import escape, is_escaped, split_unescaped, unescape


@pytest.mark.parametrize(
    ("escaped", "value"),
    [
        ("plain text", "plain text"),
        ("a\\sb", "a;b"),
        ("line 1\\nline 2", "line 1\nline 2"),
        ("tab\\there", "tab\there"),
        ("back\\\\slash", "back\\slash"),
        ("\\[x\\]", "[x]"),
        ("", ""),
    ],
)
def test_round_trip(escaped: str, value: str) -> None:
    assert unescape(escaped) == value
    assert escape(value) == escaped


def test_comma_is_only_escaped_in_lists() -> None:
    assert escape("a, b") == "a, b"
    assert escape("a, b", in_list=True) == "a\\, b"
    assert unescape("a\\, b", in_list=True) == "a, b"
    with pytest.raises(LexicalError, match="only allowed in list elements"):
        unescape("a\\, b")


@pytest.mark.parametrize(
    ("text", "offset", "message"),
    [
        ("abc\\x", 3, "unknown escape sequence"),
        ("abc\\", 3, "incomplete escape sequence"),
        ("a[b", 1, "must be escaped"),
        ("a\x01b", 1, "control character"),
    ],
)
def test_errors(text: str, offset: int, message: str) -> None:
    with pytest.raises(LexicalError, match=message) as error:
        unescape(text)
    assert error.value.offset == offset


def test_split_ignores_escaped_separators() -> None:
    assert split_unescaped("a,b\\,c,,d", ",") == [(0, "a"), (2, "b\\,c"), (7, ""), (8, "d")]
    assert split_unescaped("a\\\\,b", ",") == [(0, "a\\\\"), (4, "b")]


def test_is_escaped() -> None:
    assert is_escaped("a\\]", 2)
    assert not is_escaped("a\\\\]", 3)
    assert is_escaped("a\\\\\\]", 4)
