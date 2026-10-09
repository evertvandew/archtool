"""Cell values: parsing the text of a cell according to its column type, and writing it back.

Values are represented as:

* `str` for `id`, `ident`, `str`, `text`, `enum(…)` and `ref(…)`;
* `int` for `int`, and `bool` for `bool`;
* `Float` for `float`, which keeps the text as written;
* `DataType` for `datatype`;
* `Parameter` and `Argument` for template parameters and arguments;
* a tuple of these for `list(…)`.

An empty cell, an empty list and an empty string all mean "no value", represented by None.
"""

import re
from dataclasses import dataclass

from archtool.errors import LexicalError
from archtool.formats.datatypes import (
    DataType,
    EnumType,
    ListType,
    RefType,
    ScalarType,
    SimpleType,
    format_datatype,
    is_name_like,
    parse_datatype,
)
from archtool.formats.escaping import escape, is_escaped, split_unescaped, unescape
from archtool.identifiers import is_ident, split_identifier

_INT = re.compile(r"-?(0|[1-9][0-9]*)")
_REFERENCE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_FLOAT = re.compile(r"-?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?")


@dataclass(frozen=True, slots=True)
class Float:
    """A float, which keeps its text so that it is written back exactly as it was read."""

    text: str

    @staticmethod
    def from_value(value: float) -> "Float":
        """A new float, written in the shortest form that reads back as the same value."""
        return Float(format_float(value))

    def value(self) -> float:
        return float(self.text)


@dataclass(frozen=True, slots=True)
class Parameter:
    """A template parameter: `name:datatype`, or `name:datatype=default`."""

    name: str
    datatype: ScalarType
    default: "Scalar | None" = None


@dataclass(frozen=True, slots=True)
class Argument:
    """A template argument: `name=value`. The value is kept as (unescaped) text, as its type is
    defined by the template."""

    name: str
    text: str


type Scalar = str | int | bool | Float | DataType | Parameter | Argument
type Value = Scalar | tuple[Scalar, ...]


def format_float(value: float) -> str:
    """The shortest decimal form of `value`, with an exponent only below 1e-4 or from 1e16."""
    text = repr(value)
    if text in ("inf", "-inf", "nan"):
        raise ValueError(f"{text} cannot be written")
    return text


def parse_cell(raw: str, datatype: DataType) -> Value | None:
    """Parse the (escaped) text of a cell. Raises LexicalError, with an offset within `raw`."""
    if raw == "":
        return None
    if isinstance(datatype, ListType):
        return _parse_list(raw, datatype.element)
    return parse_scalar(raw, datatype, in_list=False)


def _parse_list(raw: str, element: ScalarType) -> tuple[Scalar, ...] | None:
    lenient = is_name_like(element)
    if not raw.startswith("["):
        raise LexicalError(0, "a list must start with '['")
    last = len(raw) - 1
    if last == 0 or raw[last] != "]" or is_escaped(raw, last):
        raise LexicalError(len(raw), "a list must end with ']'")
    inner = raw[1:-1]
    if inner == "" or (lenient and inner.strip() == ""):
        return None
    values: list[Scalar] = []
    for offset, part in split_unescaped(inner, ","):
        offset += 1
        text = part
        if lenient:
            text = part.strip()
            offset += len(part) - len(part.lstrip())
        if text == "":
            raise LexicalError(offset, "empty list element")
        try:
            values.append(parse_scalar(text, element, in_list=True))
        except LexicalError as error:
            raise error.shifted(offset) from None
    return tuple(values)


