import io
import json
import shutil
from pathlib import Path

import pytest

from archtool.checker import check_repository
from archtool.cli import run_query
from archtool.errors import FormatError
from archtool.formats.metamodel_file import TextSection
from archtool.language.blocks import mark_blocks
from archtool.language.parser import parse_expression, parse_rules
from archtool.language.runtime import Rules, RuleError, Runner, load_rules
from archtool.language.syntax import CheckRule, Name, Navigate
from archtool.metamodel import MetaModel
from archtool.repository import Repository, load_repository
from tests.conftest import SIMPLIFIED_ARCADIA


@pytest.fixture(scope="module")
def repository() -> Repository:
    return load_repository(SIMPLIFIED_ARCADIA)


@pytest.fixture(scope="module")
def runner(repository: Repository) -> Runner:
    rules = load_rules(repository.metamodel)
    assert rules.errors == []
    return Runner(rules, repository.model)


def ids(runner: Runner, expression: str) -> list[str]:
    return [str(record["id"]) for record in runner.expression(expression).records()]


# --- Blocks and parsing ---------------------------------------------------------------------------------------


def test_blocks_keep_positions() -> None:
    text = "diagram x:\n    show a\n    show b\n\ncheck y (info):\n    for each z in a:\n        require z is empty\n        otherwise \"m\"\n"
    marked = mark_blocks(text, "f", 1)
    assert marked.split("\n")[:4] == ["diagram x:", "{   show a", "    show b }", ""]
    assert marked.split("\n")[6:8] == ["{       require z is empty", '        otherwise "m" } }']


def test_continuation_lines_do_not_open_blocks() -> None:
    marked = mark_blocks("check y (info):\n    for each z in a:\n        require z is empty\n            otherwise \"m\"\n", "f", 1)
    assert marked.rstrip("\n").endswith('otherwise "m" } }')


@pytest.mark.parametrize(
    ("text", "line", "message"),
    [
        ("diagram x:\nshow a\n", 2, "expected an indented block"),
        ("diagram x:\n    show a\n  show b\n", 3, "does not match any outer block"),
        ("diagram x:\n\tshow a\n", 2, "not tabs"),
        ("diagram x:\n", 1, "expected an indented block"),
    ],
)
def test_block_errors(text: str, line: int, message: str) -> None:
    with pytest.raises(FormatError, match=message) as error:
        mark_blocks(text, "f", 10)
    assert error.value.line == 9 + line


def test_syntax_error_position() -> None:
    with pytest.raises(FormatError) as error:
        parse_rules("diagram x:\n    shw root\n", "m.csv", 20)
    assert (error.value.line, error.value.column) == (21, 5)


def test_keywords_are_not_names() -> None:
    with pytest.raises(FormatError, match="reserved word"):
        parse_expression("where.parent", "e")


def test_message_interpolation(repository: Repository) -> None:
    section = repository.metamodel.rules[0]
    rules = parse_rules(section.text, "m.csv", section.line)
    check = next(rule for rule in rules if isinstance(rule, CheckRule))
    message = check.foreach.statements[0].message  # type: ignore[union-attr]
    assert message.parts[0] == "Requirement "
    assert isinstance(message.parts[1], Name) and message.parts[1].ident == "r"
    assert (message.parts[1].pos.line, message.parts[1].pos.column) == (message.pos.line, message.pos.column + 13)


def test_navigation_syntax() -> None:
    expression = parse_expression("a.targets(b).owner", "e")
    assert isinstance(expression, Navigate) and expression.step == "owner"
    assert isinstance(expression.source, Navigate) and expression.source.arguments is not None


