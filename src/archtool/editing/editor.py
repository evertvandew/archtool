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

"""The editing engine: executes commands on a model, and writes the changes to its files.

Each command is validated completely before the model is changed, so that a command either succeeds as a whole or
leaves the model untouched. Changes are propagated where they can be: deleting an element also deletes the elements
that cannot exist without it. After each command, the model is checked, and new findings are reported as issues.
See "Command interface" in doc/architecture.md.
"""

import difflib
from collections.abc import Iterable
from dataclasses import dataclass, field

from archtool.checker import Finding, check_repository
from archtool.editing.commands import Command, RawValue, parse_command
from archtool.errors import FormatError, LexicalError
from archtool.formats.datatypes import ListType, RefType, SimpleType
from archtool.formats.diagram_file import (
    DiagramFile,
    Generate,
    Highlight,
    Layout,
    Message,
    Participant,
    Process,
    Show,
    Statement,
    Style,
    read_diagram_file,
)
from archtool.formats.escaping import escape
from archtool.formats.tables import Column
from archtool.formats.values import Value, parse_cell
from archtool.identifiers import identifier_key, split_identifier
from archtool.language.runtime import load_rules
from archtool.metamodel import Stereotype, TypeDef
from archtool.model import Element
from archtool.repository import Repository, add_diagram, save_repository

# Core attributes whose element cannot exist without the element they refer to.
_CASCADE_COLUMNS = frozenset({"owner", "start", "end", "parent", "child", "aggregate", "constituent"})

COMMANDS = ("add", "connect", "set", "move", "delete", "show", "hide", "add_chain")


class CommandError(Exception):
    """A command that cannot be executed. The model is left unchanged."""


@dataclass(slots=True)
class Result:
    ok: bool
    command: str
    line: int = 0
    created: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    issues: list[Finding] = field(default_factory=list)  # Findings that the command introduced.
    resolved: list[Finding] = field(default_factory=list)  # Findings that the command resolved.
    error: str | None = None

    def to_json(self) -> dict[str, object]:
        result: dict[str, object] = {"ok": self.ok, "line": self.line, "command": self.command}
        if self.error is not None:
            result["error"] = self.error
            return result
        result |= {
            "created": self.created,
            "changed": self.changed,
            "deleted": self.deleted,
            "issues": [issue.to_json() for issue in self.issues],
            "resolved": [finding.to_json() for finding in self.resolved],
        }
        return result


