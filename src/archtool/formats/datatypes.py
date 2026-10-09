"""Column types, as written in table headers: `str`, `enum(a|b)`, `list(ref(x))`, …"""

from dataclasses import dataclass

from archtool.errors import LexicalError
from archtool.identifiers import is_ident

SIMPLE_KINDS = frozenset({"id", "ident", "str", "text", "int", "float", "bool", "parameter", "argument", "datatype"})

# Kinds whose values are names, identifiers or references. Spaces around the
# elements of lists of these are ignored when reading.
NAME_LIKE_KINDS = frozenset({"id", "ident"})


@dataclass(frozen=True, slots=True)
class SimpleType:
    """A type without arguments, such as `str` or `int`. `kind` is one of SIMPLE_KINDS."""

    kind: str


@dataclass(frozen=True, slots=True)
class EnumType:
    """`enum(a|b|c)`: one of the listed words."""

    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RefType:
    """`ref(a|b)`: the identifier of an element of one of the listed types (or table names, in the meta model)."""

    targets: tuple[str, ...]


type ScalarType = SimpleType | EnumType | RefType


@dataclass(frozen=True, slots=True)
class ListType:
    """`list(…)`: a list of values of a scalar type. Lists of lists are not allowed."""

    element: ScalarType


type DataType = ScalarType | ListType


def parse_datatype(text: str) -> DataType:
    """Parse a column type. Raises LexicalError."""
    if text.startswith("list(") and text.endswith(")"):
        return ListType(_parse_scalar_type(text[5:-1], 5))
    return _parse_scalar_type(text, 0)


def _parse_scalar_type(text: str, offset: int) -> ScalarType:
    if text in SIMPLE_KINDS:
        return SimpleType(text)
    for prefix in ("enum(", "ref("):
        if text.startswith(prefix) and text.endswith(")"):
            words = text[len(prefix) : -1].split("|")
            position = offset + len(prefix)
            for word in words:
                if not is_ident(word):
                    raise LexicalError(position, f"'{word}' is not a valid name")
                position += len(word) + 1
            if prefix == "enum(":
                return EnumType(tuple(words))
            return RefType(tuple(words))
    if text.startswith("list("):
        raise LexicalError(offset, "lists of lists are not allowed")
    raise LexicalError(offset, f"unknown type '{text}'")


def format_datatype(datatype: DataType) -> str:
    """The text of a column type, as written in a header."""
    match datatype:
        case SimpleType(kind):
            return kind
        case EnumType(values):
            return f"enum({'|'.join(values)})"
        case RefType(targets):
            return f"ref({'|'.join(targets)})"
        case ListType(element):
            return f"list({format_datatype(element)})"


def is_name_like(datatype: ScalarType) -> bool:
    """Whether values of `datatype` are names, identifiers or references."""
    match datatype:
        case SimpleType(kind):
            return kind in NAME_LIKE_KINDS
        case EnumType() | RefType():
            return True
