"""Generate a meta-model file from a model made with the metamodelling meta model.

    uv run python examples/metamodelling/generate_metamodel.py [repository] [-o metamodel.csv]

The repository is the model that defines the meta model; it defaults to the directory of this script. The meta-model
file is written to the output file, or to stdout. Start a model with it with `archtool init <metamodel.csv> <dir>`.

The meta-model file is only written if it is valid: it is read back, with its rules, as the tools would read it, and
any errors are reported with the line of the generated file they are on. Run `archtool check` on the repository
first: its verification rules find most mistakes while modelling, with the elements they concern.
"""

import argparse
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from archtool.errors import FormatError, LexicalError
from archtool.formats.datatypes import parse_datatype
from archtool.formats.tables import format_table, parse_header
from archtool.formats.values import Value
from archtool.identifiers import identifier_key
from archtool.language.runtime import load_rules
from archtool.metamodel import TABLE_HEADERS, load_metamodel
from archtool.model import Element, Model
from archtool.repository import load_repository

# The table of the meta-model file that each type of this meta model's types goes into, in the order of the file.
TYPE_TABLES = {
    "entity_type": "entity_types",
    "port_type": "port_types",
    "relationship_type": "relationship_types",
    "refinement_type": "refinement_types",
    "hierarchy_type": "hierarchy_types",
    "breakdown_type": "relationship_breakdown_types",
    "chain_type": "chain_types",
    "template_type": "template_types",
    "instantiation_type": "instantiation_types",
    "diagram_type": "diagram_types",
}
# The types that diagram types list as `entities`; the others they show are listed as `relationships`.
ENTITY_TYPES = {"entity_type", "port_type", "template_type", "instantiation_type"}
# A row of a table of the meta-model file; None for an empty cell.
type Row = dict[str, Value | None]

RULE_NAME = re.compile(r"\s*(?:define|diagram|check|query)\s+([A-Za-z_][A-Za-z0-9_]*)")