# --- Evaluation ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("requirement where priority = high", ["requirement_1"]),
        ("requirement where verification_method = test", ["requirement_1", "requirement_2", "requirement_4", "requirement_5"]),
        ("requirement where priority in [high, low]", ["requirement_1", "requirement_3", "requirement_5"]),
        ("requirement where text contains \"SAFE\"", ["requirement_3"]),
        ("requirement where name matches \"^Brew\"", ["requirement_1", "requirement_2", "requirement_4"]),
        ("function where children is empty", [
            "logical_function_1", "logical_function_2", "logical_function_3", "logical_function_4",
            "system_function_2", "system_function_3", "system_function_4",
        ]),
        ("system_function_1.descendants(1)", ["system_function_2", "system_function_3", "system_function_4"]),
        ("system_function_3.ancestors", ["system_function_1"]),
        ("system_function_3.parent", ["system_function_1"]),
        ("component_2.ports", ["component_port_1", "component_port_4"]),
        ("component_port_1.owner", ["component_2"]),
        ("logical_function_2.outgoing(functional_exchange)", ["functional_exchange_3"]),
        ("logical_function_2.incoming(functional_exchange)", ["functional_exchange_2"]),
        ("logical_function_4.sources(functional_exchange)", ["logical_function_1", "logical_function_2"]),
        ("logical_function_3.reachable(functional_exchange)", ["logical_function_2", "logical_function_4"]),
        ("logical_function_1.targets(allocated_to)", ["component_2"]),
        ("component_2.sources(allocated_to)", ["logical_function_1", "logical_function_2"]),
        ("system_function_3.refined_by", ["logical_function_2", "logical_function_3"]),
        ("logical_function_4.refines", ["system_function_4"]),
        ("functional_exchange_2.chains", ["functional_chain_1"]),
        ("functional_chain_1.relationships", ["functional_exchange_2", "functional_exchange_3"]),
        ("component_exchange_1.constituents", ["functional_exchange_1", "functional_exchange_3"]),
        ("functional_exchange_1.aggregate", ["component_exchange_1"]),
        ("functional_exchange between (logical_function_2 union logical_function_4)", ["functional_exchange_3"]),
        ("functional_exchange from logical_function_3", ["functional_exchange_2"]),
        ("functional_exchange to logical_function_4", ["functional_exchange_1", "functional_exchange_3"]),
        ("covers to (requirement where priority = high)", ["covers_1"]),
        ("(requirement where priority = high) union requirement_3", ["requirement_1", "requirement_3"]),
        ("requirement except (requirement where priority = high)", ["requirement_2", "requirement_3", "requirement_4", "requirement_5"]),
        ("test where some r in targets(covers): r.priority = high", ["test_1"]),
        ("test where every r in targets(covers): r.priority = high", ["test_1"]),
        ("logical_function where count(targets(allocated_to)) = 1", [
            "logical_function_1", "logical_function_2", "logical_function_3", "logical_function_4",
        ]),
        ("requirement where not (priority = high or priority = low)", ["requirement_2", "requirement_4"]),
        ("Relationship_breakdown", ["exchange_allocation_1", "exchange_allocation_2", "exchange_allocation_3"]),
        ("requirement_9", []),
    ],
)
def test_expressions(runner: Runner, expression: str, expected: list[str]) -> None:
    assert ids(runner, expression) == expected


def test_values(runner: Runner) -> None:
    assert runner.expression("count(requirement)").records() == [{"value": 5}]
    assert [r["value"] for r in runner.expression("requirement.priority").records()] == ["high", "medium", "low", "medium", "low"]
    assert runner.expression("component_2.type").records() == [{"value": "component"}]


def test_queries(runner: Runner) -> None:
    assert runner.query("untested_high_priority_requirements").records() == []
    assert runner.query("unallocated_functions").records() == []


def test_generation_rules(runner: Runner) -> None:
    assert sorted(runner.generate("mission")) == ["actor_1", "involves_1", "system_function_2"]
    assert sorted(runner.generate("traceability", (("root", "requirement_1"),))) == [
        "covers_1", "requirement_1", "satisfies_1", "system_function_4", "test_1",
    ]  # fmt: skip
    shown = runner.generate("component_internals", (("root", "component_1"),))
    assert sorted(shown) == [
        "component_1", "component_2", "component_3", "component_4", "component_exchange_1", "component_exchange_2",
    ]  # fmt: skip
    assert "depth" in str(runner.rules.program.diagrams["function_breakdown"].parameters)


@pytest.mark.parametrize(
    ("rule", "arguments", "message"),
    [
        ("traceability", (), "needs a value for parameter 'root'"),
        ("traceability", (("root", "requirement_9"),), "not an element of the model"),
        ("traceability", (("root", "test_1"),), "is a test"),
        ("traceability", (("root", "requirement_1"), ("depth", "2")), "has no parameter 'depth'"),
        ("function_breakdown", (("root", "system_function_1"), ("depth", "deep")), "not a number"),
        ("nothing", (), "unknown generation rule"),
    ],
)
def test_rule_argument_errors(runner: Runner, rule: str, arguments: tuple[tuple[str, str], ...], message: str) -> None:
    with pytest.raises(RuleError, match=message):
        runner.generate(rule, arguments)


def test_default_labels(runner: Runner) -> None:
    assert runner.default_label("requirement_1") == "Brew coffee"
    assert runner.default_label("allocated_to_1") == "allocated_to_1"  # No name: the identifier.
    labels = runner.labels("component_2", "physical_architecture")
    assert [(label.anchor) for label in labels] == ["top", "top_left"]


# --- Static checking ----------------------------------------------------------------------------------------


