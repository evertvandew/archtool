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

"""What a diagram shows: its blocks, how they nest, their ports, and the lines between them.

The elements a diagram shows come from its generation rule, or from the `show` statements of a drawn diagram.
See "Diagram files" in doc/file_formats.md.
"""

from dataclasses import dataclass, field

from archtool.formats.diagram_file import DiagramFile, Generate, Highlight, Message, Participant, Process, Show
from archtool.identifiers import identifier_key
from archtool.language.runtime import Runner
from archtool.metamodel import MetaModel, Stereotype
from archtool.model import Model


@dataclass(frozen=True, slots=True)
class Line:
    """A line for element `element` (a relationship), from block or port `start` to block or port `end`."""

    element: str
    start: str
    end: str


@dataclass(frozen=True, slots=True)
class SequenceEvent:
    """A message (`participant` is None) or the processing of an element by a participant, in time order."""

    element: str
    participant: str | None = None


@dataclass(slots=True)
class DiagramContent:
    diagram: str
    type: str
    stereotype: Stereotype
    blocks: list[str] = field(default_factory=list)
    parents: dict[str, str] = field(default_factory=dict)  # A nested block's enclosing block (block diagrams).
    ports: dict[str, list[str]] = field(default_factory=dict)  # The drawn ports of each block.
    lines: list[Line] = field(default_factory=list)
    highlighted: set[str] = field(default_factory=set)
    # Sequence diagrams:
    participants: list[str] = field(default_factory=list)
    events: list[SequenceEvent] = field(default_factory=list)

    def children(self, block: str | None) -> list[str]:
        """The blocks directly inside `block`; for None, the top-level blocks."""
        return [b for b in self.blocks if self.parents.get(b) == block]


def diagram_content(runner: Runner, diagram: DiagramFile) -> DiagramContent:
    """Work out what a diagram shows. Raises RuleError for a generation rule that cannot be evaluated."""
    model = runner.model
    metamodel = model.metamodel
    stereotype = metamodel.types[diagram.type].stereotype
    content = DiagramContent(diagram.id, diagram.type, stereotype)
    if stereotype is Stereotype.SEQUENCE_DIAGRAM:
        for statement in diagram.statements:
            if isinstance(statement, Participant) and statement.element in model:
                content.participants.append(statement.element)
            elif isinstance(statement, Message) and statement.relationship in model:
                content.events.append(SequenceEvent(statement.relationship))
            elif isinstance(statement, Process) and statement.element in model:
                content.events.append(SequenceEvent(statement.element, statement.participant))
        return content

    shown: set[str] = set()
    for statement in diagram.statements:
        if isinstance(statement, Generate):
            shown |= runner.generate(statement.rule, statement.arguments)
        elif isinstance(statement, Show) and statement.element in model:
            shown.add(statement.element)
    _Builder(model, metamodel, content, shown).build()
    for statement in diagram.statements:
        if isinstance(statement, Highlight) and statement.chain in model:
            _highlight(content, model, statement.chain)
    return content


class _Builder:
    def __init__(self, model: Model, metamodel: MetaModel, content: DiagramContent, shown: set[str]) -> None:
        self.model = model
        self.metamodel = metamodel
        self.content = content
        self.shown = sorted(shown, key=identifier_key)

    def stereotype(self, identifier: str) -> Stereotype:
        return self.metamodel.types[self.model.get(identifier).type].stereotype

    def is_a(self, identifier: str, stereotype: Stereotype) -> bool:
        return stereotype in self.stereotype(identifier).chain()

    def build(self) -> None:
        content = self.content
        content.blocks = [e for e in self.shown if self._is_block(e)]
        blocks = set(content.blocks)
        hierarchy = self._hierarchy(blocks)
        if content.stereotype is Stereotype.BLOCK_DIAGRAM:
            content.parents = {child: parent for child, (_, parent) in hierarchy.items()}
        elif content.stereotype is Stereotype.BREAKDOWN_DIAGRAM:
            for child, (relationship, parent) in sorted(hierarchy.items(), key=lambda item: identifier_key(item[0])):
                content.lines.append(Line(relationship, parent, child))
        for identifier in self.shown:
            if self.is_a(identifier, Stereotype.PORT):
                self._add_port(identifier, blocks)
            elif self.is_a(identifier, Stereotype.RELATIONSHIP):
                self._add_line(identifier, blocks)

    def _is_block(self, identifier: str) -> bool:
        stereotype = self.stereotype(identifier)
        excluded = (Stereotype.PORT, Stereotype.RELATIONSHIP, Stereotype.HIERARCHY_RELATIONSHIP,
                    Stereotype.RELATIONSHIP_BREAKDOWN, Stereotype.CHAIN, Stereotype.DIAGRAM)  # fmt: skip
        return not any(s in stereotype.chain() for s in excluded)

    def _hierarchy(self, blocks: set[str]) -> dict[str, tuple[str, str]]:
        """For each shown block whose hierarchy parent is shown too: the hierarchy relationship and the parent."""
        result: dict[str, tuple[str, str]] = {}
        for relationship in self.model.elements_of("HierarchyRelationship"):
            parent, child = relationship.values.get("parent"), relationship.values.get("child")
            if isinstance(parent, str) and isinstance(child, str) and parent in blocks and child in blocks:
                result.setdefault(child, (relationship.id, parent))
        return result

    def _add_port(self, port: str, blocks: set[str]) -> None:
        owner = self.model.get(port).values.get("owner")
        if isinstance(owner, str) and owner in blocks:
            ports = self.content.ports.setdefault(owner, [])
            if port not in ports:
                ports.append(port)
                ports.sort(key=identifier_key)

    def _add_line(self, relationship: str, blocks: set[str]) -> None:
        values = self.model.get(relationship).values
        ends: list[str] = []
        for key in ("start", "end"):
            end = values.get(key)
            if not isinstance(end, str) or end not in self.model:
                return
            if self.is_a(end, Stereotype.PORT):
                owner = self.model.get(end).values.get("owner")
                if not isinstance(owner, str) or owner not in blocks:
                    return
                self._add_port(end, blocks)
            elif end not in blocks:
                return
            ends.append(end)
        self.content.lines.append(Line(relationship, ends[0], ends[1]))


def _highlight(content: DiagramContent, model: Model, chain: str) -> None:
    relationships = model.get(chain).values.get("relationships", ())
    members = set(relationships) if isinstance(relationships, tuple) else set()
    for line in content.lines:
        if line.element in members:
            content.highlighted |= {line.element, line.start, line.end}
            for end in (line.start, line.end):
                owner = model.get(end).values.get("owner")
                if isinstance(owner, str):
                    content.highlighted.add(owner)
