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
from archtool.formats.datatypes import (
    DataType,
    EnumType,
    ListType,
    RefType,
    SimpleType,
    format_datatype,
    parse_datatype,
)
from archtool.formats.values import Argument, Float, Parameter, Value, format_cell, format_float, parse_cell

STR = SimpleType("str")
TEXT = SimpleType("text")
INT = SimpleType("int")
FLOAT = SimpleType("float")
BOOL = SimpleType("bool")
ID = SimpleType("id")
REF = RefType(("function",))


@pytest.mark.parametrize(
    "text",
    ["id", "str", "enum(high|medium|low)", "ref(component|actor)", "list(ref(function))", "list(parameter)"],
)
def test_datatype_round_trip(text: str) -> None:
    assert format_datatype(parse_datatype(text)) == text


def test_datatype_errors() -> None:
    with pytest.raises(LexicalError, match="lists of lists"):
        parse_datatype("list(list(str))")
    with pytest.raises(LexicalError, match="unknown type"):
        parse_datatype("string")
    with pytest.raises(LexicalError, match="not a valid name") as error:
        parse_datatype("enum(a|B)")
    assert error.value.offset == 7


@pytest.mark.parametrize(
    ("raw", "datatype", "value"),
    [
        ("Compute position", STR, "Compute position"),
        ("Line 1\\nLine 2", TEXT, "Line 1\nLine 2"),
        ("42", INT, 42),
        ("-3", INT, -3),
        ("true", BOOL, True),
        ("1e-07", FLOAT, Float("1e-07")),
        ("50.0", FLOAT, Float("50.0")),
        ("function_42", ID, "function_42"),
        ("high", EnumType(("high", "low")), "high"),
        ("enum(a|b)", SimpleType("datatype"), EnumType(("a", "b"))),
        ("[function_3,function_7]", ListType(REF), ("function_3", "function_7")),
        ("[Alpha\\, Beta,Gamma]", ListType(STR), ("Alpha, Beta", "Gamma")),
        ("cutoff:float", SimpleType("parameter"), Parameter("cutoff", FLOAT)),
        ("order:int=2", SimpleType("parameter"), Parameter("order", INT, 2)),
        ("cutoff=50.0", SimpleType("argument"), Argument("cutoff", "50.0")),
    ],
)
def test_round_trip(raw: str, datatype: DataType, value: Value) -> None:
    assert parse_cell(raw, datatype) == value
    assert format_cell(value, datatype) == raw


def test_empty_cells_and_lists_have_no_value() -> None:
    assert parse_cell("", STR) is None
    assert parse_cell("[]", ListType(REF)) is None
    assert format_cell(None, STR) == ""
    assert format_cell((), ListType(REF)) == ""


def test_floats_keep_their_text() -> None:
    for text in ("1.50", "1e3", "0.000001", ".5"):
        assert format_cell(parse_cell(text, FLOAT), FLOAT) == text
    assert format_float(0.1) == "0.1"
    assert format_float(1e-05) == "1e-05"
    assert format_float(1e16) == "1e+16"


def test_lists_of_names_are_lenient_about_spaces() -> None:
    assert parse_cell("[component, actor]", ListType(SimpleType("ident"))) == ("component", "actor")
    assert parse_cell("[ function_1 , function_2 ]", ListType(REF)) == ("function_1", "function_2")
    assert parse_cell("[a, b]", ListType(STR)) == ("a", " b")


@pytest.mark.parametrize(
    ("raw", "datatype", "offset", "message"),
    [
        ("12x", INT, 0, "not an integer"),
        ("maybe", BOOL, 0, "not true or false"),
        ("urgent", EnumType(("high", "low")), 0, "not one of"),
        ("function-1", REF, 0, "not a valid reference"),
        ("a\\nb", STR, 1, "only allowed in text"),
        ("function_1,function_2", ListType(REF), 0, "must start with"),
        ("[function_1,function_2", ListType(REF), 22, "must end with"),
        ("[function_1,,function_2]", ListType(REF), 12, "empty list element"),
        ("[function_1,b-d]", ListType(REF), 12, "not a valid reference"),
        ("order:int=two", SimpleType("parameter"), 10, "not an integer"),
    ],
)
def test_errors(raw: str, datatype: DataType, offset: int, message: str) -> None:
    with pytest.raises(LexicalError, match=message) as error:
        parse_cell(raw, datatype)
    assert error.value.offset == offset
