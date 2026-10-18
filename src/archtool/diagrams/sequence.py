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

"""Laying out sequence diagrams.

Participants are placed side by side, with their lifelines below them. Messages and processing follow each
other from top to bottom, in time order.
"""

from archtool.diagrams.content import DiagramContent
from archtool.diagrams.geometry import BLOCK_MIN_WIDTH, LINE_HEIGHT, Box, Geometry, Path, text_size
from archtool.diagrams.presentation import Presentation
from archtool.language.evaluator import Evaluator
from archtool.model import Model

MARGIN = 20.0
PARTICIPANT_HEIGHT = 40.0
PARTICIPANT_GAP = 60.0
ROW_HEIGHT = 40.0
ACTIVATION_WIDTH = 12.0
SELF_MESSAGE_WIDTH = 30.0


def sequence_layout(content: DiagramContent, presentation: Presentation, model: Model, evaluator: Evaluator) -> Geometry:
    boxes: dict[str, tuple[float, float]] = {}  # The left edge and width of each participant's box.
    x = MARGIN
    for participant in content.participants:
        width = max(BLOCK_MIN_WIDTH, text_size([label.text for label in presentation.labels(participant)])[0] + 24)
        boxes[participant] = (x, width)
        x += width + PARTICIPANT_GAP
    centres = {participant: left + width / 2 for participant, (left, width) in boxes.items()}
    width = x - PARTICIPANT_GAP + MARGIN
    rows_top = MARGIN + PARTICIPANT_HEIGHT + ROW_HEIGHT
    height = rows_top + len(content.events) * ROW_HEIGHT + MARGIN
    geometry = Geometry(max(width, 2 * MARGIN), height)
    for participant, (left, participant_width) in boxes.items():
        centre = centres[participant]
        geometry.boxes.append(Box(participant, "participant", left, MARGIN, participant_width, PARTICIPANT_HEIGHT))
        geometry.paths.append(Path(participant, "lifeline", ((centre, MARGIN + PARTICIPANT_HEIGHT), (centre, height - MARGIN))))
    for row, event in enumerate(content.events):
        y = rows_top + row * ROW_HEIGHT
        if event.participant is not None:
            if event.participant in centres:
                left = centres[event.participant] - ACTIVATION_WIDTH / 2
                geometry.boxes.append(Box(event.element, "activation", left, y - LINE_HEIGHT, ACTIVATION_WIDTH, 2 * LINE_HEIGHT))
            continue
        relationship = model.get(event.element)
        sender = evaluator.end_owner(relationship.id, "start")
        receiver = evaluator.end_owner(relationship.id, "end")
        if sender not in centres or receiver not in centres:
            continue
        x1, x2 = centres[sender], centres[receiver]
        points: tuple[tuple[float, float], ...]
        if sender == receiver:
            points = ((x1, y - 10), (x1 + SELF_MESSAGE_WIDTH, y - 10), (x1 + SELF_MESSAGE_WIDTH, y + 10), (x1, y + 10))
        else:
            points = ((x1, y), (x2, y))
        geometry.paths.append(Path(event.element, "line", points))
    return geometry

