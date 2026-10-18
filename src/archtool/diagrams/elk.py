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

"""Laying out block, breakdown and use-case diagrams with the Eclipse Layout Kernel, through elk-cli.

The diagram is converted into an ELK JSON graph: blocks become nodes (nested for the hierarchy), ports become ELK
ports, and lines become edges. elk-cli computes the coordinates. See "Layout engine" in doc/architecture.md.
"""

import json
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path as FilePath

from archtool.diagrams.content import DiagramContent
from archtool.diagrams.geometry import (
    BLOCK_MIN_HEIGHT,
    BLOCK_MIN_WIDTH,
    CONTAINER_LABEL_HEIGHT,
    PORT_SIZE,
    Box,
    Geometry,
    Path,
    PlacedLabel,
    text_size,
)
from archtool.diagrams.hints import apply_position_hints, fit, port_side
from archtool.diagrams.presentation import Presentation
from archtool.formats.diagram_file import Layout
from archtool.metamodel import Stereotype

NPX_COMMAND = "npx -y @kieler/elk-cli"
MARGIN = 12.0
ACTOR_WIDTH = 50.0
ACTOR_HEIGHT = 70.0

type _Json = dict[str, object]


class LayoutError(Exception):
    """elk-cli could not be run, or failed."""


def elk_command(configured: str) -> list[str]:
    """The command that runs elk-cli. If the default `elk` is not installed, elk-cli is run with npx."""
    if configured == "elk" and shutil.which("elk") is None and shutil.which("npx") is not None:
        return shlex.split(NPX_COMMAND)
    return shlex.split(configured)


def elk_layout(
    content: DiagramContent, presentation: Presentation, hints: Mapping[str, Layout], command: list[str]
) -> Geometry:
    graph = elk_graph(content, presentation, hints)
    geometry = read_layout(run_elk(graph, command))
    if any(hint.element in content.blocks for hint in hints.values()):
        geometry = apply_position_hints(geometry, content, hints, orthogonal=content.stereotype is Stereotype.BLOCK_DIAGRAM)
    geometry = attach_inner_lines(geometry, content)
    # ELK's tree layout can report a graph narrower than its nodes when it places several trees side by side.
    return fit(geometry)


def attach_inner_lines(geometry: Geometry, content: DiagramContent) -> Geometry:
    """Let lines that go into a block from one of its ports start at the inner side of the port.

    Ports straddle the border of their block. Lines are attached to the outer side of a port, which is right for
    lines to the outside, but makes a line to the block's contents, such as a delegation to a part, cross the port.
    """
    boxes = {box.element: box for box in geometry.boxes}
    owners = {port: block for block, ports in content.ports.items() for port in ports}
    lines = {line.element: line for line in content.lines}
    paths = []
    for path in geometry.paths:
        line = lines.get(path.element)
        points = list(path.points)
        if line is not None and len(points) >= 2:
            for end, index, neighbour in ((line.start, 0, 1), (line.end, -1, -2)):
                port, owner = boxes.get(end), boxes.get(owners.get(end, ""))
                if port is None or owner is None:
                    continue
                (x, y), (nx, ny) = points[index], points[neighbour]
                if not (owner.x < nx < owner.x + owner.width and owner.y < ny < owner.y + owner.height):
                    continue  # The line goes to the outside.
                side = port_side(port, owner)
                # Only the end segment, which is perpendicular to the side, moves; the line stays orthogonal.
                if side in ("left", "right") and abs(y - ny) < 0.5:
                    points[index] = (port.x + port.width if side == "left" else port.x, y)
                elif side in ("top", "bottom") and abs(x - nx) < 0.5:
                    points[index] = (x, port.y + port.height if side == "top" else port.y)
        paths.append(Path(path.element, path.kind, tuple(points)))
    return Geometry(geometry.width, geometry.height, geometry.boxes, paths, geometry.labels)


