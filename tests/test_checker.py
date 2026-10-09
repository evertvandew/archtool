import io
import json
import shutil
from pathlib import Path

import pytest

from archtool.checker import check_repository
from archtool.cli import main, run_check
from archtool.repository import load_repository
from tests.conftest import SIMPLIFIED_ARCADIA


@pytest.fixture
def example(tmp_path: Path) -> Path:
    copy = tmp_path / "example"
    shutil.copytree(SIMPLIFIED_ARCADIA, copy)
    return copy


def change(root: Path, file: str, old: str, new: str) -> None:
    path = root / file
    text = path.read_text()
    assert old in text, f"{old!r} not in {file}"
    path.write_text(text.replace(old, new))


def findings(root: Path) -> list[tuple[str, str | None, str]]:
    """The findings of the checks on the model itself; the verification rules of the example are tested in
    test_language.py."""
    rules = {"requirement_covered", "requirement_satisfied", "system_function_realised", "logical_function_allocated",
             "port_direction"}  # fmt: skip
    return [(f.check, f.element, f.message) for f in check_repository(load_repository(root)) if f.check not in rules]


def test_example_has_no_findings() -> None:
    assert check_repository(load_repository(SIMPLIFIED_ARCADIA)) == []


@pytest.mark.parametrize(
    ("file", "old", "new", "expected"),
    [
        (
            "model/covers.csv", "covers_2;test_2;requirement_2", "covers_2;test_2;requirement_9",
            ("reference", "covers_2", "'end' refers to requirement_9, which does not exist"),
        ),
        (
            "model/covers.csv", "covers_2;test_2;requirement_2", "covers_2;test_2;system_function_2",
            ("reference-type", "covers_2", "'end' refers to system_function_2, which is not a requirement"),
        ),
        (
            "model/requirement.csv", ";medium;test", ";;test",
            ("required", "requirement_2", "'priority' is required"),
        ),
        (
            "model/functional_chain.csv", "[functional_exchange_2,functional_exchange_3]", "",
            ("required", "functional_chain_1", "'relationships' is required"),
        ),
        (
            "model/function_contains_function.csv",
            "function_contains_function_3;system_function_1;system_function_4;",
            "function_contains_function_3;system_function_2;system_function_3;",
            (
                "hierarchy", "function_contains_function_3",
                "system_function_3 has more than one parent, through function_contains_function_2, "
                "function_contains_function_3",
            ),
        ),
        (
            "diagrams/logical_dataflow_2.diag", "show logical_function_2", "show component_2",
            ("diagram", "logical_dataflow_2", "element component_2 is a component, which a logical_dataflow cannot show"),
        ),
        (
            "diagrams/logical_dataflow_2.diag", "highlight functional_chain_1", "highlight functional_chain_7",
            ("diagram", "logical_dataflow_2", "chain functional_chain_7 does not exist"),
        ),
        (
            "diagrams/functional_sequence_1.diag", "participant logical_function_1\n", "",
            ("diagram", "functional_sequence_1", "message functional_exchange_1: logical_function_1 is not a participant"),
        ),
        (
            "diagrams/functional_sequence_1.diag", "message functional_exchange_1", "show functional_exchange_1",
            ("diagram", "functional_sequence_1", "a sequence diagram has no 'show' statements"),
        ),
        (
            "diagrams/mission_1.diag", "generate mission", "generate allocation(root=component_1)",
            ("diagram", "mission_1", "rule 'allocation' is not a generation rule of mission"),
        ),
        (
            "diagrams/mission_1.diag", "generate mission", "participant actor_1",
            ("diagram", "mission_1", "only sequence diagrams have 'participant' statements"),
        ),
    ],
)
def test_findings(example: Path, file: str, old: str, new: str, expected: tuple[str, str, str]) -> None:
    change(example, file, old, new)
    assert findings(example) == [expected]


def test_hierarchy_cycle(example: Path) -> None:
    change(
        example,
        "model/component_contains_component.csv",
        "@last_number 3\n",
        "@last_number 4\n",
    )
    path = example / "model" / "component_contains_component.csv"
    path.write_text(path.read_text() + "component_contains_component_4;component_2;component_1;\n")
    assert ("hierarchy", "component_contains_component_4", "component_1 is its own ancestor") in findings(example)


TEMPLATES = """\
@table entity_types
name:ident;extends:ref(entity_types);description:text
@table template_types
name:ident;extends:ref(template_types);description:text
filter_template;;
@table instantiation_types
name:ident;template:ref(template_types);description:text
filter;filter_template;
"""


def test_template_arguments(tmp_path: Path) -> None:
    (tmp_path / "metamodel.csv").write_text(TEMPLATES)
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "filter_template.csv").write_text(
        "@last_number 1\nid:id;parameters:list(parameter)\nfilter_template_1;[cutoff:float,order:int=2,gain:float]\n"
    )
    (tmp_path / "model" / "filter.csv").write_text(
        "@last_number 3\nid:id;template:ref(filter_template);arguments:list(argument)\n"
        "filter_1;filter_template_1;[cutoff=50.0,gain=1]\n"
        "filter_2;filter_template_1;[cutoff=fast,gain=1,ripple=3]\n"
        "filter_3;filter_template_1;[gain=1,gain=2]\n"
    )
    assert findings(tmp_path) == [
        ("arguments", "filter_2", "argument 'cutoff': 'fast' is not a number"),
        ("arguments", "filter_2", "template filter_template_1 has no parameter 'ripple'"),
        ("arguments", "filter_3", "argument 'gain' is given more than once"),
        ("arguments", "filter_3", "parameter 'cutoff' of template filter_template_1 is required"),
    ]


def test_cli_reports_json_lines(example: Path) -> None:
    change(example, "model/covers.csv", "covers_2;test_2;requirement_2", "covers_2;test_2;requirement_9")
    output = io.StringIO()
    assert run_check(example, output) == 1
    assert [json.loads(line) for line in output.getvalue().splitlines()][:1] == [
        {
            "severity": "error",
            "check": "reference",
            "element": "covers_2",
            "path": "model/covers.csv",
            "message": "'end' refers to requirement_9, which does not exist",
        }
    ]


def test_cli_reports_syntax_errors_with_position(example: Path) -> None:
    change(example, "model/requirement.csv", ";high;test", ";urgent;test")
    output = io.StringIO()
    assert run_check(example, output) == 1
    finding = json.loads(output.getvalue())
    assert finding["check"] == "syntax"
    assert finding["path"] == "model/requirement.csv"
    assert finding["line"] == 3
    assert "'urgent' is not one of high, medium, low" in finding["message"]


def test_cli_main(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", str(SIMPLIFIED_ARCADIA)]) == 0
    assert capsys.readouterr().out == ""

