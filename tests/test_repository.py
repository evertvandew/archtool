import shutil
from pathlib import Path

import pytest

from archtool.errors import FormatError
from archtool.formats.diagram_file import DiagramFile, Generate
from archtool.model import Element, Reference
from archtool.repository import add_diagram, load_repository, save_repository
from tests.conftest import SIMPLIFIED_ARCADIA


def files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for directory in ("model", "diagrams")
        for path in sorted((root / directory).iterdir())
    }


@pytest.fixture
def example(tmp_path: Path) -> Path:
    """A copy of the simplified Arcadia example, which tests may change."""
    copy = tmp_path / "example"
    shutil.copytree(SIMPLIFIED_ARCADIA, copy)
    return copy


def test_load_example() -> None:
    repository = load_repository(SIMPLIFIED_ARCADIA)
    model = repository.model
    assert len(model) == 87
    assert model.get("requirement_1").values["priority"] == "high"
    assert [e.id for e in model.elements_of("function")] == [
        "logical_function_1", "logical_function_2", "logical_function_3", "logical_function_4",
        "system_function_1", "system_function_2", "system_function_3", "system_function_4",
    ]  # fmt: skip
    assert model.get("functional_chain_1").values["relationships"] == ("functional_exchange_2", "functional_exchange_3")
    assert sorted(model.diagrams) == sorted(e.id for name in repository.diagram_tables for e in model.elements_of(name))


def test_round_trip_is_byte_identical(tmp_path: Path) -> None:
    """The example is in canonical form: loading and saving it reproduces every file exactly."""
    repository = load_repository(SIMPLIFIED_ARCADIA)
    save_repository(repository, tmp_path)
    assert files(tmp_path) == files(SIMPLIFIED_ARCADIA)


def test_saving_an_unchanged_model_does_not_touch_files(example: Path) -> None:
    times = {path: path.stat().st_mtime_ns for path in example.rglob("*")}
    save_repository(load_repository(example))
    assert {path: path.stat().st_mtime_ns for path in example.rglob("*")} == times


def test_referrers() -> None:
    model = load_repository(SIMPLIFIED_ARCADIA).model
    assert model.referrers("requirement_1") == [
        Reference("covers_1", "end"), Reference("requirement_contains_requirement_1", "parent"),
        Reference("requirement_contains_requirement_2", "parent"), Reference("satisfies_1", "end"),
    ]  # fmt: skip
    assert Reference("functional_chain_1", "relationships") in model.referrers("functional_exchange_2")


def test_add_and_remove_elements(example: Path) -> None:
    repository = load_repository(example)
    model = repository.model
    identifier = model.new_identifier("requirement")
    assert identifier == "requirement_6"
    model.add(Element(identifier, "requirement", {"name": "Descale", "priority": "low"}))
    model.remove("requirement_3")
    save_repository(repository)
    text = (example / "model" / "requirement.csv").read_text()
    assert text.startswith("@last_number 6\n")
    assert "requirement_3;" not in text
    assert text.endswith("requirement_6;Descale;;low;\n")
    # Numbers are never reused, even after the element with the highest number is deleted.
    reloaded = load_repository(example)
    reloaded.model.remove("requirement_6")
    assert reloaded.model.new_identifier("requirement") == "requirement_7"


def test_set_value_updates_references(example: Path) -> None:
    model = load_repository(example).model
    model.set_value("covers_1", "end", "requirement_2")
    assert Reference("covers_1", "end") not in model.referrers("requirement_1")
    assert Reference("covers_1", "end") in model.referrers("requirement_2")


def test_tables_record_numbers_above_last_number(example: Path) -> None:
    """Rows added by hand without updating @last_number cannot cause a number to be reused."""
    path = example / "model" / "actor.csv"
    path.write_text(path.read_text() + "actor_5;Barista\n")
    model = load_repository(example).model
    assert model.new_identifier("actor") == "actor_6"


def test_diagrams_are_added_and_removed(example: Path) -> None:
    repository = load_repository(example)
    identifier = repository.model.new_identifier("mission")
    add_diagram(
        repository,
        Element(identifier, "mission", {"name": "Second mission"}),
        DiagramFile(identifier, "mission", [Generate("mission")]),
    )
    del repository.model.diagrams["allocation_1"]
    repository.model.remove("allocation_1")
    save_repository(repository)
    assert (example / "diagrams" / "mission_2.diag").read_text() == "@diagram mission_2 : mission\ngenerate mission\n@end\n"
    assert not (example / "diagrams" / "allocation_1.diag").exists()
    assert (example / "diagrams" / "allocation.csv").read_text() == "@last_number 1\nid:id;name:str\n"


@pytest.mark.parametrize(
    ("file", "change", "message"),
    [
        ("model/actor.csv", ("actor_1;User", "actor_1;User;extra"), "the row has 3 cells"),
        ("model/actor.csv", ("name:str\nactor_1;User", "name:str;age:int\nactor_1;User;30"), "has no attribute 'age'"),
        ("model/actor.csv", ("id:id;name:str", "id:id;name:text"), "must be 'name:str'"),
        ("model/actor.csv", ("actor_1;", "test_7;"), "does not belong to type 'actor'"),
        ("diagrams/mission_1.diag", ("mission_1 : mission", "mission_1 : allocation"), "is of type 'mission'"),
    ],
)
def test_errors(example: Path, file: str, change: tuple[str, str], message: str) -> None:
    path = example / file
    path.write_text(path.read_text().replace(*change))
    with pytest.raises(FormatError, match=message):
        load_repository(example)


def test_unknown_table(example: Path) -> None:
    (example / "model" / "printer.csv").write_text("@last_number 0\nid:id\n")
    with pytest.raises(FormatError, match="no type 'printer'"):
        load_repository(example)


def test_missing_core_column(example: Path) -> None:
    (example / "model" / "function_port.csv").write_text("@last_number 1\nid:id;name:str\nfunction_port_1;Start\n")
    with pytest.raises(FormatError, match="must have a column 'owner'"):
        load_repository(example)


def test_missing_diagram_file(example: Path) -> None:
    (example / "diagrams" / "mission_1.diag").unlink()
    with pytest.raises(FormatError, match="has no diagram file"):
        load_repository(example)
