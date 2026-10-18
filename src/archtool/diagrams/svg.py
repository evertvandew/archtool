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

"""Rendering a laid-out diagram as SVG.

Each element is an SVG group with its type, the types it extends and its stereotypes as CSS classes. Within the
group, the stylesheet can address the `shape`, `line` and `label` parts. See "Styles" and "Shapes and line
endings" in doc/file_formats.md.
"""

import math
from collections.abc import Mapping
from html import escape

from archtool.diagrams.content import DiagramContent
from archtool.diagrams.geometry import LINE_HEIGHT, Box, Geometry, Path, PlacedLabel
from archtool.diagrams.presentation import Label, Presentation

BASE_STYLE = """\
.background { fill: #ffffff; }
.shape { fill: #ffffff; stroke: #333333; stroke-width: 1px; }
.shape.filled { fill: #333333; }
.line { fill: none; stroke: #333333; stroke-width: 1px; }
.lifeline > .line { stroke-dasharray: 4 4; }
.label { font-family: sans-serif; font-size: 12px; fill: #000000; stroke: none; }
"""

# Line endings, drawn pointing to the right with the tip at (12, 6). Each is (path, filled).
LINE_ENDINGS: dict[str, tuple[str, str]] = {
    "arrow": ("M0,2 L12,6 L0,10 Z", "#333333"),
    "filled_arrow": ("M0,0 L12,6 L0,12 Z", "#333333"),
    "open_arrow": ("M0,0 L12,6 L0,12", "none"),
    "double_arrow": ("M0,0 L6,6 L0,12 M6,0 L12,6 L6,12", "none"),
    "half_arrow": ("M0,0 L12,6", "none"),
    "triangle": ("M0,0 L12,6 L0,12 Z", "#ffffff"),
    "open_triangle": ("M0,0 L12,6 L0,12 Z", "none"),
    "diamond": ("M0,6 L6,1 L12,6 L6,11 Z", "#ffffff"),
    "filled_diamond": ("M0,6 L6,1 L12,6 L6,11 Z", "#333333"),
    "circle": ("M1,6 A5,5 0 1,0 11,6 A5,5 0 1,0 1,6 Z", "#ffffff"),
    "filled_circle": ("M1,6 A5,5 0 1,0 11,6 A5,5 0 1,0 1,6 Z", "#333333"),
    "square": ("M1,1 L11,1 L11,11 L1,11 Z", "#ffffff"),
    "filled_square": ("M1,1 L11,1 L11,11 L1,11 Z", "#333333"),
    "bar": ("M10,0 L10,12", "none"),
    "cross": ("M2,1 L10,11 M10,1 L2,11", "none"),
    "one": ("M6,0 L6,12", "none"),
    "many": ("M0,6 L12,0 M0,6 L12,12 M0,6 L12,6", "none"),
    "zero_or_one": ("M10,0 L10,12 M0,6 A3,3 0 1,0 6,6 A3,3 0 1,0 0,6", "#ffffff"),
    "one_or_many": ("M2,0 L2,12 M4,6 L12,0 M4,6 L12,12", "none"),
    "zero_or_many": ("M0,6 A3,3 0 1,0 6,6 A3,3 0 1,0 0,6 M6,6 L12,0 M6,6 L12,12", "#ffffff"),
}


def render_svg(
    content: DiagramContent,
    geometry: Geometry,
    presentation: Presentation,
    element_styles: Mapping[str, str],
    defs: str,
    styles: str,
) -> str:
    width, height = max(geometry.width, 1.0), max(geometry.height, 1.0)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(width)}" height="{_n(height)}" '
        f'viewBox="0 0 {_n(width)} {_n(height)}" class="diagram {escape(content.type)}">',
        "<defs>",
        *_markers(),
        defs.rstrip("\n"),
        "</defs>",
        f"<style><![CDATA[\n{BASE_STYLE}{styles}]]></style>",
        f'<rect class="background" width="{_n(width)}" height="{_n(height)}"/>',
    ]
    renderer = _Renderer(content, presentation, element_styles, geometry.labels)
    parts += [renderer.path(path) for path in geometry.paths if path.kind == "lifeline"]
    parts += [renderer.box(box) for box in geometry.boxes]
    parts += [renderer.path(path) for path in geometry.paths if path.kind == "line"]
    parts.append("</svg>")
    return "\n".join(part for part in parts if part) + "\n"


