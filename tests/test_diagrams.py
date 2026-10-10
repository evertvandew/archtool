import io
import json
import shutil
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from archtool.cli import run_render
from archtool.diagrams.content import DiagramContent, Line, SequenceEvent, diagram_content
from archtool.diagrams.elk import elk_command, elk_graph, elk_layout, read_layout
from archtool.diagrams.geometry import Box, Geometry, Path as GeometryPath, PlacedLabel
from archtool.diagrams.hints import apply_position_hints
from archtool.diagrams.presentation import Presentation
from archtool.diagrams.render import RenderError, Renderer
from archtool.diagrams.sequence import sequence_layout
from archtool.diagrams.svg import LINE_ENDINGS, _shape, render_svg
from archtool.formats.diagram_file import Layout
from archtool.language.runtime import Runner, load_rules
from archtool.metamodel import Stereotype
from archtool.repository import Repository, load_repository
from tests.conftest import SIMPLIFIED_ARCADIA

SVG = "{http://www.w3.org/2000/svg}"


@pytest.fixture(scope="module")
def repository() -> Repository:
    return load_repository(SIMPLIFIED_ARCADIA)


@pytest.fixture(scope="module")
def runner(repository: Repository) -> Runner:
    return Runner(load_rules(repository.metamodel), repository.model)


def content(runner: Runner, diagram: str) -> DiagramContent:
    return diagram_content(runner, runner.model.diagrams[diagram])


# --- Content ------------------------------------------------------------------------------------------------


def test_block_diagram_content(runner: Runner) -> None:
    result = content(runner, "physical_architecture_1")
    assert result.stereotype is Stereotype.BLOCK_DIAGRAM
    assert result.blocks == ["component_1", "component_2", "component_3", "component_4"]
    assert result.parents == {"component_2": "component_1", "component_3": "component_1", "component_4": "component_1"}
    assert result.children(None) == ["component_1"]
    assert result.ports == {
        "component_2": ["component_port_1", "component_port_4"],
        "component_3": ["component_port_3"],
        "component_4": ["component_port_2"],
    }
    assert result.lines == [
        Line("component_exchange_1", "component_port_1", "component_port_2"),
        Line("component_exchange_2", "component_port_3", "component_port_4"),
    ]


def test_highlighted_chain(runner: Runner) -> None:
    result = content(runner, "logical_dataflow_2")
    assert result.highlighted == {
        "functional_exchange_2", "functional_exchange_3", "function_port_3", "function_port_4", "function_port_5",
        "function_port_6", "logical_function_2", "logical_function_3", "logical_function_4",
    }  # fmt: skip


def test_breakdown_diagram_content(runner: Runner) -> None:
    result = content(runner, "function_breakdown_1")
    assert result.parents == {}
    assert result.lines == [
        Line("function_contains_function_1", "system_function_1", "system_function_2"),
        Line("function_contains_function_2", "system_function_1", "system_function_3"),
        Line("function_contains_function_3", "system_function_1", "system_function_4"),
    ]


def test_lines_need_both_ends(runner: Runner) -> None:
    """In the allocation diagram, the hierarchy relationships are not lines, and allocations connect blocks."""
    result = content(runner, "allocation_1")
    assert [line.element for line in result.lines] == ["allocated_to_1", "allocated_to_2", "allocated_to_3", "allocated_to_4"]


def test_sequence_content(runner: Runner) -> None:
    result = content(runner, "functional_sequence_1")
    assert result.participants == ["logical_function_1", "logical_function_3", "logical_function_2", "logical_function_4"]
    assert result.events == [
        SequenceEvent("functional_exchange_1"), SequenceEvent("functional_exchange_2"), SequenceEvent("functional_exchange_3"),
    ]  # fmt: skip


# --- Presentation -------------------------------------------------------------------------------------------


