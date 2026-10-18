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

"""The geometry of a laid-out diagram: boxes and lines, in absolute coordinates."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Box:
    """A block, port or other rectangular part of a diagram. `kind` is "block", "port", "participant" or
    "activation"; `container` tells whether the block contains other blocks."""

    element: str
    kind: str
    x: float
    y: float
    width: float
    height: float
    container: bool = False


@dataclass(frozen=True, slots=True)
class Path:
    """A line through `points`. `kind` is "line" for a relationship, or "lifeline"."""

    element: str
    kind: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class PlacedLabel:
    """A label whose position was computed by the layout: `x` and `y` are its top left corner."""

    element: str
    text: str
    x: float
    y: float


@dataclass(slots=True)
class Geometry:
    width: float
    height: float
    boxes: list[Box] = field(default_factory=list)  # In drawing order: enclosing blocks before their contents.
    paths: list[Path] = field(default_factory=list)
    # Labels placed by the layout, for lines and ports. Elements without placed labels are labelled by the renderer.
    labels: list[PlacedLabel] = field(default_factory=list)


# Sizes used when laying out labels. They match the default font of the stylesheet (12px sans-serif).
CHARACTER_WIDTH = 7.0
LINE_HEIGHT = 15.0
BLOCK_MIN_WIDTH = 120.0
BLOCK_MIN_HEIGHT = 50.0
PORT_SIZE = 10.0
CONTAINER_LABEL_HEIGHT = 28.0


def text_size(texts: list[str]) -> tuple[float, float]:
    """The approximate width and height of texts, each of which may span several lines."""
    lines = [line for text in texts for line in text.split("\n")]
    if not lines:
        return 0.0, 0.0
    return max(len(line) for line in lines) * CHARACTER_WIDTH, len(lines) * LINE_HEIGHT