def _markers() -> list[str]:
    return [
        f'<marker id="archtool-{name}" viewBox="0 0 12 12" refX="12" refY="6" markerWidth="12" markerHeight="12" '
        f'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
        f'<path d="{path}" fill="{fill}" stroke="#333333" stroke-width="1"/></marker>'
        for name, (path, fill) in LINE_ENDINGS.items()
    ]


class _Renderer:
    def __init__(
        self,
        content: DiagramContent,
        presentation: Presentation,
        element_styles: Mapping[str, str],
        placed: list[PlacedLabel],
    ) -> None:
        self.content = content
        self.presentation = presentation
        self.element_styles = element_styles
        self.placed: dict[str, list[PlacedLabel]] = {}
        for label in placed:
            self.placed.setdefault(label.element, []).append(label)

    def placed_labels(self, element: str) -> list[str]:
        return [_text(label.text, "placed", label.x, label.y + 11, "start") for label in self.placed.get(element, [])]

    def classes(self, element: str, *extra: str) -> str:
        classes = [self.presentation.classes(element), *extra]
        if element in self.content.highlighted:
            classes.append("highlighted")
        return escape(" ".join(c for c in classes if c))

    def style(self, element: str) -> str:
        css = self.element_styles.get(element)
        return f' style="{escape(css)}"' if css else ""

    def box(self, box: Box) -> str:
        extra = box.kind if box.kind in ("participant", "activation") else ""
        look = self.presentation.look(box.element)
        shape = "rectangle" if box.kind == "activation" else look.shape
        labels = self.presentation.labels(box.element) if box.kind != "activation" else []
        texts = self.placed_labels(box.element) if box.element in self.placed else _box_labels(box, labels)
        lines = [
            f'<g class="{self.classes(box.element, extra)}" data-id="{escape(box.element)}">',
            _shape(shape, box.x, box.y, box.width, box.height, self.style(box.element)),
            *texts,
            "</g>",
        ]
        return "\n".join(lines)

    def path(self, path: Path) -> str:
        if not path.points:
            return ""
        data = " ".join(f"{'M' if i == 0 else 'L'}{_n(x)},{_n(y)}" for i, (x, y) in enumerate(path.points))
        if path.kind == "lifeline":
            return f'<g class="lifeline" data-id="{escape(path.element)}"><path class="line" d="{data}"/></g>'
        look = self.presentation.look(path.element)
        markers = _marker("marker-start", look.start) + _marker("marker-end", look.end)
        return "\n".join(
            [
                f'<g class="{self.classes(path.element)}" data-id="{escape(path.element)}">',
                f'<path class="line" d="{data}"{markers}{self.style(path.element)}/>',
                *(self.placed_labels(path.element) if path.element in self.placed
                  else _line_labels(path, self.presentation.labels(path.element))),
                "</g>",
            ]
        )


def _marker(attribute: str, ending: str) -> str:
    if ending == "none":
        return ""
    if ending.startswith("#"):
        return f' {attribute}="url({escape(ending)})"'
    if ending in LINE_ENDINGS:
        return f' {attribute}="url(#archtool-{ending})"'
    return ""


# --- Shapes -------------------------------------------------------------------------------------------------


