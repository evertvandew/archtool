"""The metamodelling example, and its script that generates a meta-model file from a model."""

import importlib.util
import io
import shutil
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType

import pytest

from archtool.checker import check_repository
from archtool.cli import run_edit
from archtool.init import init_repository
from archtool.language.runtime import Runner, load_rules
from archtool.metamodel import Stereotype, load_metamodel
from archtool.repository import load_repository, save_repository
from tests.conftest import EXAMPLES

METAMODELLING = EXAMPLES / "metamodelling"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_metamodel", METAMODELLING / "generate_metamodel.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def example(tmp_path: Path) -> Path:
    copy = tmp_path / "metamodelling"
    shutil.copytree(METAMODELLING, copy, ignore=shutil.ignore_patterns("__pycache__"))
    return copy


def run(script: ModuleType, *arguments: str) -> tuple[int, str, str]:
    output, errors = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        status = script.main(list(arguments))
    return status, output.getvalue(), errors.getvalue()


def test_example_has_no_findings() -> None:
    assert check_repository(load_repository(METAMODELLING)) == []


def test_example_is_canonical(tmp_path: Path) -> None:
    save_repository(load_repository(METAMODELLING), tmp_path)
    for path in tmp_path.rglob("*.*"):
        assert path.read_bytes() == (METAMODELLING / path.relative_to(tmp_path)).read_bytes(), path


def test_generated_metamodel(script: ModuleType, tmp_path: Path) -> None:
    output = tmp_path / "blocks.csv"
    assert run(script, str(METAMODELLING), "-m", "metamodel_1", "-o", str(output)) == (0, "", "")
    metamodel = load_metamodel(output)
    assert load_rules(metamodel).program.errors == []
    stereotypes = {name: t.stereotype for name, t in metamodel.types.items()}
    assert stereotypes == {
        "requirement": Stereotype.ENTITY, "block": Stereotype.ENTITY, "flow_port": Stereotype.PORT,
        "flow": Stereotype.RELATIONSHIP, "satisfies": Stereotype.RELATIONSHIP,
        "block_contains_block": Stereotype.HIERARCHY_RELATIONSHIP,
        "requirement_contains_requirement": Stereotype.HIERARCHY_RELATIONSHIP, "flow_path": Stereotype.CHAIN,
        "internal_block": Stereotype.BLOCK_DIAGRAM, "requirement_tree": Stereotype.BREAKDOWN_DIAGRAM,
        "satisfaction": Stereotype.BLOCK_DIAGRAM,
    }  # fmt: skip
    text = output.read_text()
    assert text.startswith("# Blocks and requirements\n#\n# A small meta model")
    assert "\nflow_port;;[block];A port through which a block sends or receives a flow.\n" in text
    assert "\ninternal_block;block;[block,flow_port];[block_contains_block,flow];[flow_path];[internals];" in text
    assert "\nrequirement;priority;enum(high|medium|low);false;medium;\n" in text
    assert "\ninternal_block;block;«block»;top_left\n" in text
    assert "\n@rules\ndiagram internals(root: block, depth: int = 1):\n" in text
    assert "\n@style\n.Entity > .label" in text
    # Without an output file, the meta model is written to stdout.
    assert run(script, str(METAMODELLING), "-m", "Blocks and requirements") == (0, text, "")


def test_model_with_generated_metamodel(script: ModuleType, tmp_path: Path) -> None:
    run(script, str(METAMODELLING), "-m", "metamodel_1", "-o", str(tmp_path / "blocks.csv"))
    root = tmp_path / "model"
    init_repository(root, tmp_path / "blocks.csv")
    commands = (
        'add requirement name="Make coffee" text="The machine shall make coffee."\n'
        'add block name="Coffee machine"\n'
        'add block name="Boiler" parent=block_1\n'
        "add flow_port owner=block_2 direction=output\n"
        'add internal_block name="Coffee machine" generate="internals(root=block_1)"\n'
    )
    output = io.StringIO()
    assert run_edit(root, io.StringIO(commands), output, io.StringIO()) == 0
    findings = check_repository(load_repository(root))
    # The rule of the generated meta model is applied.
    assert [(f.check, f.element) for f in findings] == [("requirement_satisfied", "requirement_1")]