def resolve_errors(repository: Repository, text: str) -> list[str]:
    metamodel = MetaModel(
        repository.metamodel.path,
        repository.metamodel.types,
        repository.metamodel.attributes,
        rules=[TextSection(text, 1)],
    )
    rules: Rules = load_rules(metamodel)
    return [f"{e.line}:{e.column}: {e.message}" for e in rules.errors]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("query q:\n    select requirment\n", "2:12: unknown name 'requirment'; did you mean 'requirement'?"),
        ("query q:\n    select requirement where priorty = high\n", "2:30: unknown name 'priorty'; did you mean 'priority'?"),
        ("query q:\n    select requirement.start\n", "2:23: 'start' does not apply to requirement"),
        ("query q:\n    select requirement where priority = 3\n", "2:30: cannot compare enumeration values with numbers"),
        ("query q:\n    select requirement where priority > high\n", "2:30: only numbers can be compared with >"),
        ("query q:\n    select function.targets(component)\n", "2:29: 'component' is not a Relationship type"),
        ("query q:\n    select function.descendants(function)\n", "2:33: the depth of 'descendants' must be a number"),
        ("query q:\n    select requirement.priority union test\n", "2:23: 'union' needs elements, not enumeration values"),
        ("define a = b\ndefine b = a\n", "2:12: definitions cannot refer to themselves: a → b → a"),
        ("check c(x: int) (error):\n    for each r in requirement:\n        require r is empty\n        otherwise \"m\"\n",
         "1:9: the parameters of verification rules must have a default"),
        ("diagram d(name: text):\n    show requirement where name = \"x\"\n",
         "2:28: 'name' is both a variable and an attribute of the element; write 'this.name' for the attribute"),
        ("query q:\n    select test\nquery q:\n    select test\n", "3:1: 'q' is defined more than once"),
    ],
)
def test_static_errors(repository: Repository, text: str, expected: str) -> None:
    assert resolve_errors(repository, text) == [expected]


def test_definitions(repository: Repository) -> None:
    text = (
        "define leaves = logical_function where children is empty\n"
        "define allocated(f: logical_function) = f.targets(allocated_to) is not empty\n"
        "query q:\n    select leaves where allocated(this)\n"
    )
    assert resolve_errors(repository, text) == []


# --- Integration ----------------------------------------------------------------------------------------------


@pytest.fixture
def example(tmp_path: Path) -> Path:
    copy = tmp_path / "example"
    shutil.copytree(SIMPLIFIED_ARCADIA, copy)
    return copy


def test_checker_runs_verification_rules(example: Path) -> None:
    covers = example / "model" / "covers.csv"
    covers.write_text(covers.read_text().replace("covers_2;test_2;requirement_2;\n", ""))
    findings = check_repository(load_repository(example))
    assert [(f.severity.value, f.check, f.element, f.path, f.message) for f in findings] == [
        (
            "error", "requirement_covered", "requirement_2", "model/requirement.csv",
            "Requirement Brewing time is verified by test, but is not covered by any test.",
        )
    ]  # fmt: skip


def test_broken_down_requirements_are_not_checked(example: Path) -> None:
    """Brew coffee is broken down into Brew strength and Cup size, so only those need to be covered by a test."""
    covers = example / "model" / "covers.csv"
    covers.write_text(covers.read_text().replace("covers_1;test_1;requirement_1;\n", ""))
    assert check_repository(load_repository(example)) == []


def test_checker_reports_rule_errors(example: Path) -> None:
    metamodel = example / "metamodel.csv"
    metamodel.write_text(metamodel.read_text().replace("for each r in requirement where", "for each r in requirment where"))
    findings = check_repository(load_repository(example))
    lines = [n for n, line in enumerate(metamodel.read_text().split("\n"), 1) if "in requirment where" in line]
    assert len(lines) == 2
    assert [(f.check, f.line, f.column) for f in findings] == [("rules", line, 19) for line in lines]
    assert "did you mean 'requirement'" in findings[0].message


def test_cli_query() -> None:
    output, errors = io.StringIO(), io.StringIO()
    assert run_query(SIMPLIFIED_ARCADIA, "component_1.descendants", [], output, errors) == 0
    assert [json.loads(line)["id"] for line in output.getvalue().splitlines()] == ["component_2", "component_3", "component_4"]
    output = io.StringIO()
    assert run_query(SIMPLIFIED_ARCADIA, "unallocated_functions", [], output, errors) == 0
    assert output.getvalue() == ""
    assert run_query(SIMPLIFIED_ARCADIA, "requirement where", [], output, errors) == 1
    assert errors.getvalue().startswith("<expression>:1:")


def test_generated_parser_is_up_to_date() -> None:
    """If this fails, regenerate the parser with: uv run python -m archtool.language.grammar"""
    from archtool.language.grammar import generate_parser

    generated = Path(__file__).parent.parent / "src" / "archtool" / "language" / "_parser.py"
    assert generated.read_text(encoding="utf-8") == generate_parser()


def test_query_columns_and_order(repository: Repository) -> None:
    text = "query q:\n    select requirement columns id, name, priority order by name descending\n"
    metamodel = MetaModel(repository.metamodel.path, repository.metamodel.types, repository.metamodel.attributes,
                          rules=[TextSection(text, 1)])  # fmt: skip
    result = Runner(load_rules(metamodel), repository.model).query("q")
    assert result.records() == [
        {"id": "requirement_3", "name": "Food-safe materials", "priority": "low"},
        {"id": "requirement_5", "name": "Cup size", "priority": "low"},
        {"id": "requirement_2", "name": "Brewing time", "priority": "medium"},
        {"id": "requirement_4", "name": "Brew strength", "priority": "medium"},
        {"id": "requirement_1", "name": "Brew coffee", "priority": "high"},
    ]