def _shape(shape: str, x: float, y: float, w: float, h: float, style: str) -> str:
    """The SVG of a built-in shape, or of an SVG symbol from the meta model (`#id`)."""
    if shape.startswith("#"):
        return f'<use class="shape" href="{escape(shape)}" x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"{style}/>'
    cx, cy, r = x + w / 2, y + h / 2, min(w, h) / 2
    right, bottom = x + w, y + h

    def polygon(*points: tuple[float, float], extra: str = "") -> str:
        coordinates = " ".join(f"{_n(px)},{_n(py)}" for px, py in points)
        return f'<polygon class="shape{extra}" points="{coordinates}"{style}/>'

    def path(data: str, extra: str = "") -> str:
        return f'<path class="shape{extra}" d="{data}"{style}/>'

    def rect(rx: float = 0.0, extra: str = "") -> str:
        rounding = f' rx="{_n(rx)}"' if rx else ""
        return f'<rect class="shape{extra}" x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"{rounding}{style}/>'

    match shape:
        case "rounded_rectangle":
            return rect(8)
        case "stadium":
            return rect(h / 2)
        case "state":
            return rect(12)
        case "ellipse" | "use_case":
            return f'<ellipse class="shape" cx="{_n(cx)}" cy="{_n(cy)}" rx="{_n(w / 2)}" ry="{_n(h / 2)}"{style}/>'
        case "circle":
            return f'<circle class="shape" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}"{style}/>'
        case "initial_state":
            return f'<circle class="shape filled" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}"{style}/>'
        case "final_state":
            return (f'<circle class="shape" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}"{style}/>'
                    f'<circle class="shape filled" cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r * 0.6)}"/>')  # fmt: skip
        case "diamond" | "decision":
            return polygon((cx, y), (right, cy), (cx, bottom), (x, cy))
        case "hexagon":
            d = min(w / 4, h / 2)
            return polygon((x + d, y), (right - d, y), (right, cy), (right - d, bottom), (x + d, bottom), (x, cy))
        case "octagon":
            d = min(w, h) * 0.29
            return polygon((x + d, y), (right - d, y), (right, y + d), (right, bottom - d), (right - d, bottom),
                           (x + d, bottom), (x, bottom - d), (x, y + d))  # fmt: skip
        case "parallelogram":
            d = min(w / 4, h / 2)
            return polygon((x + d, y), (right, y), (right - d, bottom), (x, bottom))
        case "trapezoid":
            d = min(w / 4, h / 2)
            return polygon((x + d, y), (right - d, y), (right, bottom), (x, bottom))
        case "triangle":
            return polygon((cx, y), (right, bottom), (x, bottom))
        case "cylinder":
            e = min(h / 6, 12.0)
            return path(f"M{_n(x)},{_n(y + e)} A{_n(w / 2)},{_n(e)} 0 0,1 {_n(right)},{_n(y + e)} "
                        f"L{_n(right)},{_n(bottom - e)} A{_n(w / 2)},{_n(e)} 0 0,1 {_n(x)},{_n(bottom - e)} Z "
                        f"M{_n(x)},{_n(y + e)} A{_n(w / 2)},{_n(e)} 0 0,0 {_n(right)},{_n(y + e)}")  # fmt: skip
        case "document":
            wave = min(h / 6, 10.0)
            return path(f"M{_n(x)},{_n(y)} L{_n(right)},{_n(y)} L{_n(right)},{_n(bottom - wave)} "
                        f"C{_n(right - w / 4)},{_n(bottom - 2 * wave)} {_n(x + w / 2)},{_n(bottom + wave)} "
                        f"{_n(x)},{_n(bottom - wave)} Z")  # fmt: skip
        case "note":
            fold = min(12.0, w / 4, h / 4)
            return (polygon((x, y), (right - fold, y), (right, y + fold), (right, bottom), (x, bottom))
                    + path(f"M{_n(right - fold)},{_n(y)} L{_n(right - fold)},{_n(y + fold)} L{_n(right)},{_n(y + fold)}"))  # fmt: skip
        case "folder" | "package":
            tab_width, tab_height = min(w / 3, 60.0), min(h / 5, 12.0)
            return polygon((x, y), (x + tab_width, y), (x + tab_width + 4, y + tab_height), (right, y + tab_height),
                           (right, bottom), (x, bottom))  # fmt: skip
        case "component":
            return (rect() + f'<rect class="shape" x="{_n(x - 6)}" y="{_n(y + 10)}" width="12" height="8"/>'
                    f'<rect class="shape" x="{_n(x - 6)}" y="{_n(y + 24)}" width="12" height="8"/>')  # fmt: skip
        case "node":
            d = min(10.0, w / 6, h / 6)
            return (polygon((x, y + d), (right - d, y + d), (right - d, bottom), (x, bottom))
                    + polygon((x, y + d), (x + d, y), (right, y), (right - d, y + d))
                    + polygon((right - d, y + d), (right, y), (right, bottom - d), (right - d, bottom)))  # fmt: skip
        case "cloud":
            return path(f"M{_n(x + w * 0.25)},{_n(bottom - h * 0.1)} "
                        f"A{_n(w * 0.2)},{_n(h * 0.25)} 0 0,1 {_n(x + w * 0.2)},{_n(y + h * 0.4)} "
                        f"A{_n(w * 0.25)},{_n(h * 0.3)} 0 0,1 {_n(x + w * 0.6)},{_n(y + h * 0.2)} "
                        f"A{_n(w * 0.22)},{_n(h * 0.3)} 0 0,1 {_n(right - w * 0.1)},{_n(y + h * 0.6)} "
                        f"A{_n(w * 0.2)},{_n(h * 0.25)} 0 0,1 {_n(x + w * 0.7)},{_n(bottom - h * 0.1)} Z")  # fmt: skip
        case "actor":
            # A stick figure in the upper part of the box, leaving room for a label at the bottom.
            figure = max(h - LINE_HEIGHT - 4, h * 0.6)
            head = figure / 8
            neck = y + 2 * head + 2
            hips = y + figure * 0.6
            feet = y + figure
            arm = min(w / 2, figure / 3)
            return (f'<circle class="shape" cx="{_n(cx)}" cy="{_n(y + head + 1)}" r="{_n(head)}"{style}/>'
                    + path(f"M{_n(cx)},{_n(neck)} L{_n(cx)},{_n(hips)} M{_n(cx - arm)},{_n(neck + figure * 0.12)} "
                           f"L{_n(cx + arm)},{_n(neck + figure * 0.12)} M{_n(cx - arm * 0.8)},{_n(feet)} "
                           f"L{_n(cx)},{_n(hips)} L{_n(cx + arm * 0.8)},{_n(feet)}"))  # fmt: skip
        case "fork_join":
            return rect(extra=" filled")
        case _:  # rectangle, lifeline, activation, and unknown shapes
            return rect()


