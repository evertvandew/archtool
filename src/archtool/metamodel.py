"""The meta model: the types of a method, defined as instances of the core-model stereotypes.

See "Meta-model file" in doc/file_formats.md, and "Core-model stereotypes" in doc/architecture.md.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from archtool.errors import FormatError, LexicalError
from archtool.formats.datatypes import DataType, EnumType, ListType, RefType, SimpleType
from archtool.formats.metamodel_file import MetaModelFile, TextSection, read_metamodel_file
from archtool.formats.tables import Column, Row, Table, parse_header
from archtool.formats.values import Scalar, Value, parse_cell
from archtool.identifiers import KEYWORDS, is_valid_type_name


class Stereotype(Enum):
    ENTITY = "Entity"
    PORT = "Port"
    RELATIONSHIP = "Relationship"
    REFINEMENT = "Refinement"
    HIERARCHY_RELATIONSHIP = "HierarchyRelationship"
    RELATIONSHIP_BREAKDOWN = "Relationship_breakdown"
    CHAIN = "Chain"
    TEMPLATE_ENTITY = "TemplateEntity"
    INSTANTIATION_ENTITY = "InstantiationEntity"
    DIAGRAM = "Diagram"
    BLOCK_DIAGRAM = "BlockDiagram"
    SEQUENCE_DIAGRAM = "SequenceDiagram"
    BREAKDOWN_DIAGRAM = "BreakDownDiagram"
    USE_CASE_DIAGRAM = "UseCaseDiagram"

    @property
    def parent(self) -> "Stereotype | None":
        """The stereotype this one specialises."""
        return _STEREOTYPE_PARENTS[self]

    def chain(self) -> list["Stereotype"]:
        """This stereotype and the ones it specialises, from `Entity` down to this one."""
        result: list[Stereotype] = []
        current: Stereotype | None = self
        while current is not None:
            result.append(current)
            current = current.parent
        return result[::-1]

    def is_diagram(self) -> bool:
        return Stereotype.DIAGRAM in self.chain()


_STEREOTYPE_PARENTS: dict[Stereotype, Stereotype | None] = {
    Stereotype.ENTITY: None,
    Stereotype.PORT: Stereotype.ENTITY,
    Stereotype.RELATIONSHIP: Stereotype.ENTITY,
    Stereotype.REFINEMENT: Stereotype.RELATIONSHIP,
    Stereotype.HIERARCHY_RELATIONSHIP: Stereotype.ENTITY,
    Stereotype.RELATIONSHIP_BREAKDOWN: Stereotype.ENTITY,
    Stereotype.CHAIN: Stereotype.ENTITY,
    Stereotype.TEMPLATE_ENTITY: Stereotype.ENTITY,
    Stereotype.INSTANTIATION_ENTITY: Stereotype.ENTITY,
    Stereotype.DIAGRAM: Stereotype.ENTITY,
    Stereotype.BLOCK_DIAGRAM: Stereotype.DIAGRAM,
    Stereotype.SEQUENCE_DIAGRAM: Stereotype.DIAGRAM,
    Stereotype.BREAKDOWN_DIAGRAM: Stereotype.DIAGRAM,
    Stereotype.USE_CASE_DIAGRAM: Stereotype.DIAGRAM,
}

_STEREOTYPES_BY_NAME = {stereotype.value: stereotype for stereotype in Stereotype}

_DIAGRAM_KINDS = {
    "block": Stereotype.BLOCK_DIAGRAM,
    "sequence": Stereotype.SEQUENCE_DIAGRAM,
    "breakdown": Stereotype.BREAKDOWN_DIAGRAM,
    "use_case": Stereotype.USE_CASE_DIAGRAM,
}

# The tables of the meta-model file, with their columns, as specified in doc/file_formats.md.
TABLE_HEADERS = {
    "entity_types": "name:ident;extends:ref(entity_types);description:text",
    "port_types": "name:ident;extends:ref(port_types);owner:list(ref(entity_types));description:text",
    "relationship_types": "name:ident;extends:ref(relationship_types);start:list(ref(entity_types|port_types));"
    "end:list(ref(entity_types|port_types));description:text",
    "refinement_types": "name:ident;extends:ref(refinement_types);start:list(ref(entity_types));"
    "end:list(ref(entity_types));description:text",
    "hierarchy_types": "name:ident;parent:ref(entity_types);child:ref(entity_types);description:text",
    "relationship_breakdown_types": "name:ident;aggregate:ref(relationship_types);"
    "constituent:ref(relationship_types);description:text",
    "chain_types": "name:ident;relationship:ref(relationship_types);description:text",
    "template_types": "name:ident;extends:ref(template_types);description:text",
    "instantiation_types": "name:ident;template:ref(template_types);description:text",
    "diagram_types": "name:ident;kind:enum(block|sequence|breakdown|use_case);"
    "entities:list(ref(entity_types|port_types));relationships:list(ref(any_type));"
    "chains:list(ref(chain_types));rules:list(ident);description:text",
    "abstraction_levels": "name:ident;diagrams:list(ref(diagram_types));description:text",
    "attributes": "type:ref(any_type);name:ident;datatype:datatype;required:bool;default:str;description:text",
    "labels": "diagram_type:ref(diagram_types);type:ref(any_type);text:str;anchor:ident",
    "shapes": "diagram_type:ref(diagram_types);type:ref(any_type);shape:str;start:str;end:str",
}
_TABLE_COLUMNS = {name: parse_header(header, "<specification>", 1) for name, header in TABLE_HEADERS.items()}

# The tables that define types, with the stereotype of their types (diagram types: by kind).
_TYPE_TABLES: dict[str, Stereotype | None] = {
    "entity_types": Stereotype.ENTITY,
    "port_types": Stereotype.PORT,
    "relationship_types": Stereotype.RELATIONSHIP,
    "refinement_types": Stereotype.REFINEMENT,
    "hierarchy_types": Stereotype.HIERARCHY_RELATIONSHIP,
    "relationship_breakdown_types": Stereotype.RELATIONSHIP_BREAKDOWN,
    "chain_types": Stereotype.CHAIN,
    "template_types": Stereotype.TEMPLATE_ENTITY,
    "instantiation_types": Stereotype.INSTANTIATION_ENTITY,
    "diagram_types": None,
}

# The properties a type of each stereotype must define, as they determine its core columns.
_REQUIRED_PROPERTIES = {
    Stereotype.PORT: ("owner",),
    Stereotype.RELATIONSHIP: ("start", "end"),
    Stereotype.REFINEMENT: ("start", "end"),
    Stereotype.HIERARCHY_RELATIONSHIP: ("parent", "child"),
    Stereotype.RELATIONSHIP_BREAKDOWN: ("aggregate", "constituent"),
    Stereotype.CHAIN: ("relationship",),
    Stereotype.INSTANTIATION_ENTITY: ("template",),
}

_RESERVED_ATTRIBUTE_NAMES = frozenset(
    {"id", "type", "owner", "start", "end", "parent", "child", "aggregate", "constituent", "relationships",
     "parameters", "template", "arguments"}
)  # fmt: skip


@dataclass(slots=True)
class TypeDef:
    """A type defined in the meta model."""

    name: str
    stereotype: Stereotype
    table: str
    extends: str | None = None
    description: str = ""
    # The other columns of the type's row, e.g. `owner` for a port type, or `start` and `end` for a relationship type.
    properties: dict[str, Value] = field(default_factory=dict)
    line: int = 0


@dataclass(frozen=True, slots=True)
class AttributeDef:
    """An attribute defined for a type, or for a stereotype (`owner` is then the stereotype's name)."""

    owner: str
    name: str
    datatype: DataType
    required: bool = False
    default: Value | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class Label:
    diagram_type: str | None
    type: str
    text: str
    anchor: str | None
    line: int = 0


@dataclass(frozen=True, slots=True)
class Shape:
    diagram_type: str | None
    type: str
    shape: str | None
    start: str | None
    end: str | None
    line: int = 0


@dataclass(frozen=True, slots=True)
class AbstractionLevel:
    name: str
    diagrams: tuple[str, ...]
    description: str = ""


@dataclass(slots=True)
class MetaModel:
    path: str
    types: dict[str, TypeDef] = field(default_factory=dict)
    attributes: list[AttributeDef] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    abstraction_levels: list[AbstractionLevel] = field(default_factory=list)
    rules: list[TextSection] = field(default_factory=list)
    styles: list[TextSection] = field(default_factory=list)
    defs: list[TextSection] = field(default_factory=list)

    def type(self, name: str) -> TypeDef:
        return self.types[name]

    def ancestors(self, name: str) -> list[str]:
        """The type and the types it extends, from the root of the inheritance chain down to the type itself."""
        result: list[str] = []
        current: str | None = name
        while current is not None:
            result.append(current)
            current = self.types[current].extends
        return result[::-1]

    def is_a(self, name: str, other: str) -> bool:
        """Whether type `name` is `other`, or extends it. `other` may also be a stereotype name."""
        if other in _STEREOTYPES_BY_NAME:
            return _STEREOTYPES_BY_NAME[other] in self.types[name].stereotype.chain()
        return other in self.ancestors(name)

    def subtypes(self, name: str) -> list[str]:
        """All types that are `name` or extend it, in the order they are defined."""
        return [other for other in self.types if self.is_a(other, name)]

    def property(self, name: str, key: str) -> Value | None:
        """A property of a type, inherited from the types it extends if it does not define it itself."""
        for ancestor in reversed(self.ancestors(name)):
            value = self.types[ancestor].properties.get(key)
            if value is not None:
                return value
        return None

    def attributes_of(self, name: str) -> list[AttributeDef]:
        """The attributes of a type, in canonical column order: first those of its stereotypes, then those of
        the types it extends, from the root down, and finally its own."""
        owners = [stereotype.value for stereotype in self.types[name].stereotype.chain()] + self.ancestors(name)
        return [attribute for owner in owners for attribute in self.attributes if attribute.owner == owner]

    def core_columns(self, name: str) -> list[Column]:
        """The core columns of a type's table, as determined by its stereotype."""
        columns = [Column("id", SimpleType("id"))]
        match self.types[name].stereotype:
            case Stereotype.PORT:
                columns.append(Column("owner", RefType(self._names(name, "owner"))))
            case Stereotype.RELATIONSHIP | Stereotype.REFINEMENT:
                columns.append(Column("start", RefType(self._names(name, "start"))))
                columns.append(Column("end", RefType(self._names(name, "end"))))
            case Stereotype.HIERARCHY_RELATIONSHIP:
                columns.append(Column("parent", RefType(self._names(name, "parent"))))
                columns.append(Column("child", RefType(self._names(name, "child"))))
            case Stereotype.RELATIONSHIP_BREAKDOWN:
                columns.append(Column("aggregate", RefType(self._names(name, "aggregate"))))
                columns.append(Column("constituent", RefType(self._names(name, "constituent"))))
            case Stereotype.CHAIN:
                columns.append(Column("relationships", ListType(RefType(self._names(name, "relationship")))))
            case Stereotype.TEMPLATE_ENTITY:
                columns.append(Column("parameters", ListType(SimpleType("parameter"))))
            case Stereotype.INSTANTIATION_ENTITY:
                columns.append(Column("template", RefType(self._names(name, "template"))))
                columns.append(Column("arguments", ListType(SimpleType("argument"))))
            case _:
                pass
        return columns

    def columns(self, name: str) -> list[Column]:
        """All columns of a type's table, in canonical order."""
        attributes = [Column(attribute.name, attribute.datatype) for attribute in self.attributes_of(name)]
        return self.core_columns(name) + attributes

    def _names(self, name: str, key: str) -> tuple[str, ...]:
        value = self.property(name, key)
        if isinstance(value, str):
            return (value,)
        if isinstance(value, tuple):
            return tuple(str(item) for item in value)
        raise AssertionError(f"type {name} has no property {key}")


def load_metamodel(path: Path) -> MetaModel:
    """Read and interpret a meta-model file. Raises FormatError."""
    return build_metamodel(read_metamodel_file(path.read_text(encoding="utf-8"), path))


def build_metamodel(file: MetaModelFile) -> MetaModel:
    """Interpret the tables of a meta-model file. Raises FormatError."""
    return _Builder(file).build()


class _Builder:
    def __init__(self, file: MetaModelFile) -> None:
        self.file = file
        self.metamodel = MetaModel(file.path, rules=file.rules, styles=file.styles, defs=file.defs)

    def error(self, line: int, message: str) -> FormatError:
        return FormatError(self.file.path, line, 1, message)

    def build(self) -> MetaModel:
        for name, table in self.file.tables.items():
            self._check_table(name, table)
        for table_name, stereotype in _TYPE_TABLES.items():
            for row in self._rows(table_name):
                self._add_type(table_name, stereotype, row)
        for type_def in self.metamodel.types.values():
            self._check_type(type_def)
        for row in self._rows("attributes"):
            self._add_attribute(row)
        for name in self.metamodel.types:
            self._check_attributes(name)
        for row in self._rows("labels"):
            self.metamodel.labels.append(self._label(row))
        for row in self._rows("shapes"):
            self.metamodel.shapes.append(self._shape(row))
        for row in self._rows("abstraction_levels"):
            self.metamodel.abstraction_levels.append(self._abstraction_level(row))
        return self.metamodel

    def _rows(self, table: str) -> list[Row]:
        return self.file.tables[table].rows if table in self.file.tables else []

    def _check_table(self, name: str, table: Table) -> None:
        if name not in _TABLE_COLUMNS:
            raise self.error(table.line - 1, f"unknown table '{name}'")
        expected = {column.name: column for column in _TABLE_COLUMNS[name]}
        for column in table.columns:
            if column.name not in expected:
                raise self.error(table.line, f"table '{name}' has no column '{column.name}'")
            if column != expected[column.name]:
                raise self.error(table.line, f"column '{column.name}' must be written as '{expected[column.name].header()}'")
        first = _TABLE_COLUMNS[name][0].name
        if table.column(first) is None:
            raise self.error(table.line, f"table '{name}' must have a column '{first}'")

    def _add_type(self, table: str, stereotype: Stereotype | None, row: Row) -> None:
        values = dict(row.values)
        name = _text(values.pop("name", None))
        if not is_valid_type_name(name):
            raise self.error(row.line, f"'{name}' is not a valid type name")
        if name in self.metamodel.types:
            raise self.error(row.line, f"type '{name}' is defined more than once")
        if stereotype is None:
            kind = values.pop("kind", None)
            if not isinstance(kind, str):
                raise self.error(row.line, f"diagram type '{name}' has no kind")
            stereotype = _DIAGRAM_KINDS[kind]
        extends = values.pop("extends", None)
        description = values.pop("description", None)
        self.metamodel.types[name] = TypeDef(
            name, stereotype, table, extends if isinstance(extends, str) else None, _text(description), values, row.line
        )

    def _check_type(self, type_def: TypeDef) -> None:
        if type_def.extends is not None:
            parent = self.metamodel.types.get(type_def.extends)
            if parent is None or parent.table != type_def.table:
                raise self.error(type_def.line, f"'{type_def.extends}' is not a type in table '{type_def.table}'")
            seen = {type_def.name}
            current = parent
            while current.extends is not None:
                if current.name in seen:
                    raise self.error(type_def.line, f"type '{type_def.name}' extends itself")
                seen.add(current.name)
                current = self.metamodel.types[current.extends]
        for key in _REQUIRED_PROPERTIES.get(type_def.stereotype, ()):
            if self.metamodel.property(type_def.name, key) is None:
                raise self.error(type_def.line, f"type '{type_def.name}' must define '{key}'")
        for key, value in type_def.properties.items():
            column = next(c for c in _TABLE_COLUMNS[type_def.table] if c.name == key)
            for target in _references(value, column.datatype):
                self._check_reference(target, column.datatype, type_def.line, stereotypes=False)

    def _check_reference(self, name: str, datatype: DataType, line: int, *, stereotypes: bool) -> None:
        element = datatype.element if isinstance(datatype, ListType) else datatype
        assert isinstance(element, RefType)
        if stereotypes and name in _STEREOTYPES_BY_NAME:
            return
        type_def = self.metamodel.types.get(name)
        if type_def is None:
            raise self.error(line, f"unknown type '{name}'")
        tables = set(element.targets)
        if "entity_types" in tables:
            tables |= {"template_types", "instantiation_types"}
        if "any_type" not in tables and type_def.table not in tables:
            raise self.error(line, f"'{name}' is not a type in {', '.join(sorted(element.targets))}")

    def _add_attribute(self, row: Row) -> None:
        owner = _text(row.values.get("type"))
        if owner not in _STEREOTYPES_BY_NAME:
            self._check_reference(owner, RefType(("any_type",)), row.line, stereotypes=False)
        name = _text(row.values.get("name"))
        if name in KEYWORDS or name in _RESERVED_ATTRIBUTE_NAMES:
            raise self.error(row.line, f"'{name}' cannot be used as an attribute name")
        datatype = row.values.get("datatype")
        if not isinstance(datatype, (SimpleType, EnumType, RefType, ListType)):
            raise self.error(row.line, f"attribute '{name}' has no data type")
        required = row.values.get("required") is True
        default_text = row.values.get("default")
        default: Value | None = None
        if isinstance(default_text, str):
            if required:
                raise self.error(row.line, f"required attribute '{name}' cannot have a default")
            try:
                default = parse_cell(default_text, datatype)
            except LexicalError as error:
                raise self.error(row.line, f"invalid default for attribute '{name}': {error.message}") from None
        self.metamodel.attributes.append(
            AttributeDef(owner, name, datatype, required, default, _text(row.values.get("description")))
        )

    def _check_attributes(self, name: str) -> None:
        seen: set[str] = set()
        for attribute in self.metamodel.attributes_of(name):
            if attribute.name in seen:
                raise self.error(1, f"type '{name}' has attribute '{attribute.name}' more than once")
            seen.add(attribute.name)

    def _label(self, row: Row) -> Label:
        diagram_type, type_name = self._presentation_keys(row)
        anchor = row.values.get("anchor")
        text = _text(row.values.get("text"))
        return Label(diagram_type, type_name, text, anchor if isinstance(anchor, str) else None, row.line)

    def _shape(self, row: Row) -> Shape:
        diagram_type, type_name = self._presentation_keys(row)
        return Shape(
            diagram_type,
            type_name,
            _optional_text(row.values.get("shape")),
            _optional_text(row.values.get("start")),
            _optional_text(row.values.get("end")),
            row.line,
        )

    def _presentation_keys(self, row: Row) -> tuple[str | None, str]:
        diagram_type = _optional_text(row.values.get("diagram_type"))
        if diagram_type is not None:
            self._check_reference(diagram_type, RefType(("diagram_types",)), row.line, stereotypes=False)
        type_name = _text(row.values.get("type"))
        self._check_reference(type_name, RefType(("any_type",)), row.line, stereotypes=True)
        return diagram_type, type_name

    def _abstraction_level(self, row: Row) -> AbstractionLevel:
        name = _text(row.values.get("name"))
        diagrams = row.values.get("diagrams", ())
        assert isinstance(diagrams, tuple)
        for diagram in diagrams:
            self._check_reference(str(diagram), RefType(("diagram_types",)), row.line, stereotypes=False)
        return AbstractionLevel(name, tuple(str(d) for d in diagrams), _text(row.values.get("description")))


def _references(value: Value, datatype: DataType) -> Iterator[str]:
    """The names referred to by a value of a `ref(…)` or `list(ref(…))` column."""
    element = datatype.element if isinstance(datatype, ListType) else datatype
    if not isinstance(element, RefType):
        return
    items: tuple[Scalar, ...] = value if isinstance(value, tuple) else (value,)
    for item in items:
        yield str(item)


def _text(value: Value | None) -> str:
    return value if isinstance(value, str) else ""


def _optional_text(value: Value | None) -> str | None:
    return value if isinstance(value, str) else None

