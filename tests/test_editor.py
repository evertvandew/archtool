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

import io
import json
import shutil
from pathlib import Path

import pytest

from archtool.cli import run_edit
from archtool.editing.commands import RawValue, parse_command
from archtool.editing.editor import Editor, Result
from archtool.errors import LexicalError
from archtool.formats.diagram_file import Message, Participant, Show
from archtool.repository import load_repository
from tests.conftest import SIMPLIFIED_ARCADIA


@pytest.fixture
def example(tmp_path: Path) -> Path:
    copy = tmp_path / "example"
    shutil.copytree(SIMPLIFIED_ARCADIA, copy)
    return copy


@pytest.fixture
def editor(example: Path) -> Editor:
    return Editor(load_repository(example))


def run(editor: Editor, text: str) -> Result:
    result = editor.run(text)
    assert result is not None
    return result


def ok(editor: Editor, text: str) -> Result:
    result = run(editor, text)
    assert result.ok, result.error
    return result


def error(editor: Editor, text: str) -> str:
    result = run(editor, text)
    assert not result.ok
    assert result.error is not None
    return result.error


# --- Parsing ------------------------------------------------------------------------------------------------


def test_parse_command() -> None:
    command = parse_command('add requirement name="Grind \\"fresh\\"" priority=high tags=[a, b] x=', 3)
    assert command is not None
    assert (command.name, command.positional, command.line) == ("add", ["requirement"], 3)
    assert command.keywords == {
        "name": RawValue('Grind "fresh"', quoted=True),
        "priority": RawValue("high"),
        "tags": RawValue("[a, b]"),
        "x": RawValue(""),
    }
    assert parse_command("   ") is None
    assert parse_command("# a comment") is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('set x name="abc', "unterminated string"),
        ("set x tags=[a, b", "unbalanced"),
        ('set x "abc"', "must be the value of an argument"),
        ("set x a=1 a=2", "more than once"),
    ],
)
def test_parse_errors(text: str, message: str) -> None:
    with pytest.raises(LexicalError, match=message):
        parse_command(text)


# --- Commands -----------------------------------------------------------------------------------------------


def test_add_with_parent(editor: Editor, example: Path) -> None:
    result = ok(editor, 'add system_function name="Grind beans" parent=system_function_1')
    assert result.created == ["function_contains_function_4", "system_function_5"]
    assert [issue.check for issue in result.issues] == ["system_function_realised"]
    assert (example / "model" / "system_function.csv").read_text().endswith("system_function_5;Grind beans\n")
    hierarchy = (example / "model" / "function_contains_function.csv").read_text()
    assert "function_contains_function_4;system_function_1;system_function_5;\n" in hierarchy
    # The files are complete and consistent: the repository loads again.
    assert "system_function_5" in load_repository(example).model


def test_connect(editor: Editor) -> None:
    ok(editor, 'add requirement name="Grind fresh" text="Grind beans." priority=high verification_method=analysis')
    result = ok(editor, "connect satisfies start=system_function_2 end=requirement_6")
    assert result.created == ["satisfies_5"]
    assert [f.check for f in result.resolved] == ["requirement_satisfied"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("add printer", "unknown type 'printer'"),
        ("add requirment", "did you mean 'requirement'"),
        ("connect component", "is not a relationship type"),
        ("add function_port name=x direction=input", "'owner' is required"),
        ("add function_port owner=component_1 direction=input", "'owner': component_1 is a component, not a function"),
        ("add function_port owner=function_9 direction=input", "'owner': function_9 does not exist"),
        ("add requirement priority=urgent", "'priority': 'urgent' is not one of high, medium, low"),
        ("add requirement colour=red", "a requirement has no attribute 'colour'"),
        ('add requirement name="a\\nb"', "line breaks are only allowed in text values"),
        ("add component parent=system_function_1", "no hierarchy in which a component can be part of a system_function"),
        ("set requirement_9 name=x", "requirement_9 does not exist"),
        ("set requirement_1", "nothing to set"),
        ("set covers_1 end=", "'end' cannot be cleared"),
        ("set system_function_2 parent=system_function_3", "use 'move'"),
        ("move system_function_1 parent=system_function_2", "cannot be moved into itself or one of its descendants"),
        ("show function_breakdown_1 system_function_1", "is generated"),
        ("show functional_sequence_1 logical_function_1", "use 'add_chain'"),
        ("add_chain logical_dataflow_2 functional_chain_1", "is not a sequence diagram"),
        ("add mission generate=allocation(root=component_1)", "'allocation' is not a generation rule of mission"),
        ("add mission generate=mission(root=actor_1)", "rule 'mission' has no parameter 'root'"),
        ("add requirement_traceability generate=traceability", "rule 'traceability' needs a value for 'root'"),
        ("frobnicate x", "unknown command 'frobnicate'"),
    ],
)
def test_errors_leave_the_model_unchanged(editor: Editor, example: Path, text: str, message: str) -> None:
    before = {path: path.read_bytes() for path in example.rglob("*") if path.is_file()}
    assert message in error(editor, text)
    assert {path: path.read_bytes() for path in example.rglob("*") if path.is_file()} == before