def elk_graph(content: DiagramContent, presentation: Presentation, hints: Mapping[str, Layout]) -> _Json:
    """The ELK JSON graph of a diagram."""
    options: dict[str, str] = {
        "elk.algorithm": "layered",
        "elk.direction": "RIGHT",
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.spacing.nodeNode": "30",
        "elk.layered.spacing.nodeNodeBetweenLayers": "50",
        "elk.spacing.edgeLabel": "4",
        "elk.spacing.labelPortHorizontal": "4",
        "elk.spacing.labelPortVertical": "2",
        "elk.padding": f"[top={MARGIN},left={MARGIN},bottom={MARGIN},right={MARGIN}]",
    }
    if content.stereotype is Stereotype.BLOCK_DIAGRAM:
        options["elk.hierarchyHandling"] = "INCLUDE_CHILDREN"
    elif content.stereotype is Stereotype.BREAKDOWN_DIAGRAM:
        # A breakdown of several elements is a forest: its trees are placed side by side, rather than packed in rows.
        options |= {"elk.algorithm": "mrtree", "elk.direction": "DOWN", "elk.aspectRatio": "100"}
        del options["elk.edgeRouting"]

    def node(block: str) -> _Json:
        labels = [label.text for label in presentation.labels(block)]
        text_width, text_height = text_size(labels)
        width = max(BLOCK_MIN_WIDTH, text_width + 24)
        height = max(BLOCK_MIN_HEIGHT, text_height + 20)
        result: _Json = {"id": block}
        children = content.children(block)
        if presentation.look(block).shape == "actor":
            # A stick figure, with its label below it.
            width, height = max(ACTOR_WIDTH, text_width + 8), ACTOR_HEIGHT + text_height
        hint = hints.get(block)
        if hint is not None and hint.size is not None:
            width, height = float(hint.size[0]), float(hint.size[1])
        if children:
            padding = f"[top={CONTAINER_LABEL_HEIGHT + text_height},left={MARGIN},bottom={MARGIN},right={MARGIN}]"
            result["layoutOptions"] = {
                "elk.padding": padding,
                "elk.nodeSize.constraints": "MINIMUM_SIZE",
                "elk.nodeSize.minimum": f"({width}, {height})",
            }
            result["children"] = [node(child) for child in children]
        else:
            result["width"] = width
            result["height"] = height
        ports = content.ports.get(block, [])
        if ports:
            result["ports"] = [
                # Ports straddle the border of their block: half inside, half outside.
                {"id": port, "width": PORT_SIZE, "height": PORT_SIZE, "labels": elk_labels(port),
                 "layoutOptions": {"elk.port.borderOffset": str(-PORT_SIZE / 2)}}
                for port in ports
            ]
            options = result.setdefault("layoutOptions", {})
            assert isinstance(options, dict)
            options["elk.portLabels.placement"] = "[OUTSIDE]"
        return result

    def elk_labels(element: str) -> list[_Json]:
        result: list[_Json] = []
        for label in presentation.labels(element):
            width, height = text_size([label.text])
            result.append({"text": label.text, "width": width, "height": height})
        return result

    edges = [{"id": f"{line.element}#{index}", "sources": [line.start], "targets": [line.end], "labels": elk_labels(line.element)}
             for index, line in enumerate(content.lines)]  # fmt: skip
    return {"id": "root", "layoutOptions": options, "children": [node(b) for b in content.children(None)], "edges": edges}


def run_elk(graph: _Json, command: list[str]) -> _Json:
    """Run elk-cli on a graph, and return the laid-out graph."""
    with tempfile.TemporaryDirectory(prefix="archtool-") as directory:
        path = FilePath(directory) / "graph.json"
        path.write_text(json.dumps(graph), encoding="utf-8")
        try:
            process = subprocess.run([*command, "-f", str(path)], capture_output=True, text=True, timeout=120, check=False)
        except FileNotFoundError:
            raise LayoutError(
                f"cannot run '{' '.join(command)}': install elk-cli with 'npm install -g @kieler/elk-cli', "
                "or set render.elk in archtool.toml"
            ) from None
        except subprocess.TimeoutExpired:
            raise LayoutError(f"'{' '.join(command)}' did not finish within 120 seconds") from None
    if process.returncode != 0:
        raise LayoutError(f"elk-cli failed: {process.stderr.strip() or process.stdout.strip()}")
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError:
        raise LayoutError(f"elk-cli did not produce a layout: {process.stdout.strip()[:200]}") from None
    if not isinstance(result, dict):
        raise LayoutError("elk-cli did not produce a layout")
    return result


def read_layout(graph: _Json) -> Geometry:
    """Read the absolute coordinates of blocks, ports and lines from a laid-out graph."""
    geometry = Geometry(_number(graph, "width"), _number(graph, "height"))
    offsets: dict[str, tuple[float, float]] = {"root": (0.0, 0.0)}

    def visit(node: _Json, x0: float, y0: float) -> None:
        identifier = str(node["id"])
        x, y = x0 + _number(node, "x"), y0 + _number(node, "y")
        offsets[identifier] = (x, y)
        children = _list(node, "children")
        geometry.boxes.append(
            Box(identifier, "block", x, y, _number(node, "width"), _number(node, "height"), container=bool(children))
        )
        for port in _list(node, "ports"):
            port_x, port_y = x + _number(port, "x"), y + _number(port, "y")
            port_id = str(port["id"])
            geometry.boxes.append(Box(port_id, "port", port_x, port_y, _number(port, "width"), _number(port, "height")))
            for label in _list(port, "labels"):
                geometry.labels.append(
                    PlacedLabel(port_id, str(label.get("text", "")), port_x + _number(label, "x"), port_y + _number(label, "y"))
                )
        for child in children:
            visit(child, x, y)

    for child in _list(graph, "children"):
        visit(child, 0.0, 0.0)
    for edge in _list(graph, "edges"):
        x0, y0 = offsets.get(str(edge.get("container", "root")), (0.0, 0.0))
        points: list[tuple[float, float]] = []
        for section in _list(edge, "sections"):
            for point in [section.get("startPoint"), *_list(section, "bendPoints"), section.get("endPoint")]:
                if isinstance(point, dict):
                    points.append((x0 + _number(point, "x"), y0 + _number(point, "y")))
        element = str(edge["id"]).split("#")[0]
        geometry.paths.append(Path(element, "line", tuple(points)))
        for label in _list(edge, "labels"):
            text = str(label.get("text", ""))
            geometry.labels.append(PlacedLabel(element, text, x0 + _number(label, "x"), y0 + _number(label, "y")))
    return geometry


def _number(node: Mapping[str, object], key: str) -> float:
    value = node.get(key, 0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _list(node: Mapping[str, object], key: str) -> list[_Json]:
    value = node.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