def test_presentation(runner: Runner) -> None:
    physical = Presentation(runner, "physical_architecture")
    assert physical.classes("component_2") == "component Entity"
    assert physical.classes("realises_1") == "realises Refinement Relationship Entity"
    assert [(label.text, label.anchor) for label in physical.labels("component_2")] == [
        ("Controller", "top"), ("«component»", "top_left"),
    ]  # fmt: skip
    assert physical.look("component_2").shape == "rectangle"
    assert Presentation(runner, "mission").look("system_function_2").shape == "use_case"
    assert Presentation(runner, "function_breakdown").look("system_function_2").shape == "rounded_rectangle"
    breakdown = Presentation(runner, "function_breakdown").look("function_contains_function_1")
    assert (breakdown.start, breakdown.end) == ("none", "none")
    covers = physical.look("covers_1")
    assert (covers.start, covers.end) == ("none", "open_arrow")
    # Relationships without a name have an empty label, which is not shown.
    assert physical.labels("allocated_to_1") == []


# --- Layout -------------------------------------------------------------------------------------------------


def test_elk_graph(runner: Runner) -> None:
    diagram = runner.model.diagrams["physical_architecture_1"]
    hints = {s.element: s for s in diagram.statements if isinstance(s, Layout)}
    graph = elk_graph(diagram_content(runner, diagram), Presentation(runner, diagram.type), hints)
    options = graph["layoutOptions"]
    assert isinstance(options, dict) and options["elk.hierarchyHandling"] == "INCLUDE_CHILDREN"
    children = graph["children"]
    assert isinstance(children, list) and len(children) == 1
    root = children[0]
    assert root["id"] == "component_1"
    controller = next(child for child in root["children"] if child["id"] == "component_2")
    assert (controller["width"], controller["height"]) == (160.0, 100.0)  # The size hint.
    assert [port["id"] for port in controller["ports"]] == ["component_port_1", "component_port_4"]
    assert graph["edges"][0] == {  # type: ignore[index]
        "id": "component_exchange_1#0", "sources": ["component_port_1"], "targets": ["component_port_2"],
        "labels": [{"text": "Pump control", "width": 84.0, "height": 15.0}],
    }  # fmt: skip


def test_read_layout_uses_absolute_coordinates() -> None:
    laid_out = {
        "width": 330, "height": 120,
        "children": [{"id": "a", "x": 12, "y": 12, "width": 300, "height": 90, "children": [
            {"id": "b", "x": 12, "y": 30, "width": 120, "height": 50,
             "ports": [{"id": "p", "x": 120, "y": 20, "width": 10, "height": 10,
                        "labels": [{"text": "P", "x": 12, "y": -15}]}]},
        ]}],
        "edges": [{"id": "e#0", "container": "a", "labels": [{"text": "E", "x": 150, "y": 30}],
                   "sections": [{"startPoint": {"x": 142, "y": 55}, "bendPoints": [{"x": 150, "y": 55}],
                                 "endPoint": {"x": 162, "y": 55}}]}],
    }  # fmt: skip
    geometry = read_layout(laid_out)
    assert geometry.boxes == [
        Box("a", "block", 12, 12, 300, 90, container=True),
        Box("b", "block", 24, 42, 120, 50),
        Box("p", "port", 144, 62, 10, 10),
    ]
    assert geometry.paths == [GeometryPath("e", "line", ((154, 67), (162, 67), (174, 67)))]
    assert geometry.labels == [PlacedLabel("p", "P", 156, 47), PlacedLabel("e", "E", 162, 42)]