def test_invalid_metamodel_is_not_written(script: ModuleType, example: Path, tmp_path: Path) -> None:
    rules = example / "model" / "rule.csv"
    rules.write_text(rules.read_text().replace("show satisfies to root", "show satisfy to root"))
    output = tmp_path / "blocks.csv"
    status, _, errors = run(script, str(example), "-m", "metamodel_1", "-o", str(output))
    assert status == 1 and not output.exists()
    assert "The generated meta model is not valid, so it was not written:" in errors
    assert "unknown name 'satisfy'" in errors and "    show satisfy to root" in errors


def test_problems_in_the_model(script: ModuleType, example: Path) -> None:
    types = example / "model" / "entity_type.csv"
    types.write_text(types.read_text().replace("entity_type_2;block;", "entity_type_2;;"))
    status, output, errors = run(script, str(example), "-m", "metamodel_1")
    assert status == 1 and output == ""
    assert "entity_type_2 has no name" in errors
    # The model's own verification rules find it too.
    assert ("type_name", "entity_type_2") in [(f.check, f.element) for f in check_repository(load_repository(example))]


def test_several_metamodels(script: ModuleType, tmp_path: Path) -> None:
    status, output, errors = run(script, str(METAMODELLING))
    assert (status, output) == (1, "")
    assert errors == (
        "the model defines several meta models, so choose one with --metamodel: "
        "metamodel_1 (Blocks and requirements), metamodel_2 (State machines)\n"
    )
    assert "there is no meta model called 'Petri nets'" in run(script, str(METAMODELLING), "-m", "Petri nets")[2]
    assert run(script, str(METAMODELLING), "-m", "State machines", "-o", str(tmp_path / "states.csv"))[0] == 0
    metamodel = load_metamodel(tmp_path / "states.csv")
    assert list(metamodel.types) == ["state", "transition", "state_contains_state", "state_machine"]
    text = (tmp_path / "states.csv").read_text()
    # The stereotypes, with their attribute, label and shapes, are shared with Blocks and requirements.
    assert "\nEntity;name;str;false;;The name of the element.\n" in text and "\n;Entity;{name};\n" in text
    assert "\n;Relationship;;none;arrow\n" in text
    assert "flow_port" not in text and "requirement" not in text


def test_type_overview_per_metamodel() -> None:
    repository = load_repository(METAMODELLING)
    runner = Runner(load_rules(repository.metamodel), repository.model)
    shown = runner.generate("type_overview", (("root", "metamodel_2"),))
    assert sorted(shown) == ["ends_at_3", "entity_type_3", "has_child_3", "has_parent_3", "hierarchy_type_3",
                             "relationship_type_3", "starts_at_3"]  # fmt: skip


def test_everything_belongs_to_a_metamodel(example: Path) -> None:
    belongs_to = example / "model" / "belongs_to.csv"
    belongs_to.write_text("\n".join(line for line in belongs_to.read_text().split("\n") if ";rule_6;" not in line))
    findings = check_repository(load_repository(example))
    assert [(f.check, f.element, f.message) for f in findings] == [
        ("belongs_to_a_metamodel", "rule_6", "transition_trigger must belong to a meta model.")
    ]


def test_links_stay_within_metamodels(script: ModuleType, example: Path) -> None:
    """A transition from a block: the block does not belong to State machines."""
    run_edit(example, io.StringIO("connect starts_at start=relationship_type_3 end=entity_type_2\n"), io.StringIO(), io.StringIO())
    findings = check_repository(load_repository(example))
    assert [(f.check, f.element) for f in findings] == [("links_within_metamodels", "starts_at_4")]
    assert findings[0].message == (
        "transition is linked to block by starts_at, so block must belong to every meta model that transition belongs to."
    )
    status, _, errors = run(script, str(example), "-m", "metamodel_2")
    assert status == 1
    assert errors == (
        "relationship_type_3 refers to entity_type_2 (starts_at), which does not belong to metamodel_2; "
        "let it belong to metamodel_2 as well\n"
    )