def test_set_and_clear(editor: Editor, example: Path) -> None:
    result = ok(editor, 'set requirement_3 name="Safe materials" priority=medium')
    assert result.changed == ["requirement_3"]
    ok(editor, "set component_exchange_1 protocol=")
    model = load_repository(example).model
    assert model.get("requirement_3").values["name"] == "Safe materials"
    assert "protocol" not in model.get("component_exchange_1").values


def test_move(editor: Editor) -> None:
    result = ok(editor, "move system_function_4 parent=system_function_2")
    assert result.deleted == ["function_contains_function_3"]
    assert result.created == ["function_contains_function_4"]
    result = ok(editor, "move system_function_4 parent=")
    assert result.deleted == ["function_contains_function_4"] and result.created == []


def test_delete_propagates(editor: Editor, example: Path) -> None:
    result = ok(editor, "delete logical_function_2")
    # Its ports, the relationships attached to it or its ports, and their breakdowns are deleted too.
    assert result.deleted == [
        "allocated_to_2", "exchange_allocation_2", "exchange_allocation_3", "function_port_4", "function_port_5",
        "functional_exchange_2", "functional_exchange_3", "logical_function_2", "realises_2",
    ]  # fmt: skip
    # References from elements that remain are removed: from the chain, and from drawn diagrams.
    assert result.changed == ["functional_chain_1", "functional_sequence_1", "logical_dataflow_2"]
    repository = load_repository(example)
    assert "relationships" not in repository.model.get("functional_chain_1").values
    assert Show("logical_function_2") not in repository.model.diagrams["logical_dataflow_2"].statements
    assert [f.check for f in result.issues] == ["required"]  # The chain is now empty.


def test_delete_keeps_children(editor: Editor) -> None:
    result = ok(editor, "delete system_function_1")
    assert result.deleted == [
        "function_contains_function_1", "function_contains_function_2", "function_contains_function_3", "system_function_1",
    ]  # fmt: skip
    assert result.changed == []


def test_delete_reports_generated_diagrams(editor: Editor) -> None:
    result = ok(editor, "delete requirement_1")
    assert any(f.check == "diagram" and f.element == "requirement_traceability_1" for f in result.issues)


def test_diagram_commands(editor: Editor, example: Path) -> None:
    result = ok(editor, 'add mission name="Second mission" generate=mission')
    assert result.created == ["mission_2"]
    assert (example / "diagrams" / "mission_2.diag").read_text() == "@diagram mission_2 : mission\ngenerate mission\n@end\n"
    ok(editor, "show logical_dataflow_2 logical_function_1 functional_exchange_1")
    ok(editor, "hide logical_dataflow_2 logical_function_3")
    statements = load_repository(example).model.diagrams["logical_dataflow_2"].statements
    assert Show("logical_function_1") in statements and Show("functional_exchange_1") in statements
    assert all(getattr(s, "element", None) != "logical_function_3" for s in statements)
    ok(editor, "add functional_sequence name=Second")
    ok(editor, "add_chain functional_sequence_2 functional_chain_1")
    assert load_repository(example).model.diagrams["functional_sequence_2"].statements == [
        Participant("logical_function_3"), Participant("logical_function_2"), Participant("logical_function_4"),
        Message("functional_exchange_2"), Message("functional_exchange_3"),
    ]  # fmt: skip


def test_without_saving(example: Path) -> None:
    editor = Editor(load_repository(example), save=False)
    ok(editor, "add actor name=Barista")
    assert "actor_2" in editor.model
    assert "actor_2" not in load_repository(example).model


def test_cli_edit(example: Path) -> None:
    commands = io.StringIO('add actor name=Barista\n\n# comment\nset actor_2 colour=red\n')
    output, errors = io.StringIO(), io.StringIO()
    assert run_edit(example, commands, output, errors) == 1
    results = [json.loads(line) for line in output.getvalue().splitlines()]
    assert results[0] == {
        "ok": True, "line": 1, "command": "add", "created": ["actor_2"], "changed": [], "deleted": [], "issues": [],
        "resolved": [],
    }  # fmt: skip
    assert results[1] == {"ok": False, "line": 4, "command": "set", "error": "a actor has no attribute 'colour'"}