def test_sequence_layout(runner: Runner, repository: Repository) -> None:
    result = content(runner, "functional_sequence_1")
    geometry = sequence_layout(result, Presentation(runner, "functional_sequence"), repository.model, runner.evaluator)
    participants = [box for box in geometry.boxes if box.kind == "participant"]
    assert [box.element for box in participants] == result.participants
    assert all(a.x + a.width < b.x for a, b in zip(participants, participants[1:]))
    messages = [path for path in geometry.paths if path.kind == "line"]
    assert [path.element for path in messages] == ["functional_exchange_1", "functional_exchange_2", "functional_exchange_3"]
    # Messages go from the sender's lifeline to the receiver's, one row below the other.
    centre = {box.element: box.x + box.width / 2 for box in participants}
    assert messages[1].points == ((centre["logical_function_3"], messages[1].points[0][1]),
                                  (centre["logical_function_2"], messages[1].points[0][1]))  # fmt: skip
    assert messages[0].points[0][1] < messages[1].points[0][1] < messages[2].points[0][1]


# --- SVG ----------------------------------------------------------------------------------------------------


def test_svg(runner: Runner) -> None:
    result = content(runner, "logical_dataflow_2")
    geometry = Geometry(
        400, 100,
        boxes=[Box("logical_function_2", "block", 10, 10, 120, 50), Box("function_port_5", "port", 130, 30, 10, 10)],
        paths=[GeometryPath("functional_exchange_3", "line", ((140, 35), (200, 35)))],
        labels=[PlacedLabel("function_port_5", "Ready", 142, 40)],
    )  # fmt: skip
    presentation = Presentation(runner, "logical_dataflow")
    svg = render_svg(result, geometry, presentation, {"logical_function_2": "stroke-width: 3px"}, "<g id='x'/>", ".x {}\n")
    root = ElementTree.fromstring(svg)
    assert root.get("class") == "diagram logical_dataflow"
    groups = {g.get("data-id"): g for g in root.iter(f"{SVG}g") if g.get("data-id")}
    function = groups["logical_function_2"]
    assert function.get("class") == "logical_function function Entity highlighted"
    shape = function.find(f"{SVG}rect")
    assert shape is not None and shape.get("class") == "shape" and shape.get("rx") == "8"
    assert shape.get("style") == "stroke-width: 3px"
    assert [t.text for t in function.iter(f"{SVG}text")] == ["Control heater"]
    line = groups["functional_exchange_3"].find(f"{SVG}path")
    assert line is not None and line.get("d") == "M140,35 L200,35" and line.get("marker-end") == "url(#archtool-arrow)"
    assert [t.text for t in groups["function_port_5"].iter(f"{SVG}text")] == ["Ready"]
    assert ".x {}" in svg and "<g id='x'/>" in svg


def test_all_shapes_render() -> None:
    shapes = ["rectangle", "rounded_rectangle", "ellipse", "circle", "diamond", "hexagon", "octagon", "parallelogram",
              "trapezoid", "triangle", "stadium", "cylinder", "document", "note", "folder", "package", "component",
              "node", "cloud", "actor", "use_case", "state", "initial_state", "final_state", "decision", "fork_join",
              "lifeline", "activation", "#custom"]  # fmt: skip
    for shape in shapes:
        svg = f'<svg xmlns="http://www.w3.org/2000/svg">{_shape(shape, 0, 0, 100, 60, "")}</svg>'
        root = ElementTree.fromstring(svg)
        assert all("shape" in (child.get("class") or "") for child in root), shape
    assert len(LINE_ENDINGS) == 20  # Plus "none".


def test_text_is_escaped(runner: Runner) -> None:
    result = DiagramContent("x_1", "mission", Stereotype.USE_CASE_DIAGRAM)
    geometry = Geometry(100, 100, boxes=[Box("actor_1", "block", 0, 0, 50, 80)])
    svg = render_svg(result, geometry, Presentation(runner, "mission"), {"actor_1": 'a"<b>'}, "", "")
    ElementTree.fromstring(svg)
    assert 'style="a&quot;&lt;b&gt;"' in svg


# --- Rendering with ELK -------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def elk() -> list[str]:
    if shutil.which("elk") is None and shutil.which("npx") is None:
        pytest.skip("elk-cli is not available")
    return elk_command("elk")