def parse_scalar(raw: str, datatype: ScalarType, *, in_list: bool) -> Scalar:
    """Parse the (escaped) text of a single value. Raises LexicalError."""
    match datatype:
        case EnumType(values):
            text = unescape(raw, in_list=in_list)
            if text not in values:
                raise LexicalError(0, f"'{text}' is not one of {', '.join(values)}")
            return text
        case RefType():
            # An identifier in a model table; in the meta-model file, the name of a type or a stereotype.
            text = unescape(raw, in_list=in_list)
            if _REFERENCE.fullmatch(text) is None:
                raise LexicalError(0, f"'{text}' is not a valid reference")
            return text
        case SimpleType("id"):
            return _parse_identifier(raw, in_list)
        case SimpleType("ident"):
            text = unescape(raw, in_list=in_list)
            if not is_ident(text):
                raise LexicalError(0, f"'{text}' is not a valid name")
            return text
        case SimpleType("str"):
            text = unescape(raw, in_list=in_list)
            if "\n" in text:
                raise LexicalError(raw.find("\\n"), "line breaks are only allowed in text values")
            return text
        case SimpleType("text"):
            return unescape(raw, in_list=in_list)
        case SimpleType("int"):
            if _INT.fullmatch(raw) is None:
                raise LexicalError(0, f"'{raw}' is not an integer")
            return int(raw)
        case SimpleType("float"):
            if _FLOAT.fullmatch(raw) is None:
                raise LexicalError(0, f"'{raw}' is not a number")
            return Float(raw)
        case SimpleType("bool"):
            if raw == "true":
                return True
            if raw == "false":
                return False
            raise LexicalError(0, f"'{raw}' is not true or false")
        case SimpleType("datatype"):
            return parse_datatype(unescape(raw, in_list=in_list))
        case SimpleType("parameter"):
            return _parse_parameter(raw, in_list)
        case SimpleType("argument"):
            return _parse_argument(raw, in_list)
        case SimpleType(kind):
            raise AssertionError(f"unknown kind {kind}")


def _parse_identifier(raw: str, in_list: bool) -> str:
    text = unescape(raw, in_list=in_list)
    if split_identifier(text) is None:
        raise LexicalError(0, f"'{text}' is not a valid identifier")
    return text


def _parse_parameter(raw: str, in_list: bool) -> Parameter:
    colon = raw.find(":")
    if colon < 0:
        raise LexicalError(0, "a parameter is written as name:type or name:type=default")
    name = raw[:colon]
    if not is_ident(name):
        raise LexicalError(0, f"'{name}' is not a valid parameter name")
    rest = raw[colon + 1 :]
    equals = rest.find("=")
    type_text = rest if equals < 0 else rest[:equals]
    try:
        datatype = parse_datatype(type_text)
    except LexicalError as error:
        raise error.shifted(colon + 1) from None
    if isinstance(datatype, ListType):
        raise LexicalError(colon + 1, "parameters cannot be lists")
    if equals < 0:
        return Parameter(name, datatype)
    default_offset = colon + 1 + equals + 1
    try:
        default = parse_scalar(rest[equals + 1 :], datatype, in_list=in_list)
    except LexicalError as error:
        raise error.shifted(default_offset) from None
    return Parameter(name, datatype, default)


def _parse_argument(raw: str, in_list: bool) -> Argument:
    equals = raw.find("=")
    if equals < 0:
        raise LexicalError(0, "an argument is written as name=value")
    name = raw[:equals]
    if not is_ident(name):
        raise LexicalError(0, f"'{name}' is not a valid parameter name")
    try:
        text = unescape(raw[equals + 1 :], in_list=in_list)
    except LexicalError as error:
        raise error.shifted(equals + 1) from None
    return Argument(name, text)


def format_cell(value: Value | None, datatype: DataType) -> str:
    """The text of a cell, in canonical form."""
    if value is None:
        return ""
    if isinstance(datatype, ListType):
        if not isinstance(value, tuple):
            raise TypeError(f"expected a list, got {value!r}")
        if not value:
            return ""
        return "[" + ",".join(format_scalar(item, datatype.element, in_list=True) for item in value) + "]"
    if isinstance(value, tuple):
        raise TypeError(f"expected a single value, got {value!r}")
    return format_scalar(value, datatype, in_list=False)


def format_scalar(value: Scalar, datatype: ScalarType, *, in_list: bool) -> str:
    """The (escaped) text of a single value."""
    match datatype, value:
        case SimpleType("int"), int() if not isinstance(value, bool):
            return str(value)
        case SimpleType("bool"), bool():
            return "true" if value else "false"
        case SimpleType("float"), Float(text):
            return text
        case SimpleType("str"), str() if "\n" in value:
            raise ValueError(f"a str value cannot contain line breaks: {value!r}")
        case SimpleType("datatype"), SimpleType() | EnumType() | RefType() | ListType():
            return escape(format_datatype(value), in_list=in_list)
        case SimpleType("parameter"), Parameter(name, param_type, default):
            text = f"{name}:{format_datatype(param_type)}"
            if default is not None:
                text += "=" + format_scalar(default, param_type, in_list=in_list)
            return text
        case SimpleType("argument"), Argument(name, text):
            return f"{name}={escape(text, in_list=in_list)}"
        case SimpleType("id" | "ident" | "str" | "text") | EnumType() | RefType(), str():
            return escape(value, in_list=in_list)
    raise TypeError(f"value {value!r} does not match type {format_datatype(datatype)}")
