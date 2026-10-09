import pytest

from archtool.errors import FormatError
from archtool.formats.metamodel_file import read_metamodel_file
from archtool.metamodel import MetaModel, Stereotype, build_metamodel, load_metamodel
from tests.conftest import SIMPLIFIED_ARCADIA


@pytest.fixture(scope="module")
def arcadia() -> MetaModel:
    return load_metamodel(SIMPLIFIED_ARCADIA / "metamodel.csv")


def headers(metamodel: MetaModel, type_name: str) -> str:
    return ";".join(column.header() for column in metamodel.columns(type_name))


def test_types_and_stereotypes(arcadia: MetaModel) -> None:
    assert arcadia.type("function").stereotype is Stereotype.ENTITY
    assert arcadia.type("realises").stereotype is Stereotype.REFINEMENT
    assert arcadia.type("functional_sequence").stereotype is Stereotype.SEQUENCE_DIAGRAM
    assert arcadia.ancestors("system_function") == ["function", "system_function"]
    assert arcadia.is_a("system_function", "function")
    assert arcadia.is_a("realises", "Relationship")
    assert not arcadia.is_a("function", "system_function")
    assert arcadia.subtypes("function") == ["function", "system_function", "logical_function"]


def test_columns_as_in_the_architecture(arcadia: MetaModel) -> None:
    """The table headers listed in doc/architecture.md, "Example: simplified Arcadia"."""
    assert headers(arcadia, "requirement") == (
        "id:id;name:str;text:text;priority:enum(high|medium|low);"
        "verification_method:enum(test|inspection|analysis|demonstration)"
    )
    assert headers(arcadia, "function_port") == "id:id;owner:ref(function);name:str;direction:enum(input|output)"
    assert headers(arcadia, "component_port") == "id:id;owner:ref(component|actor);name:str"
    assert headers(arcadia, "functional_exchange") == (
        "id:id;start:ref(function_port);end:ref(function_port);name:str;description:text"
    )
    assert headers(arcadia, "realises") == "id:id;start:ref(logical_function);end:ref(system_function);name:str"
    assert headers(arcadia, "function_contains_function") == "id:id;parent:ref(function);child:ref(function);name:str"
    assert headers(arcadia, "functional_chain") == "id:id;relationships:list(ref(functional_exchange));name:str"
    assert headers(arcadia, "exchange_allocation") == (
        "id:id;aggregate:ref(component_exchange);constituent:ref(functional_exchange);name:str"
    )
    assert headers(arcadia, "mission") == "id:id;name:str"


def test_presentation_and_rules(arcadia: MetaModel) -> None:
    assert [level.name for level in arcadia.abstraction_levels] == ["system_level", "logical_level", "physical_level"]
    assert any(label.diagram_type is None and label.type == "Entity" for label in arcadia.labels)
    assert any(shape.type == "actor" and shape.shape == "actor" for shape in arcadia.shapes)
    assert "check requirement_covered (error):" in arcadia.rules[0].text
    assert "linearGradient" in arcadia.defs[0].text


def build(text: str) -> MetaModel:
    return build_metamodel(read_metamodel_file(text, "m.csv"))


ENTITIES = "@table entity_types\nname:ident;extends:ref(entity_types);description:text\nfunction;;\n"


def test_templates_and_instantiations() -> None:
    metamodel = build(
        "@table template_types\nname:ident;extends:ref(template_types);description:text\nfilter_template;;\n"
        "@table instantiation_types\nname:ident;template:ref(template_types);description:text\n"
        "filter;filter_template;\n"
    )
    assert headers(metamodel, "filter_template") == "id:id;parameters:list(parameter)"
    assert headers(metamodel, "filter") == "id:id;template:ref(filter_template);arguments:list(argument)"


def test_properties_are_inherited() -> None:
    metamodel = build(
        ENTITIES + "@table port_types\nname:ident;extends:ref(port_types);owner:list(ref(entity_types));"
        "description:text\nport;;[function];\nspecial_port;port;;\n"
    )
    assert headers(metamodel, "special_port") == "id:id;owner:ref(function)"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("@table entity_typez\nname:ident\n", "unknown table"),
        ("@table entity_types\nname:ident;kind:str\n", "has no column 'kind'"),
        ("@table entity_types\nname:str\n", "must be written as 'name:ident'"),
        (ENTITIES + "function;;\n", "defined more than once"),
        ("@table entity_types\nname:ident;extends:ref(entity_types)\nlevel_2;\n", "not a valid type name"),
        ("@table entity_types\nname:ident;extends:ref(entity_types)\nwhere;\n", "not a valid type name"),
        ("@table entity_types\nname:ident;extends:ref(entity_types)\nf;g\n", "'g' is not a type"),
        ("@table entity_types\nname:ident;extends:ref(entity_types)\nf;g\ng;f\n", "extends itself"),
        (
            ENTITIES + "@table relationship_types\nname:ident;start:list(ref(entity_types|port_types))\nr;[function]\n",
            "must define 'end'",
        ),
        (
            ENTITIES + "@table relationship_types\nname:ident;start:list(ref(entity_types|port_types));"
            "end:list(ref(entity_types|port_types))\nr;[function];[nothing]\n",
            "unknown type 'nothing'",
        ),
        (
            ENTITIES + "@table attributes\ntype:ref(any_type);name:ident;datatype:datatype\nfunction;order;str\n",
            "cannot be used as an attribute name",
        ),
        (
            ENTITIES + "@table attributes\ntype:ref(any_type);name:ident;datatype:datatype\n"
            "Entity;name;str\nfunction;name;str\n",
            "attribute 'name' more than once",
        ),
    ],
)
def test_errors(text: str, message: str) -> None:
    with pytest.raises(FormatError, match=message):
        build(text)