def test_render_all_example_diagrams(repository: Repository, elk: list[str], tmp_path: Path) -> None:
    renderer = Renderer(repository, elk)
    rendered = renderer.render_to(tmp_path)
    assert [r.diagram for r in rendered] == sorted(repository.model.diagrams, key=lambda i: (i.rsplit("_", 1)[0], int(i.rsplit("_", 1)[1])))
    for result in rendered:
        root = ElementTree.fromstring(result.path.read_text())
        ids = {g.get("data-id") for g in root.iter(f"{SVG}g")}
        assert ids - {None}, result.diagram
    # Rendering is deterministic.
    assert renderer.render("physical_architecture_1") == (tmp_path / "physical_architecture_1.svg").read_text()


def test_render_errors(repository: Repository, elk: list[str]) -> None:
    with pytest.raises(RenderError, match="there is no diagram"):
        Renderer(repository, elk).render("mission_9")
    with pytest.raises(RenderError, match="cannot run"):
        Renderer(repository, ["no-such-elk-command"]).render("mission_1")


def test_cli_render(elk: list[str], tmp_path: Path) -> None:
    output, errors = io.StringIO(), io.StringIO()
    assert run_render(SIMPLIFIED_ARCADIA, ["mission_1", "functional_sequence_1"], tmp_path, output, errors) == 0
    assert [json.loads(line)["diagram"] for line in output.getvalue().splitlines()] == ["mission_1", "functional_sequence_1"]
    assert (tmp_path / "mission_1.svg").exists()
    assert run_render(SIMPLIFIED_ARCADIA, ["mission_7"], tmp_path, output, errors) == 1
    assert "there is no diagram 'mission_7'" in errors.getvalue()


# --- Position hints -----------------------------------------------------------------------------------------


def hinted_layout() -> tuple[DiagramContent, Geometry]:
    """A container `c_1` with blocks `a_1` (with port `p_1`) and `b_1` (with port `p_2`), and a line between the ports."""
    content = DiagramContent("d_1", "d", Stereotype.BLOCK_DIAGRAM, blocks=["a_1", "b_1", "c_1"],
                             parents={"a_1": "c_1", "b_1": "c_1"}, ports={"a_1": ["p_1"], "b_1": ["p_2"]},
                             lines=[Line("e_1", "p_1", "p_2")])  # fmt: skip
    geometry = Geometry(
        400, 200,
        boxes=[Box("c_1", "block", 10, 10, 380, 120, container=True), Box("a_1", "block", 30, 50, 100, 50),
               Box("p_1", "port", 130, 70, 10, 10), Box("b_1", "block", 250, 50, 100, 50), Box("p_2", "port", 240, 70, 10, 10)],
        paths=[GeometryPath("e_1", "line", ((140, 75), (240, 75)))],
        labels=[PlacedLabel("e_1", "E", 180, 60), PlacedLabel("p_1", "P", 142, 80)],
    )  # fmt: skip
    return content, geometry


def boxes(geometry: Geometry) -> dict[str, tuple[float, float, float, float]]:
    return {b.element: (b.x, b.y, b.width, b.height) for b in geometry.boxes}


def test_position_hint_moves_block_with_its_ports() -> None:
    content, geometry = hinted_layout()
    result = apply_position_hints(geometry, content, {"a_1": Layout("a_1", 20, 100)}, orthogonal=True)
    # Relative to the enclosing block, at (10, 10).
    assert boxes(result)["a_1"] == (30, 110, 100, 50)
    assert boxes(result)["p_1"] == (130, 130, 10, 10)
    # The enclosing block grows to contain it, and the line is rerouted orthogonally from port to port.
    assert boxes(result)["c_1"] == (10, 10, 380, 162)
    assert result.paths == [GeometryPath("e_1", "line", ((140, 135), (190, 135), (190, 75), (240, 75)))]
    # The line's label is now placed by the renderer; the port's label moves with its port.
    assert result.labels == [PlacedLabel("p_1", "P", 142, 140)]
    assert result.height >= 172


