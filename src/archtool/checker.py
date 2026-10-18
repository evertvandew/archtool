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

"""The model checker: checks a concrete model against its meta model, and reports all findings.

Syntax errors are found while loading a repository; this module checks what can only be checked once the
whole model is loaded, and evaluates the verification rules of the meta model.
See "Model checker" in doc/architecture.md.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum

from archtool.errors import LexicalError
from archtool.formats.datatypes import ListType, RefType
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
)
from archtool.formats.escaping import escape
from archtool.formats.values import Argument, Parameter, parse_scalar
from archtool.identifiers import identifier_key, split_identifier
from archtool.language.runtime import Rules, Runner, load_rules
from archtool.metamodel import MetaModel, Stereotype
from archtool.model import Element, Model
from archtool.repository import DIAGRAM_DIRECTORY, MODEL_DIRECTORY, Repository


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    check: str
    message: str
    element: str | None = None
    path: str | None = None
    line: int | None = None
    column: int | None = None

    def to_json(self) -> dict[str, str | int]:
        """The finding as a JSON object, without the fields that have no value."""
        result: dict[str, str | int] = {"severity": self.severity.value, "check": self.check}
        for key, value in (("element", self.element), ("path", self.path), ("line", self.line), ("column", self.column)):
            if value is not None:
                result[key] = value
        result["message"] = self.message
        return result


def check_repository(repository: Repository, rules: Rules | None = None) -> list[Finding]:
    """All findings for a loaded repository, sorted by file and element. `rules` are the loaded rules of its meta
    model; by default they are loaded from the meta model."""
    checker = _Checker(repository, rules if rules is not None else load_rules(repository.metamodel))
    findings = [
        *checker.check_elements(),
        *checker.check_hierarchy(),
        *checker.check_diagrams(),
        *checker.check_rules(),
    ]
    return sorted(findings, key=lambda f: (f.path or "", identifier_key(f.element) if f.element else ("", 0)))


class _Checker:
    def __init__(self, repository: Repository, rules: Rules) -> None:
        self.model: Model = repository.model
        self.metamodel: MetaModel = repository.metamodel
        self.rules = rules

    def path(self, element: Element) -> str:
        directory = DIAGRAM_DIRECTORY if self.stereotype(element).is_diagram() else MODEL_DIRECTORY
        return f"{directory}/{element.type}.csv"

    def stereotype(self, element: Element) -> Stereotype:
        return self.metamodel.types[element.type].stereotype

    def error(self, element: Element, check: str, message: str, *, path: str | None = None) -> Finding:
        return Finding(Severity.ERROR, check, message, element.id, path or self.path(element))

    # --- Verification rules ------------------------------------------------------------------------------

    def check_rules(self) -> Iterator[Finding]:
        for error in self.rules.errors:
            yield Finding(Severity.ERROR, "rules", error.message, None, error.path, error.line, error.column)
        if self.rules.errors:
            return
        for result in Runner(self.rules, self.model).checks():
            element = self.model.get(result.element)
            yield Finding(Severity(result.severity), result.rule, result.message, element.id, self.path(element))

    # --- Elements ------------------------------------------------------------------------------------------

    def check_elements(self) -> Iterator[Finding]:
        for element in self.model.elements():
            yield from self.check_required(element)
            yield from self.check_references(element)
            if self.stereotype(element) is Stereotype.TEMPLATE_ENTITY:
                yield from self.check_parameters(element)
            if self.stereotype(element) is Stereotype.INSTANTIATION_ENTITY:
                yield from self.check_arguments(element)

    def check_required(self, element: Element) -> Iterator[Finding]:
        required = [column.name for column in self.metamodel.core_columns(element.type)[1:]]
        required += [a.name for a in self.metamodel.attributes_of(element.type) if a.required]
        for name in required:
            if name not in element.values:
                yield self.error(element, "required", f"'{name}' is required")

    def check_references(self, element: Element) -> Iterator[Finding]:
        for column in self.metamodel.columns(element.type):
            datatype = column.datatype.element if isinstance(column.datatype, ListType) else column.datatype
            if not isinstance(datatype, RefType) or column.name not in element.values:
                continue
            value = element.values[column.name]
            for target in value if isinstance(value, tuple) else (value,):
                target = str(target)
                if target not in self.model:
                    yield self.error(element, "reference", f"'{column.name}' refers to {target}, which does not exist")
                elif not any(self.metamodel.is_a(self.model.get(target).type, t) for t in datatype.targets):
                    allowed = " or ".join(datatype.targets)
                    message = f"'{column.name}' refers to {target}, which is not a {allowed}"
                    yield self.error(element, "reference-type", message)

    def check_parameters(self, element: Element) -> Iterator[Finding]:
        names = [p.name for p in _items(element.values.get("parameters")) if isinstance(p, Parameter)]
        for name in sorted({name for name in names if names.count(name) > 1}):
            yield self.error(element, "parameters", f"parameter '{name}' is defined more than once")

    def check_arguments(self, element: Element) -> Iterator[Finding]:
        template_id = element.values.get("template")
        if not isinstance(template_id, str) or template_id not in self.model:
            return  # Reported by check_references.
        template = self.model.get(template_id)
        parameters = {p.name: p for p in _items(template.values.get("parameters")) if isinstance(p, Parameter)}
        arguments = [a for a in _items(element.values.get("arguments")) if isinstance(a, Argument)]
        names = [argument.name for argument in arguments]
        for name in sorted({name for name in names if names.count(name) > 1}):
            yield self.error(element, "arguments", f"argument '{name}' is given more than once")
        for argument in arguments:
            parameter = parameters.get(argument.name)
            if parameter is None:
                yield self.error(element, "arguments", f"template {template_id} has no parameter '{argument.name}'")
                continue
            try:
                parse_scalar(escape(argument.text), parameter.datatype, in_list=False)
            except LexicalError as error:
                yield self.error(element, "arguments", f"argument '{argument.name}': {error.message}")
        for parameter in parameters.values():
            if parameter.default is None and parameter.name not in names:
                yield self.error(element, "arguments", f"parameter '{parameter.name}' of template {template_id} is required")

    # --- Hierarchy -----------------------------------------------------------------------------------------

    def check_hierarchy(self) -> Iterator[Finding]:
        parents: dict[str, list[Element]] = {}
        for relationship in self.model.elements_of("HierarchyRelationship"):
            child = relationship.values.get("child")
            if isinstance(child, str):
                parents.setdefault(child, []).append(relationship)
        for child, relationships in parents.items():
            if len(relationships) > 1:
                listed = ", ".join(r.id for r in relationships)
                for relationship in relationships[1:]:
                    message = f"{child} has more than one parent, through {listed}"
                    yield self.error(relationship, "hierarchy", message)
        for child, relationships in parents.items():
            if self._is_own_ancestor(child, parents):
                yield self.error(relationships[0], "hierarchy", f"{child} is its own ancestor")

    @staticmethod
    def _is_own_ancestor(element: str, parents: dict[str, list[Element]]) -> bool:
        seen: set[str] = set()
        current = element
        while current in parents and current not in seen:
            seen.add(current)
            parent = parents[current][0].values.get("parent")
            if not isinstance(parent, str):
                return False
            if parent == element:
                return True
            current = parent
        return False

    # --- Diagrams ------------------------------------------------------------------------------------------

    def check_diagrams(self) -> Iterator[Finding]:
        for identifier, diagram in sorted(self.model.diagrams.items()):
            yield from self.check_diagram(self.model.get(identifier), diagram)

    def check_diagram(self, element: Element, diagram: DiagramFile) -> Iterator[Finding]:
        path = f"{DIAGRAM_DIRECTORY}/{diagram.id}.diag"
        type_name = element.type
        stereotype = self.stereotype(element)
        is_sequence = stereotype is Stereotype.SEQUENCE_DIAGRAM
        allowed = self._names(type_name, "entities") + self._names(type_name, "relationships")
        generated = any(isinstance(s, Generate) for s in diagram.statements)
        participants = [s.element for s in diagram.statements if isinstance(s, Participant)]

        def error(message: str) -> Finding:
            return self.error(element, "diagram", message, path=path)

        def check_allowed(identifier: str, what: str) -> Iterator[Finding]:
            if identifier not in self.model:
                yield error(f"{what} {identifier} does not exist")
            elif not any(self.metamodel.is_a(self.model.get(identifier).type, name) for name in allowed):
                yield error(f"{what} {identifier} is a {self.model.get(identifier).type}, which a {type_name} cannot show")

        for statement in diagram.statements:
            match statement:
                case Generate(rule, arguments):
                    if rule not in self._names(type_name, "rules"):
                        yield error(f"rule '{rule}' is not a generation rule of {type_name}")
                    for name, value in arguments:
                        if split_identifier(value) is not None and value not in self.model:
                            yield error(f"argument '{name}' of rule '{rule}' is {value}, which does not exist")
                case Show() | Highlight() if is_sequence:
                    yield error(f"a sequence diagram has no '{_keyword(statement)}' statements")
                case Participant() | Message() | Process() if not is_sequence:
                    yield error(f"only sequence diagrams have '{_keyword(statement)}' statements")
                case Show(identifier):
                    if generated:
                        yield error("a generated diagram has no 'show' statements")
                    yield from check_allowed(identifier, "element")
                case Highlight(chain):
                    if chain not in self.model:
                        yield error(f"chain {chain} does not exist")
                    elif not any(self.metamodel.is_a(self.model.get(chain).type, c) for c in self._names(type_name, "chains")):
                        yield error(f"{chain} is not a chain that a {type_name} can highlight")
                case Participant(identifier):
                    yield from check_allowed(identifier, "participant")
                case Message(relationship):
                    yield from check_allowed(relationship, "message")
                    if relationship in self.model:
                        for end in ("start", "end"):
                            owner = self._owner(self.model.get(relationship).values.get(end))
                            if owner is not None and owner not in participants:
                                yield error(f"message {relationship}: {owner} is not a participant")
                case Process(identifier, participant):
                    yield from check_allowed(identifier, "process")
                    if participant not in participants:
                        yield error(f"process {identifier}: {participant} is not a participant")
                case Layout(identifier) | Style(identifier):
                    if identifier not in self.model:
                        yield error(f"element {identifier} does not exist")

    def _names(self, type_name: str, key: str) -> list[str]:
        return [str(item) for item in _items(self.metamodel.property(type_name, key))]

    def _owner(self, identifier: object) -> str | None:
        """The entity an end of a relationship belongs to: the owner of a port, or the entity itself."""
        if not isinstance(identifier, str) or identifier not in self.model:
            return None
        element = self.model.get(identifier)
        if self.stereotype(element) is Stereotype.PORT:
            owner = element.values.get("owner")
            return owner if isinstance(owner, str) else None
        return identifier


def _keyword(statement: Statement) -> str:
    match statement:
        case Generate():
            return "generate"
        case Show():
            return "show"
        case Highlight():
            return "highlight"
        case Participant():
            return "participant"
        case Message():
            return "message"
        case Process():
            return "process"
        case Layout():
            return "layout"
        case Style():
            return "style"


def _items(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return (value,)
