"""Escape sequences in cell values, and splitting rows and lists.

`;`, `[` and `]` never occur unescaped in a value, and `,` never occurs
unescaped in a list element, so rows and lists can be split before
unescaping. See "Escape sequences" in doc/file_formats.md.
"""

from archtool.errors import LexicalError

_UNESCAPE = {"\\": "\\", "s": ";", "n": "\n", "t": "\t", "[": "[", "]": "]", ",": ","}
_ESCAPE = {"\\": "\\\\", ";": "\\s", "\n": "\\n", "\t": "\\t", "[": "\\[", "]": "\\]"}


def unescape(text: str, *, in_list: bool = False) -> str:
    """Replace the escape sequences in `text` by the characters they stand for.

    `\\,` is only allowed in list elements (`in_list`). Unescaped square
    brackets and control characters are errors.
    """
    result: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\":
            if i + 1 == len(text):
                raise LexicalError(i, "incomplete escape sequence at the end of the value")
            code = text[i + 1]
            if code not in _UNESCAPE:
                raise LexicalError(i, f"unknown escape sequence '\\{code}'")
            if code == "," and not in_list:
                raise LexicalError(i, "'\\,' is only allowed in list elements")
            result.append(_UNESCAPE[code])
            i += 2
            continue
        if char in "[]":
            raise LexicalError(i, f"'{char}' must be escaped as '\\{char}'")
        if is_control_character(char):
            raise LexicalError(i, f"control character U+{ord(char):04X} is not allowed")
        result.append(char)
        i += 1
    return "".join(result)


def escape(value: str, *, in_list: bool = False) -> str:
    """Escape exactly the characters in `value` that must be escaped, and nothing else."""
    result: list[str] = []
    for char in value:
        if char in _ESCAPE:
            result.append(_ESCAPE[char])
        elif char == "," and in_list:
            result.append("\\,")
        elif is_control_character(char):
            raise ValueError(f"control character U+{ord(char):04X} cannot be written")
        else:
            result.append(char)
    return "".join(result)


def is_control_character(char: str) -> bool:
    """Whether `char` is a control character that is not allowed in values.

    Tabs are allowed; line feeds cannot occur, as files are read line by line.
    """
    return (ord(char) < 0x20 and char != "\t") or ord(char) == 0x7F


def split_unescaped(text: str, separator: str) -> list[tuple[int, str]]:
    """Split `text` at every `separator` that is not part of an escape sequence.

    Returns the parts with their offsets in `text`.
    """
    parts: list[tuple[int, str]] = []
    start = 0
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == separator:
            parts.append((start, text[start:i]))
            start = i + 1
        i += 1
    parts.append((start, text[start:]))
    return parts


def is_escaped(text: str, index: int) -> bool:
    """Whether the character at `index` is escaped, i.e. preceded by an odd number of backslashes."""
    count = 0
    i = index - 1
    while i >= 0 and text[i] == "\\":
        count += 1
        i -= 1
    return count % 2 == 1