def test_position_hint_moves_contents_along() -> None:
    content, geometry = hinted_layout()
    result = apply_position_hints(geometry, content, {"c_1": Layout("c_1", 50, 30)}, orthogonal=False)
    assert boxes(result)["c_1"] == (50, 30, 380, 120)
    assert boxes(result)["a_1"] == (70, 70, 100, 50)
    assert boxes(result)["p_2"] == (280, 90, 10, 10)
    assert result.paths == [GeometryPath("e_1", "line", ((180, 95), (280, 95)))]
    assert result.width == 442


def test_ports_follow_the_edge_of_a_growing_block() -> None:
    content, geometry = hinted_layout()
    content.ports["c_1"] = ["p_3"]
    geometry.boxes.append(Box("p_3", "port", 390, 60, 10, 10))  # On the right edge of c_1.
    result = apply_position_hints(geometry, content, {"b_1": Layout("b_1", 400, 50)}, orthogonal=True)
    c = boxes(result)["c_1"]
    assert boxes(result)["p_3"][0] == c[0] + c[2]


def test_rendered_position_hint(repository: Repository, elk: list[str]) -> None:
    svg = Renderer(repository, elk).render("physical_architecture_1")
    root = ElementTree.fromstring(svg)
    rects = {g.get("data-id"): g.find(f"{SVG}rect") for g in root.iter(f"{SVG}g") if g.get("data-id")}
    machine, controller = rects["component_1"], rects["component_2"]
    assert machine is not None and controller is not None
    # `layout component_2 at 330,110 size 160x100`
    assert float(controller.get("x", 0)) - float(machine.get("x", 0)) == 330
    assert float(controller.get("y", 0)) - float(machine.get("y", 0)) == 110
    assert (controller.get("width"), controller.get("height")) == ("160", "100")


def test_negative_positions_are_moved_into_view() -> None:
    content, geometry = hinted_layout()
    result = apply_position_hints(geometry, content, {"c_1": Layout("c_1", -30, 0)}, orthogonal=True)
    assert boxes(result)["c_1"][0] == 12


def test_preview_of_generated_diagram(repository: Repository, elk: list[str]) -> None:
    renderer = Renderer(repository, elk)
    root = ElementTree.fromstring(renderer.preview("requirement_breakdown", "requirement_breakdown", (("root", "requirement_1"),)))
    shown = {g.get("data-id") for g in root.iter(f"{SVG}g")} - {None}
    assert shown == {"requirement_1", "requirement_4", "requirement_5",
                     "requirement_contains_requirement_1", "requirement_contains_requirement_2"}  # fmt: skip
    with pytest.raises(RenderError, match="not an element of the model"):
        renderer.preview("requirement_breakdown", "requirement_breakdown", (("root", "requirement_9"),))
    with pytest.raises(RenderError, match="needs a value for parameter 'root'"):
        renderer.preview("requirement_breakdown", "requirement_breakdown", ())


def test_breakdown_of_several_trees(runner: Runner, elk: list[str]) -> None:
    # All requirements: "Brew coffee" with its parts, and two requirements that are not broken down.
    diagram = runner.model.diagrams["requirement_breakdown_2"]
    geometry = elk_layout(content(runner, diagram.id), Presentation(runner, diagram.type), {}, elk)
    blocks = boxes(geometry)
    assert set(blocks) == {f"requirement_{n}" for n in range(1, 6)}
    # The trees are placed side by side: their roots are in one row.
    assert blocks["requirement_1"][1] == blocks["requirement_2"][1] == blocks["requirement_3"][1]
    # The diagram is as large as its contents, although ELK reports a smaller graph for a forest.
    assert all(x + w <= geometry.width and y + h <= geometry.height for x, y, w, h in blocks.values())
