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
from archtool.formats.diagram_file import (
    DiagramFile,
    Generate,
    Highlight,
    Layout,
    Message,
    Participant,
    Process,
    Show,
    Style,
    format_diagram_file,
    read_diagram_file,
)


def test_generated_diagram() -> None:
    text = """\
@diagram physical_architecture_4 : physical_architecture
generate component_internals(root=component_1, depth=2)
layout component_5 at 120,40 size 200x120
@end
"""
    diagram = read_diagram_file(text, "d.diag")
    assert diagram.statements == [
        Generate("component_internals", (("root", "component_1"), ("depth", "2"))),
        Layout("component_5", 120, 40, (200, 120)),
    ]
    assert format_diagram_file(diagram) == text


def test_rule_without_parameters() -> None:
    diagram = read_diagram_file("@diagram mission_1 : mission\ngenerate mission\n@end\n", "d.diag")
    assert diagram.statements == [Generate("mission")]


def test_sequence_diagram_keeps_its_order() -> None:
    text = """\
@diagram functional_sequence_1 : functional_sequence
participant logical_function_3
participant logical_function_1
message functional_exchange_2
process logical_function_9 on logical_function_1
message functional_exchange_1
@end
"""
    diagram = read_diagram_file(text, "d.diag")
    assert diagram.statements[2:] == [
        Message("functional_exchange_2"),
        Process("logical_function_9", "logical_function_1"),
        Message("functional_exchange_1"),
    ]
    assert format_diagram_file(diagram) == text


def test_canonical_order() -> None:
    diagram = DiagramFile(
        "logical_dataflow_2",
        "logical_dataflow",
        [
            Style("logical_function_2", "stroke-width: 3px"),
            Show("logical_function_10"),
            Highlight("functional_chain_1"),
            Show("logical_function_9"),
            Show("functional_exchange_2"),
            Layout("logical_function_3", 40, 40),
        ],
    )
    assert format_diagram_file(diagram) == """\
@diagram logical_dataflow_2 : logical_dataflow
show functional_exchange_2
show logical_function_9
show logical_function_10
highlight functional_chain_1
layout logical_function_3 at 40,40
style logical_function_2 stroke-width: 3px
@end
"""


def test_string_arguments_may_contain_commas() -> None:
    diagram = read_diagram_file('@diagram x_1 : x\ngenerate r(title="a, b", n=1)\n@end\n', "d.diag")
    assert diagram.statements == [Generate("r", (("title", '"a, b"'), ("n", "1")))]


@pytest.mark.parametrize(
    ("text", "line", "message"),
    [
        ("show x_1\n@end\n", 1, "first line"),
        ("@diagram x_1 : x\nshow x_1\n", 2, "must end with '@end'"),
        ("@diagram x_1 : x\nshow X\n@end\n", 2, "not a valid identifier"),
        ("@diagram x_1 : x\ndraw x_1\n@end\n", 2, "unknown statement"),
        ("@diagram x_1 : x\nlayout x_1 at 1\n@end\n", 2, "expected 'layout"),
        ("@diagram x_1 : x\n@end\nshow x_1\n", 3, "after '@end'"),
    ],
)
def test_errors(text: str, line: int, message: str) -> None:
    with pytest.raises(FormatError, match=message) as error:
        read_diagram_file(text, "d.diag")
    assert error.value.line == line


def test_participants_are_written_before_messages() -> None:
    diagram = DiagramFile("s_1", "s", [Participant("f_1"), Message("e_1"), Participant("f_2")])
    assert format_diagram_file(diagram) == "@diagram s_1 : s\nparticipant f_1\nparticipant f_2\nmessage e_1\n@end\n"