class Editor:
    def __init__(self, repository: Repository, *, save: bool = True) -> None:
        self.repository = repository
        self.model = repository.model
        self.metamodel = repository.metamodel
        self.rules = load_rules(repository.metamodel)
        self.save = save
        self._findings = set(check_repository(repository, self.rules))

    @property
    def findings(self) -> list[Finding]:
        """The current findings of the model."""
        return sorted(self._findings, key=_finding_key)

    # --- Running commands ----------------------------------------------------------------------------------

    def run(self, text: str, line: int = 0) -> Result | None:
        """Parse and execute a command line. Returns None for a blank line or a comment."""
        try:
            command = parse_command(text, line)
        except LexicalError as error:
            return Result(False, text.split(" ", 1)[0], line, error=error.message)
        if command is None:
            return None
        return self.execute(command)

    def execute(self, command: Command) -> Result:
        result = Result(True, command.name, command.line)
        try:
            match command.name:
                case "add":
                    self.add_element(command, result, relationship=False)
                case "connect":
                    self.add_element(command, result, relationship=True)
                case "set":
                    self.set_values(command, result)
                case "move":
                    self.move_element(command, result)
                case "delete":
                    self.delete_elements(command, result)
                case "show" | "hide":
                    self.show_elements(command, result, show=command.name == "show")
                case "add_chain":
                    self.add_chain(command, result)
                case _:
                    raise CommandError(f"unknown command '{command.name}'{_suggestion(command.name, COMMANDS)}")
        except CommandError as error:
            return Result(False, command.name, command.line, error=str(error))
        result.created.sort(key=identifier_key)
        result.changed = sorted(set(result.changed) - set(result.created) - set(result.deleted), key=identifier_key)
        result.deleted.sort(key=identifier_key)
        if self.save:
            save_repository(self.repository)
        findings = set(check_repository(self.repository, self.rules))
        result.issues = sorted(findings - self._findings, key=_finding_key)
        result.resolved = sorted(self._findings - findings, key=_finding_key)
        self._findings = findings
        return result

    # --- add and connect -----------------------------------------------------------------------------------

    def add_element(self, command: Command, result: Result, *, relationship: bool) -> None:
        type_name = self._single(command, "a type")
        type_def = self._type(type_name)
        if relationship and Stereotype.RELATIONSHIP not in type_def.stereotype.chain():
            raise CommandError(f"'{type_name}' is not a relationship type; use 'add' for other elements")
        if type_def.stereotype.is_diagram():
            self._add_diagram(type_def, command, result)
            return
        keywords = dict(command.keywords)
        parent = keywords.pop("parent", None)
        hierarchy = keywords.pop("hierarchy", None)
        values = self._values(type_name, keywords)
        for column in self.metamodel.core_columns(type_name)[1:]:
            if column.name not in values:
                raise CommandError(f"'{column.name}' is required for a {type_name}")
        parent_id = parent.text if parent is not None and parent.text else None
        hierarchy_type = self._hierarchy_type(parent_id, type_name, hierarchy) if parent_id else None
        # Validated: now change the model.
        identifier = self.model.new_identifier(type_name)
        self.model.add(Element(identifier, type_name, values))
        result.created.append(identifier)
        if parent_id is not None and hierarchy_type is not None:
            result.created.append(self._add_hierarchy(hierarchy_type, parent_id, identifier))

    def _add_diagram(self, type_def: TypeDef, command: Command, result: Result) -> None:
        keywords = dict(command.keywords)
        generate = keywords.pop("generate", None)
        values = self._values(type_def.name, keywords)
        statements: list[Statement] = []
        if generate is not None:
            statement = self._generate(type_def, generate.text)
            statements.append(statement)
        identifier = self.model.new_identifier(type_def.name)
        add_diagram(self.repository, Element(identifier, type_def.name, values), DiagramFile(identifier, type_def.name, statements))
        result.created.append(identifier)

    def _generate(self, type_def: TypeDef, text: str) -> Generate:
        try:
            diagram = read_diagram_file(f"@diagram {type_def.name}_1 : {type_def.name}\ngenerate {text}\n@end\n", "<command>")
        except FormatError as error:
            raise CommandError(f"'generate': {error.message}") from None
        statement = diagram.statements[0]
        assert isinstance(statement, Generate)
        rules = self._names(type_def.name, "rules")
        if statement.rule not in rules:
            raise CommandError(f"'{statement.rule}' is not a generation rule of {type_def.name}{_suggestion(statement.rule, rules)}")
        rule = self.rules.program.diagrams.get(statement.rule)
        parameters = {p.ident: p for p in rule.parameters} if rule is not None else {}
        given = dict(statement.arguments)
        for name, value in statement.arguments:
            if name not in parameters:
                raise CommandError(f"'generate': rule '{statement.rule}' has no parameter '{name}'")
            if split_identifier(value) is not None and value not in self.model:
                raise CommandError(f"'generate': {value} does not exist")
        for name, parameter in parameters.items():
            if parameter.default is None and name not in given:
                raise CommandError(f"'generate': rule '{statement.rule}' needs a value for '{name}'")
        return statement

    # --- set and move --------------------------------------------------------------------------------------

    def set_values(self, command: Command, result: Result) -> None:
        element = self._element(self._single(command, "an element"))
        if "parent" in command.keywords and self._stereotype(element) is not Stereotype.HIERARCHY_RELATIONSHIP:
            raise CommandError("use 'move' to change the parent of an element")
        if not command.keywords:
            raise CommandError("nothing to set: give key=value arguments")
        values = self._values(element.type, command.keywords, allow_clear=True)
        for key in command.keywords:
            if values.get(key) is None and key in self._core(element.type):
                raise CommandError(f"'{key}' cannot be cleared")
        for key in command.keywords:
            self.model.set_value(element.id, key, values.get(key))
        result.changed.append(element.id)

    def move_element(self, command: Command, result: Result) -> None:
        element = self._element(self._single(command, "an element"))
        if "parent" not in command.keywords:
            raise CommandError("give the new parent: parent=<id>, or parent= to make it a top-level element")
        unknown = set(command.keywords) - {"parent", "hierarchy"}
        if unknown:
            raise CommandError(f"'move' has no argument '{sorted(unknown)[0]}'")
        parent_text = command.keywords["parent"].text
        hierarchy_type = None
        if parent_text:
            self._element(parent_text)
            if parent_text == element.id or element.id in self._ancestors(parent_text):
                raise CommandError(f"{element.id} cannot be moved into itself or one of its descendants")
            hierarchy_type = self._hierarchy_type(parent_text, element.type, command.keywords.get("hierarchy"))
        # Validated: now change the model.
        for relationship in self._hierarchy_relationships(element.id):
            self.model.remove(relationship)
            result.deleted.append(relationship)
        if parent_text and hierarchy_type is not None:
            result.created.append(self._add_hierarchy(hierarchy_type, parent_text, element.id))

    # --- delete --------------------------------------------------------------------------------------------

    def delete_elements(self, command: Command, result: Result) -> None:
        if command.keywords:
            raise CommandError("'delete' takes no key=value arguments")
        if not command.positional:
            raise CommandError("give the elements to delete")
        for identifier in command.positional:
            self._element(identifier)
        deleted, removals = self._deletion(command.positional)
        blocked = sorted({source for source, column, _ in removals if column == "template" and source not in deleted})
        if blocked:
            users = ", ".join(blocked)
            raise CommandError(f"cannot delete a template that is still used, by {users}; delete those first")
        # Validated: now change the model.
        for source, column, _ in removals:
            if source in deleted:
                continue
            value = self.model.get(source).values.get(column)
            if isinstance(value, tuple):
                remaining = tuple(item for item in value if item not in deleted)
                self.model.set_value(source, column, remaining or None)
            else:
                self.model.set_value(source, column, None)
            result.changed.append(source)
        for identifier, diagram in self.model.diagrams.items():
            if identifier in deleted:
                continue
            kept = [s for s in diagram.statements if not set(_references(s)) & deleted]
            if len(kept) != len(diagram.statements):
                diagram.statements = kept
                result.changed.append(identifier)
        for identifier in sorted(deleted, key=identifier_key):
            self.model.remove(identifier)
            self.model.diagrams.pop(identifier, None)
            result.deleted.append(identifier)

    def _deletion(self, identifiers: Iterable[str]) -> tuple[set[str], list[tuple[str, str, str]]]:
        """The elements to delete: the given ones, and those that cannot exist without them. Also the references
        to deleted elements that must be removed from elements that remain: (source, column, target)."""
        deleted: set[str] = set()
        removals: list[tuple[str, str, str]] = []
        queue = list(identifiers)
        while queue:
            identifier = queue.pop()
            if identifier in deleted:
                continue
            deleted.add(identifier)
            for reference in self.model.referrers(identifier):
                if reference.column in _CASCADE_COLUMNS:
                    queue.append(reference.source)
                else:
                    removals.append((reference.source, reference.column, identifier))
        return deleted, removals

    # --- Diagrams ------------------------------------------------------------------------------------------

    def show_elements(self, command: Command, result: Result, *, show: bool) -> None:
        if command.keywords:
            raise CommandError(f"'{command.name}' takes no key=value arguments")
        if len(command.positional) < 2:
            raise CommandError(f"give a diagram, and the elements to {command.name}")
        diagram = self._diagram(command.positional[0])
        type_def = self.metamodel.types[diagram.type]
        if type_def.stereotype is Stereotype.SEQUENCE_DIAGRAM:
            raise CommandError("sequence diagrams have participants and messages; use 'add_chain'")
        if any(isinstance(s, Generate) for s in diagram.statements):
            raise CommandError(f"{diagram.id} is generated; its contents follow from its generation rule")
        allowed = self._names(diagram.type, "entities") + self._names(diagram.type, "relationships")
        elements = [self._element(identifier) for identifier in command.positional[1:]]
        if show:
            for element in elements:
                if not any(self.metamodel.is_a(element.type, name) for name in allowed):
                    raise CommandError(f"a {diagram.type} cannot show {element.id}, which is a {element.type}")
        # Validated: now change the diagram.
        targets = {element.id for element in elements}
        if show:
            present = {s.element for s in diagram.statements if isinstance(s, Show)}
            diagram.statements += [Show(e.id) for e in elements if e.id not in present]
        else:
            diagram.statements = [
                s for s in diagram.statements if not (isinstance(s, (Show, Layout, Style)) and s.element in targets)
            ]
        result.changed.append(diagram.id)

    def add_chain(self, command: Command, result: Result) -> None:
        if command.keywords or len(command.positional) != 2:
            raise CommandError("give a sequence diagram and a chain: add_chain <diagram> <chain>")
        diagram = self._diagram(command.positional[0])
        if self.metamodel.types[diagram.type].stereotype is not Stereotype.SEQUENCE_DIAGRAM:
            raise CommandError(f"{diagram.id} is not a sequence diagram")
        chain = self._element(command.positional[1])
        chain_types = self._names(diagram.type, "chains")
        if not any(self.metamodel.is_a(chain.type, name) for name in chain_types):
            if not chain_types:
                raise CommandError(f"a {diagram.type} cannot show chains")
            raise CommandError(f"a {diagram.type} can only show chains of type {' or '.join(chain_types)}")
        relationships = chain.values.get("relationships", ())
        assert isinstance(relationships, tuple)
        # The participants of the messages are added when they are missing.
        participants = [s.element for s in diagram.statements if isinstance(s, Participant)]
        added: list[Statement] = []
        for relationship in relationships:
            for end in ("start", "end"):
                owner = self._owner(str(relationship), end)
                if owner is not None and owner not in participants:
                    participants.append(owner)
                    added.append(Participant(owner))
        diagram.statements += added + [Message(str(r)) for r in relationships]
        result.changed.append(diagram.id)

    # --- Helpers -------------------------------------------------------------------------------------------

    def _single(self, command: Command, what: str) -> str:
        if len(command.positional) != 1:
            raise CommandError(f"'{command.name}' takes {what}, followed by key=value arguments")
        return command.positional[0]

    def _type(self, name: str) -> TypeDef:
        type_def = self.metamodel.types.get(name)
        if type_def is None:
            raise CommandError(f"unknown type '{name}'{_suggestion(name, self.metamodel.types)}")
        return type_def

    def _element(self, identifier: str) -> Element:
        if identifier not in self.model:
            raise CommandError(f"{identifier} does not exist")
        return self.model.get(identifier)

    def _diagram(self, identifier: str) -> DiagramFile:
        self._element(identifier)
        if identifier not in self.model.diagrams:
            raise CommandError(f"{identifier} is not a diagram")
        return self.model.diagrams[identifier]

    def _stereotype(self, element: Element) -> Stereotype:
        return self.metamodel.types[element.type].stereotype

    def _core(self, type_name: str) -> set[str]:
        return {column.name for column in self.metamodel.core_columns(type_name)}

    def _names(self, type_name: str, key: str) -> list[str]:
        value = self.metamodel.property(type_name, key)
        if isinstance(value, tuple):
            return [str(item) for item in value]
        return [value] if isinstance(value, str) else []

    def _values(self, type_name: str, keywords: dict[str, RawValue], *, allow_clear: bool = False) -> dict[str, Value]:
        """Convert `key=value` arguments to the values of an element of a type, and validate them."""
        columns = {column.name: column for column in self.metamodel.columns(type_name)}
        values: dict[str, Value] = {}
        for key, raw in keywords.items():
            column = columns.get(key)
            if column is None or key == "id":
                candidates = [name for name in columns if name != "id"]
                raise CommandError(f"a {type_name} has no attribute '{key}'{_suggestion(key, candidates)}")
            value = self._convert(column, raw)
            if value is None:
                if not allow_clear:
                    continue
            else:
                self._check_references(column, value)
                values[key] = value
        return values

    def _convert(self, column: Column, raw: RawValue) -> Value | None:
        datatype = column.datatype
        if raw.quoted and isinstance(datatype, SimpleType) and datatype.kind in ("str", "text"):
            if datatype.kind == "str" and "\n" in raw.text:
                raise CommandError(f"'{column.name}': line breaks are only allowed in text values")
            return raw.text or None
        text = escape(raw.text) if raw.quoted else raw.text
        try:
            return parse_cell(text, datatype)
        except LexicalError as error:
            raise CommandError(f"'{column.name}': {error.message}") from None

    def _check_references(self, column: Column, value: Value) -> None:
        datatype = column.datatype.element if isinstance(column.datatype, ListType) else column.datatype
        if not isinstance(datatype, RefType):
            return
        for target in value if isinstance(value, tuple) else (value,):
            target = str(target)
            if target not in self.model:
                raise CommandError(f"'{column.name}': {target} does not exist")
            target_type = self.model.get(target).type
            if not any(self.metamodel.is_a(target_type, name) for name in datatype.targets):
                raise CommandError(f"'{column.name}': {target} is a {target_type}, not a {' or '.join(datatype.targets)}")

    def _hierarchy_type(self, parent: str, child_type: str, given: RawValue | None) -> str:
        parent_type = self._element(parent).type
        candidates = [
            name for name, type_def in self.metamodel.types.items()
            if type_def.stereotype is Stereotype.HIERARCHY_RELATIONSHIP
            and self.metamodel.is_a(parent_type, self._names(name, "parent")[0])
            and self.metamodel.is_a(child_type, self._names(name, "child")[0])
        ]  # fmt: skip
        if given is not None:
            if given.text not in candidates:
                raise CommandError(f"'{given.text}' cannot place a {child_type} in a {parent_type}")
            return given.text
        if not candidates:
            raise CommandError(f"the meta model has no hierarchy in which a {child_type} can be part of a {parent_type}")
        if len(candidates) > 1:
            raise CommandError(f"choose the hierarchy with hierarchy=<type>: {', '.join(candidates)}")
        return candidates[0]

    def _add_hierarchy(self, hierarchy_type: str, parent: str, child: str) -> str:
        identifier = self.model.new_identifier(hierarchy_type)
        self.model.add(Element(identifier, hierarchy_type, {"parent": parent, "child": child}))
        return identifier

    def _hierarchy_relationships(self, child: str) -> list[str]:
        return [r.source for r in self.model.referrers(child) if r.column == "child"]

    def _ancestors(self, identifier: str) -> set[str]:
        result: set[str] = set()
        current = [identifier]
        while current:
            parents = [
                str(self.model.get(r).values["parent"]) for c in current for r in self._hierarchy_relationships(c)
                if "parent" in self.model.get(r).values
            ]  # fmt: skip
            current = [p for p in parents if p not in result]
            result.update(current)
        return result

    def _owner(self, relationship: str, end: str) -> str | None:
        value = self.model.get(relationship).values.get(end)
        if not isinstance(value, str) or value not in self.model:
            return None
        element = self.model.get(value)
        if self._stereotype(element) is Stereotype.PORT:
            owner = element.values.get("owner")
            return owner if isinstance(owner, str) else None
        return value


def _references(statement: Statement) -> list[str]:
    match statement:
        case Show(element) | Participant(element) | Layout(element) | Style(element):
            return [element]
        case Highlight(chain):
            return [chain]
        case Message(relationship):
            return [relationship]
        case Process(element, participant):
            return [element, participant]
        case Generate():
            return []


def _finding_key(finding: Finding) -> tuple[str, tuple[str, int], str, str]:
    element = identifier_key(finding.element) if finding.element else ("", 0)
    return finding.path or "", element, finding.check, finding.message


def _suggestion(name: str, candidates: Iterable[str]) -> str:
    matches = difflib.get_close_matches(name, sorted(set(candidates)), n=1)
    return f"; did you mean '{matches[0]}'?" if matches else ""