# --- Labels -------------------------------------------------------------------------------------------------


def _box_labels(box: Box, labels: list[Label]) -> list[str]:
    result: list[str] = []
    offsets: dict[str, float] = {}
    default = "outside" if box.kind == "port" else "top" if box.container else "centre"
    if box.kind == "activation":
        default = "right"
    for label in labels:
        anchor = label.anchor or default
        lines = label.text.split("\n")
        # Labels at the top (or bottom) are stacked, even with different anchors, so that they never overlap.
        row = anchor.split("_")[0] if anchor.startswith(("top", "bottom")) else anchor
        offset = offsets.get(row, 0.0)
        offsets[row] = offset + len(lines) * LINE_HEIGHT
        x, y, align = _box_anchor(box, anchor, len(lines))
        result.append(_text(label.text, anchor, x, y + offset if row != "bottom" else y - offset, align))
    return result


def _box_anchor(box: Box, anchor: str, lines: int) -> tuple[float, float, str]:
    x, y, w, h = box.x, box.y, box.width, box.height
    if box.kind == "port":
        if anchor == "inside":
            return x - 3, y - 2, "end"
        return x + w + 3, y - 2, "start"
    if box.kind == "activation" and anchor == "right":
        return x + w + 4, y + h / 2 + 4, "start"
    text_height = lines * LINE_HEIGHT
    column, row = {
        "top_left": ("left", "top"), "top": ("centre", "top"), "top_right": ("right", "top"),
        "left": ("left", "middle"), "centre": ("centre", "middle"), "right": ("right", "middle"),
        "bottom_left": ("left", "bottom"), "bottom": ("centre", "bottom"), "bottom_right": ("right", "bottom"),
    }.get(anchor, ("centre", "middle"))  # fmt: skip
    tx, align = {"left": (x + 6, "start"), "centre": (x + w / 2, "middle"), "right": (x + w - 6, "end")}[column]
    ty = {"top": y + 15, "middle": y + (h - text_height) / 2 + 11, "bottom": y + h - text_height + 9}[row]
    return tx, ty, align


def _line_labels(path: Path, labels: list[Label]) -> list[str]:
    result: list[str] = []
    for label in labels:
        anchor = label.anchor or "middle"
        if anchor == "start":
            (x, y), align = path.points[0], "start"
            x, y = x + 6, y - 5
        elif anchor == "end":
            (x, y), align = path.points[-1], "end"
            x, y = x - 6, y - 5
        else:
            (x, y), align = _midpoint(path.points), "middle"
            y -= 5
        result.append(_text(label.text, anchor, x, y, align))
    return result


def _midpoint(points: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    """The point halfway along a polyline."""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    remaining = sum(lengths) / 2
    for (a, b), length in zip(zip(points, points[1:]), lengths):
        if remaining <= length and length > 0:
            t = remaining / length
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        remaining -= length
    return points[0]


def _text(text: str, anchor: str, x: float, y: float, align: str) -> str:
    lines = text.split("\n")
    if len(lines) == 1:
        content = escape(text)
    else:
        content = "".join(
            f'<tspan x="{_n(x)}" dy="{0 if i == 0 else _n(LINE_HEIGHT)}">{escape(line)}</tspan>' for i, line in enumerate(lines)
        )
    return f'<text class="label {escape(anchor)}" x="{_n(x)}" y="{_n(y)}" text-anchor="{align}">{content}</text>'


def _n(value: float) -> str:
    """A coordinate, rounded to one decimal, without a trailing `.0`."""
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text
