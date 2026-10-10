"""The model as JSON, for web clients: the meta model, the elements, the diagrams and the findings.

Values are converted to JSON as simply as possible: text, numbers and booleans as such, lists as lists, and
anything else (floats, which keep their text, template parameters and arguments) as the text of a table cell.
"""

from archtool.checker import Finding
from archtool.formats.datatypes import DataType, EnumType, ListType, RefType, SimpleType
from archtool.diagrams.content import diagram_content
from archtool.formats.diagram_file import DiagramFile, Generate, Show
from archtool.formats.values import Float, Scalar, Value, format_scalar
from archtool.identifiers import identifier_key
from archtool.language.runtime import RuleError, Rules, Runner
from archtool.metamodel import MetaModel
from archtool.model import Model

type Json = dict[str, object]

_PROPERTIES = ("owner", "start", "end", "parent", "child", "aggregate", "constituent", "relationship", "template",
               "entities", "relationships", "chains", "rules")  # fmt: skip


def snapshot(model: Model, rules: Rules, findings: list[Finding], version: int) -> Json:
    runner = Runner(rules, model)
    metamodel = model.metamodel
    parents: dict[str, str] = {}
    for relationship in model.elements_of("HierarchyRelationship"):
        parent, child = relationship.values.get("parent"), relationship.values.get("child")
        if isinstance(parent, str) and isinstance(child, str):
            parents.setdefault(child, parent)
    elements: Json = {}
    for element in model.elements():
        columns = {column.name: column.datatype for column in metamodel.columns(element.type)}
        elements[element.id] = {
            "type": element.type,
            "label": runner.default_label(element.id),
            "values": {key: _json(value, columns[key]) for key, value in element.values.items() if key in columns},
            "parent": parents.get(element.id),
        }
    diagrams = [
        {
            "id": identifier,
            "type": diagram.type,
            "label": runner.default_label(identifier),
            "kind": metamodel.types[diagram.type].stereotype.value,
            "generated": any(isinstance(s, Generate) for s in diagram.statements),
            "shown": [s.element for s in diagram.statements if isinstance(s, Show)],
            "elements": _diagram_elements(runner, diagram),
        }
        for identifier, diagram in sorted(model.diagrams.items(), key=lambda item: identifier_key(item[0]))
    ]
    return {
        "version": version,
        "types": types(metamodel),
        "rules": generation_rules(rules),
        "elements": elements,
        "diagrams": diagrams,
        "findings": [finding.to_json() for finding in findings],
    }


def _diagram_elements(runner: Runner, diagram: DiagramFile) -> list[str]:
    """The elements that appear in a diagram. For a generated diagram, these are the elements that pass its generation
    rule, evaluated with the diagram's arguments; for a drawn one, the elements it shows. Both also include the ports
    drawn on its blocks, and the participants and messages of a sequence diagram. If the generation rule cannot be
    evaluated, the diagram has no elements."""
    found: set[str] = set()
    try:
        for statement in diagram.statements:
            if isinstance(statement, Generate):
                found |= runner.generate(statement.rule, statement.arguments)
        content = diagram_content(runner, diagram)
    except RuleError:
        return []
    found |= {*content.blocks, *(port for ports in content.ports.values() for port in ports)}
    found |= {line.element for line in content.lines} | set(content.participants)
    found |= {event.element for event in content.events}
    return sorted(found, key=identifier_key)


def generation_rules(rules: Rules) -> Json:
    """The parameters of the generation rules: their names, types and defaults (None if they have none)."""
    return {
        name: {
            "parameters": [
                {"name": p.ident, "type": p.type, "default": p.default.value if p.default is not None else None}
                for p in rule.parameters
            ]
        }
        for name, rule in rules.program.diagrams.items()
    }


def types(metamodel: MetaModel) -> Json:
    """The types of the meta model, with what clients need to build forms and menus."""
    required = {(a.owner, a.name) for a in metamodel.attributes if a.required}
    result: Json = {}
    for name, type_def in metamodel.types.items():
        core = {column.name for column in metamodel.core_columns(name)}
        owners = set(metamodel.ancestors(name)) | {s.value for s in type_def.stereotype.chain()}
        columns = []
        for column in metamodel.columns(name):
            if column.name == "id":
                continue
            entry = _datatype(column.datatype)
            entry["name"] = column.name
            entry["core"] = column.name in core
            entry["required"] = column.name in core or any((owner, column.name) in required for owner in owners)
            columns.append(entry)
        properties: Json = {}
        for key in _PROPERTIES:
            value = metamodel.property(name, key)
            if value is not None:
                properties[key] = [str(v) for v in value] if isinstance(value, tuple) else [str(value)]
        result[name] = {
            "stereotype": type_def.stereotype.value,
            "stereotypes": [s.value for s in type_def.stereotype.chain()],
            "ancestors": metamodel.ancestors(name),
            "description": type_def.description,
            "columns": columns,
            "properties": properties,
        }
    return result


def _datatype(datatype: DataType) -> Json:
    element = datatype.element if isinstance(datatype, ListType) else datatype
    result: Json = {"list": isinstance(datatype, ListType)}
    match element:
        case EnumType(values):
            result |= {"kind": "enum", "values": list(values)}
        case RefType(targets):
            result |= {"kind": "ref", "targets": list(targets)}
        case SimpleType(kind):
            result["kind"] = kind
    return result


def _json(value: Value, datatype: DataType) -> object:
    if isinstance(value, tuple):
        element = datatype.element if isinstance(datatype, ListType) else datatype
        return [_scalar(item, element) for item in value]
    scalar_type = datatype.element if isinstance(datatype, ListType) else datatype
    return _scalar(value, scalar_type)


def _scalar(value: Scalar, datatype: SimpleType | EnumType | RefType) -> object:
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Float):
        return value.text
    return format_scalar(value, datatype, in_list=False)
