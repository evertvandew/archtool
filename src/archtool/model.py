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

"""The model store: the elements of a concrete model, indexed by identifier, type and references.

See "Model library" in doc/architecture.md.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field

from archtool.formats.datatypes import ListType, RefType
from archtool.formats.diagram_file import DiagramFile
from archtool.formats.values import Value
from archtool.identifiers import identifier_key, make_identifier, split_identifier
from archtool.metamodel import MetaModel


@dataclass(slots=True)
class Element:
    """An element of the concrete model. `values` holds its attributes and core attributes, except `id`."""

    id: str
    type: str
    values: dict[str, Value] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Reference:
    """A reference from attribute `column` of element `source` to another element."""

    source: str
    column: str


class Model:
    """The elements of a concrete model, with the diagram files of its diagrams."""

    def __init__(self, metamodel: MetaModel) -> None:
        self.metamodel = metamodel
        self.diagrams: dict[str, DiagramFile] = {}
        self._elements: dict[str, Element] = {}
        self._by_type: dict[str, set[str]] = {}
        self._referrers: dict[str, set[Reference]] = {}
        # The highest number ever used per type, and the types that have a table, even if it is empty.
        self._last_numbers: dict[str, int] = {}

    # --- Queries -------------------------------------------------------------------------------------------

    def __contains__(self, identifier: str) -> bool:
        return identifier in self._elements

    def __len__(self) -> int:
        return len(self._elements)

    def get(self, identifier: str) -> Element:
        return self._elements[identifier]

    def elements(self) -> list[Element]:
        """All elements, sorted by identifier."""
        return [self._elements[i] for i in sorted(self._elements, key=identifier_key)]

    def elements_of(self, type_name: str, *, include_subtypes: bool = True) -> list[Element]:
        """The elements of a type (and by default of the types that extend it), sorted by identifier."""
        names = self.metamodel.subtypes(type_name) if include_subtypes else [type_name]
        identifiers = [i for name in names for i in self._by_type.get(name, ())]
        return [self._elements[i] for i in sorted(identifiers, key=identifier_key)]

    def referrers(self, identifier: str) -> list[Reference]:
        """The references to an element, sorted by source and column."""
        return sorted(self._referrers.get(identifier, ()), key=lambda r: (identifier_key(r.source), r.column))

    def table_types(self) -> list[str]:
        """The types that have a table, in the order of the meta model."""
        return [name for name in self.metamodel.types if name in self._last_numbers]

    def last_number(self, type_name: str) -> int:
        """The highest number ever used for a type: the recorded number, or a higher number in use."""
        recorded = self._last_numbers.get(type_name, 0)
        in_use = [split_identifier(i) for i in self._by_type.get(type_name, ())]
        return max([recorded] + [parts[1] for parts in in_use if parts is not None])

    # --- Changes -------------------------------------------------------------------------------------------

    def record_table(self, type_name: str, last_number: int) -> None:
        """Record that a type has a table, and the highest number ever used for it."""
        self._last_numbers[type_name] = max(last_number, self._last_numbers.get(type_name, 0))

    def new_identifier(self, type_name: str) -> str:
        """Allocate a new identifier for an element of a type. Numbers are never reused."""
        number = self.last_number(type_name) + 1
        self._last_numbers[type_name] = number
        return make_identifier(type_name, number)

    def add(self, element: Element) -> None:
        """Add an element with an identifier that is not in use yet."""
        if element.id in self._elements:
            raise ValueError(f"identifier {element.id} is already in use")
        parts = split_identifier(element.id)
        if parts is None or parts[0] != element.type:
            raise ValueError(f"identifier {element.id} does not match type {element.type}")
        self._elements[element.id] = element
        self._by_type.setdefault(element.type, set()).add(element.id)
        self.record_table(element.type, 0)
        self._index_references(element)

    def set_value(self, identifier: str, column: str, value: Value | None) -> None:
        """Set (or, with None, remove) a value of an element."""
        element = self._elements[identifier]
        self._unindex_references(element)
        if value is None:
            element.values.pop(column, None)
        else:
            element.values[column] = value
        self._index_references(element)

    def remove(self, identifier: str) -> Element:
        """Remove an element. References to it are not removed; see referrers()."""
        element = self._elements.pop(identifier)
        self._by_type[element.type].discard(identifier)
        self._unindex_references(element)
        return element

    # --- Reference index -----------------------------------------------------------------------------------

    def references_from(self, element: Element) -> Iterator[tuple[str, str]]:
        """The (column, target) pairs of the references of an element."""
        for column in self.metamodel.columns(element.type):
            datatype = column.datatype
            is_reference = isinstance(datatype, RefType) or (
                isinstance(datatype, ListType) and isinstance(datatype.element, RefType)
            )
            value = element.values.get(column.name)
            if not is_reference or value is None:
                continue
            for target in value if isinstance(value, tuple) else (value,):
                yield column.name, str(target)

    def _index_references(self, element: Element) -> None:
        for column, target in self.references_from(element):
            self._referrers.setdefault(target, set()).add(Reference(element.id, column))

    def _unindex_references(self, element: Element) -> None:
        for column, target in self.references_from(element):
            self._referrers.get(target, set()).discard(Reference(element.id, column))