class GenerationError(Exception):
    """The model cannot be turned into a meta-model file. `problems` says why."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


class _Source:
    """Reads the model: names, relationships, and the parts of types."""

    def __init__(self, model: Model) -> None:
        self.model = model
        self.problems: list[str] = []
        self._targets: dict[tuple[str, str], list[str]] = {}
        for relationship in model.elements_of("Relationship"):
            start, end = relationship.values.get("start"), relationship.values.get("end")
            if isinstance(start, str) and isinstance(end, str):
                self._targets.setdefault((relationship.type, start), []).append(end)
        self._parts: dict[str, list[str]] = {}
        for hierarchy in model.elements_of("HierarchyRelationship"):
            parent, child = hierarchy.values.get("parent"), hierarchy.values.get("child")
            if isinstance(parent, str) and isinstance(child, str):
                self._parts.setdefault(child, []).append(parent)

    def name(self, identifier: str) -> str:
        name = self.model.get(identifier).values.get("name")
        if not isinstance(name, str) or not name:
            self.problems.append(f"{identifier} has no name")
            return identifier
        return name

    def text(self, element: Element, attribute: str) -> str | None:
        value = element.values.get(attribute)
        return value if isinstance(value, str) and value else None

    def targets(self, element: Element, relationship: str) -> list[str]:
        """The elements that relationships of a type lead to from an element, in the order they were made."""
        return sorted(self._targets.get((relationship, element.id), []), key=identifier_key)

    def names(self, element: Element, relationship: str) -> tuple[str, ...]:
        return tuple(self.name(target) for target in self.targets(element, relationship))

    def single(self, element: Element, relationship: str) -> str | None:
        names = self.names(element, relationship)
        if len(names) > 1:
            self.problems.append(f"{element.id} has more than one {relationship}: {', '.join(names)}")
        return names[0] if names else None

    def owner(self, element: Element) -> str | None:
        """The name of the type or stereotype that an attribute, label or shape is part of."""
        parents = self._parts.get(element.id, [])
        if not parents:
            self.problems.append(f"{element.id} is not part of a type or stereotype")
            return None
        return self.name(parents[0])

    def rule_name(self, identifier: str) -> str:
        text = self.text(self.model.get(identifier), "text") or ""
        match = RULE_NAME.match(text)
        if match is None:
            self.problems.append(f"{identifier} does not start with define, diagram, check or query, and a name")
            return identifier
        return match.group(1)


def generate_metamodel(model: Model, source_name: str) -> str:
    """The text of the meta-model file that a model defines. Raises GenerationError."""
    source = _Source(model)
    tables: dict[str, list[Row]] = {table: [] for table in TABLE_HEADERS}
    for element_type, table in TYPE_TABLES.items():
        for element in model.elements_of(element_type, include_subtypes=False):
            tables[table].append(_type_row(source, element))
    for level in model.elements_of("abstraction_level"):
        tables["abstraction_levels"].append({
            "name": source.name(level.id), "diagrams": source.names(level, "includes"),
            "description": source.text(level, "description"),
        })  # fmt: skip
    for attribute in model.elements_of("attribute"):
        datatype_text = source.text(attribute, "datatype") or ""
        try:
            datatype = parse_datatype(datatype_text)
        except LexicalError as error:
            source.problems.append(f"{attribute.id}: '{datatype_text}' is not a data type: {error.message}")
            continue
        tables["attributes"].append({
            "type": source.owner(attribute), "name": source.name(attribute.id), "datatype": datatype,
            "required": attribute.values.get("required") is True, "default": source.text(attribute, "default"),
            "description": source.text(attribute, "description"),
        })  # fmt: skip
    for label in model.elements_of("type_label"):
        tables["labels"].append({
            "diagram_type": _diagram_type(source, label), "type": source.owner(label), "text": source.text(label, "text"),
            "anchor": source.text(label, "anchor"),
        })  # fmt: skip
    for shape in model.elements_of("type_shape"):
        tables["shapes"].append({
            "diagram_type": _diagram_type(source, shape), "type": source.owner(shape),
            "shape": source.text(shape, "block_shape"), "start": source.text(shape, "line_start"),
            "end": source.text(shape, "line_end"),
        })  # fmt: skip
    rules = [source.text(rule, "text") or "" for rule in model.elements_of("rule")]
    metamodels = model.elements_of("metamodel")
    if len(metamodels) > 1:
        source.problems.append(f"the model defines more than one meta model: {', '.join(m.id for m in metamodels)}")
    if source.problems:
        raise GenerationError(source.problems)

    metamodel = metamodels[0] if metamodels else None
    title = (source.text(metamodel, "name") if metamodel else None) or "Meta model"
    lines = [f"# {title}", "#"]
    description = source.text(metamodel, "description") if metamodel else None
    if description:
        lines += [f"# {line}".rstrip() for line in description.splitlines()] + ["#"]
    lines += [f"# Generated by generate_metamodel.py from {source_name}: change that model, not this file.", ""]
    for table, rows in tables.items():
        if rows:
            columns = parse_header(TABLE_HEADERS[table], table, 1)
            cells = [{key: value for key, value in row.items() if value is not None} for row in rows]
            lines += [f"@table {table}", *format_table(columns, cells), ""]
    if rules:
        lines += ["@rules", *"\n\n".join(rule.strip("\n") for rule in rules).split("\n"), "@end", ""]
    for section in ("defs", "style"):
        text = source.text(metamodel, section) if metamodel else None
        if text:
            lines += [f"@{section}", *text.strip("\n").split("\n"), "@end", ""]
    return "\n".join(lines)


def _type_row(source: _Source, element: Element) -> Row:
    row: Row = {"name": source.name(element.id), "description": source.text(element, "description")}
    kind = element.type
    if kind in ("entity_type", "port_type", "relationship_type", "refinement_type", "template_type"):
        row["extends"] = source.single(element, "extends")
    if kind == "port_type":
        row["owner"] = source.names(element, "owned_by")
    if kind in ("relationship_type", "refinement_type"):
        row["start"], row["end"] = source.names(element, "starts_at"), source.names(element, "ends_at")
    if kind == "hierarchy_type":
        row["parent"], row["child"] = source.single(element, "has_parent"), source.single(element, "has_child")
    if kind == "breakdown_type":
        row["aggregate"] = source.single(element, "has_aggregate")
        row["constituent"] = source.single(element, "has_constituent")
    if kind == "chain_type":
        row["relationship"] = source.single(element, "chain_of")
    if kind == "instantiation_type":
        row["template"] = source.single(element, "instantiates")
    if kind == "diagram_type":
        shown = source.targets(element, "shows")
        row["kind"] = source.text(element, "kind")
        row["entities"] = tuple(source.name(t) for t in shown if source.model.get(t).type in ENTITY_TYPES)
        row["relationships"] = tuple(source.name(t) for t in shown if source.model.get(t).type not in ENTITY_TYPES)
        row["chains"] = source.names(element, "highlights")
        row["rules"] = tuple(source.rule_name(rule) for rule in source.targets(element, "uses_rule"))
    return row


def _diagram_type(source: _Source, element: Element) -> str | None:
    diagram_type = element.values.get("in_diagram")
    return source.name(diagram_type) if isinstance(diagram_type, str) else None


def validate(text: str) -> list[str]:
    """The errors in a meta-model file, as the tools would report them, each with the line it is on."""
    lines = text.split("\n")
    with tempfile.TemporaryDirectory(prefix="metamodel-") as directory:
        path = Path(directory) / "metamodel.csv"
        path.write_text(text, encoding="utf-8")
        try:
            errors = list(load_rules(load_metamodel(path)).program.errors)
        except FormatError as error:
            errors = [error]
    return [f"line {e.line}, column {e.column}: {e.message}\n    {lines[e.line - 1] if 0 < e.line <= len(lines) else ''}"
            for e in errors]  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a meta-model file from a model made with the metamodelling meta model.")
    parser.add_argument("repository", nargs="?", type=Path, default=Path(__file__).parent,
                        help="the model that defines the meta model (default: the directory of this script)")  # fmt: skip
    parser.add_argument("-o", "--output", type=Path, help="the meta-model file to write (default: stdout)")
    arguments = parser.parse_args(argv)
    try:
        repository = load_repository(arguments.repository)
        text = generate_metamodel(repository.model, arguments.repository.resolve().name)
    except FormatError as error:
        print(f"{error.path}:{error.line}:{error.column}: {error.message}", file=sys.stderr)
        return 1
    except GenerationError as error:
        for problem in error.problems:
            print(problem, file=sys.stderr)
        return 1
    errors = validate(text)
    if errors:
        print("The generated meta model is not valid, so it was not written:", file=sys.stderr)
        for message in errors:
            print(message, file=sys.stderr)
        return 1
    if arguments.output is None:
        sys.stdout.write(text)
    else:
        arguments.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
