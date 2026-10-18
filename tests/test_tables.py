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

from archtool.errors import FormatError
from archtool.formats.datatypes import ListType, RefType, SimpleType
from archtool.formats.metamodel_file import read_metamodel_file
from archtool.formats.tables import Column, format_model_table, read_model_table

TABLE = """\
@last_number 7
id:id;start:ref(function_port);end:ref(function_port);name:str;description:text
functional_exchange_1;function_port_3;function_port_8;Position;Current position.\\nUpdated at 10 Hz.
functional_exchange_2;function_port_9;function_port_4;Alarm;
"""


def test_read_model_table() -> None:
    last_number, table = read_model_table(TABLE, "t.csv")
    assert last_number == 7
    assert table.columns[1] == Column("start", RefType(("function_port",)))
    assert [row.values for row in table.rows] == [
        {
            "id": "functional_exchange_1",
            "start": "function_port_3",
            "end": "function_port_8",
            "name": "Position",
            "description": "Current position.\nUpdated at 10 Hz.",
        },
        {"id": "functional_exchange_2", "start": "function_port_9", "end": "function_port_4", "name": "Alarm"},
    ]
    assert [row.line for row in table.rows] == [3, 4]


def test_model_table_round_trip() -> None:
    last_number, table = read_model_table(TABLE, "t.csv")
    assert format_model_table(last_number, table.columns, [row.values for row in table.rows]) == TABLE


def test_reading_is_lenient() -> None:
    crlf = TABLE.replace("\n", "\r\n").rstrip("\r\n")
    last_number, table = read_model_table(crlf, "t.csv")
    assert len(table.rows) == 2


@pytest.mark.parametrize(
    ("text", "line", "column", "message"),
    [
        ("id:id\nfunction_1\n", 1, 1, "@last_number"),
        ("@last_number 1\nid:id;name\n", 2, 7, "must be written as name:type"),
        ("@last_number 1\nid:id;id:str\n", 2, 7, "more than once"),
        ("@last_number 1\nid:id;n:strin\n", 2, 9, "unknown type"),
        ("@last_number 1\nid:id;n:int\nfunction_1\n", 3, 1, "the row has 1 cells"),
        ("@last_number 1\nid:id;n:int\nfunction_1;x1\n", 3, 12, "column 'n': 'x1' is not an integer"),
        ("\ufeff@last_number 1\n", 1, 1, "byte order mark"),
    ],
)
def test_errors(text: str, line: int, column: int, message: str) -> None:
    with pytest.raises(FormatError, match=message) as error:
        read_model_table(text, "t.csv")
    assert (error.value.line, error.value.column) == (line, column)


def test_format_list_columns() -> None:
    columns = [Column("id", SimpleType("id")), Column("relationships", ListType(RefType(("x",))))]
    text = format_model_table(1, columns, [{"id": "chain_1", "relationships": ("x_1", "x_2")}])
    assert text == "@last_number 1\nid:id;relationships:list(ref(x))\nchain_1;[x_1,x_2]\n"


def test_metamodel_file_sections() -> None:
    text = """\
# A comment

@table entity_types
name:ident;extends:ref(entity_types);description:text
# Another comment
component;;A part.

@rules
diagram x:
    show component
@end

@style
.component { fill: red; }
@end
"""
    file = read_metamodel_file(text, "m.csv")
    assert list(file.tables) == ["entity_types"]
    assert file.tables["entity_types"].rows[0].values == {"name": "component", "description": "A part."}
    assert file.tables["entity_types"].rows[0].line == 6
    assert file.rules[0].text == "diagram x:\n    show component\n"
    assert file.rules[0].line == 9
    assert file.styles[0].text == ".component { fill: red; }\n"


def test_metamodel_file_errors() -> None:
    with pytest.raises(FormatError, match="without '@end'"):
        read_metamodel_file("@rules\ndiagram x:\n", "m.csv")
    with pytest.raises(FormatError, match="more than once"):
        read_metamodel_file("@table a\nname:ident\n@table a\nname:ident\n", "m.csv")
    with pytest.raises(FormatError, match="expected '@table'"):
        read_metamodel_file("name:ident\n", "m.csv")
