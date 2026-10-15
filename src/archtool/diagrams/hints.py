"""Applying the position hints of a diagram (`layout <id> at x,y`) to its layout.

ELK cannot fix the position of some blocks while laying out the others, so position hints are applied after
ELK's layout:

1. Each hinted block is moved to its position, relative to the top-left corner of its enclosing block (or of the
   diagram), with its contents and ports.
2. Enclosing blocks grow where needed to keep containing their contents; ports on their right or bottom edge move
   with that edge.
3. Lines attached to anything that moved are rerouted: orthogonally in block diagrams, leaving each port away from
   its block, and straight in other diagrams.
   Their labels are placed by the renderer instead of ELK.

Everything else keeps the layout computed by ELK. Size hints are passed to ELK itself (see archtool.diagrams.elk).
"""

from collections.abc import Mapping
from dataclasses import replace

from archtool.diagrams.content import DiagramContent
from archtool.diagrams.geometry import CONTAINER_LABEL_HEIGHT, Box, Geometry, Path
from archtool.formats.diagram_file import Layout

MARGIN = 12.0
# How far a rerouted line runs straight out of a port before it turns, when it cannot turn straight away.
STUB = 12.0

type Point = tuple[float, float]


def apply_position_hints(geometry: Geometry, content: DiagramContent, hints: Mapping[str, Layout], *, orthogonal: bool) -> Geometry:
    blocks = {box.element: box for box in geometry.boxes if box.kind == "block"}
    ports = {box.element: box for box in geometry.boxes if box.kind == "port"}
    owners = {port: block for block, block_ports in content.ports.items() for port in block_ports}
    moved: set[str] = set()

    def descendants(block: str) -> list[str]:
        result: list[str] = []
        for child in content.children(block):
            result += [child, *descendants(child)]
        return result

    def shift(element: str, dx: float, dy: float) -> None:
        for name in [element, *descendants(element)]:
            box = blocks[name]
            blocks[name] = replace(box, x=box.x + dx, y=box.y + dy)
            moved.add(name)
            for port in content.ports.get(name, []):
                if port in ports:
                    ports[port] = replace(ports[port], x=ports[port].x + dx, y=ports[port].y + dy)
                    moved.add(port)

    # 1. Move the hinted blocks; enclosing blocks first, so that their contents are positioned within their new place.
    for block in _tree_order(content):
        hint = hints.get(block)
        if hint is None or block not in blocks:
            continue
        parent = content.parents.get(block)
        origin_x, origin_y = (blocks[parent].x, blocks[parent].y) if parent in blocks else (0.0, 0.0)
        box = blocks[block]
        dx, dy = origin_x + hint.x - box.x, origin_y + hint.y - box.y
        if dx or dy:
            shift(block, dx, dy)

    # 2. Let enclosing blocks grow to contain their contents, from the innermost outwards.
    for block in reversed(_tree_order(content)):
        children = [blocks[c] for c in content.children(block) if c in blocks]
        if not children or block not in blocks:
            continue
        box = blocks[block]
        contents = children + [ports[p] for c in content.children(block) for p in content.ports.get(c, []) if p in ports]
        left = min(min(b.x for b in contents) - MARGIN, box.x)
        top = min(min(b.y for b in contents) - CONTAINER_LABEL_HEIGHT, box.y)
        right = max(max(b.x + b.width for b in contents) + MARGIN, box.x + box.width)
        bottom = max(max(b.y + b.height for b in contents) + MARGIN, box.y + box.height)
        grown = Box(box.element, box.kind, left, top, right - left, bottom - top, box.container)
        if grown != box:
            for port in content.ports.get(block, []):
                if port in ports:
                    ports[port] = _follow_edge(ports[port], box, grown)
                    moved.add(port)
            blocks[block] = grown

    # 3. Reroute the lines attached to anything that moved.
    boxes = {**blocks, **ports}
    lines = {line.element: line for line in content.lines}
    paths: list[Path] = []
    rerouted: set[str] = set()
    for path in geometry.paths:
        line = lines.get(path.element)
        if path.kind == "line" and line is not None and (line.start in moved or line.end in moved):
            if line.start in boxes and line.end in boxes:
                points = _route(boxes[line.start], boxes[line.end], boxes, owners, orthogonal)
                paths.append(Path(path.element, path.kind, points))
                rerouted.add(path.element)
                continue
        paths.append(path)

    # The labels of ports were placed by ELK: they move with their ports.
    original = {box.element: box for box in geometry.boxes if box.kind == "port"}
    labels = []
    for label in geometry.labels:
        if label.element in rerouted:
            continue
        if label.element in ports and label.element in original:
            dx = ports[label.element].x - original[label.element].x
            dy = ports[label.element].y - original[label.element].y
            label = replace(label, x=label.x + dx, y=label.y + dy)
        labels.append(label)
    result = Geometry(
        geometry.width,
        geometry.height,
        [blocks.get(b.element, b) if b.kind == "block" else ports.get(b.element, b) for b in geometry.boxes],
        paths,
        labels,
    )
    return fit(result)


def _tree_order(content: DiagramContent) -> list[str]:
    """The blocks, each after the block that encloses it."""
    result: list[str] = []

    def visit(block: str | None) -> None:
        for child in content.children(block):
            result.append(child)
            visit(child)

    visit(None)
    return result


def _follow_edge(port: Box, old: Box, new: Box) -> Box:
    """Move a port on the edge of a block that grew, so that it stays on that edge."""
    x, y = port.x, port.y
    if port.x + port.width / 2 >= old.x + old.width - 1:
        x += (new.x + new.width) - (old.x + old.width)
    elif port.x + port.width / 2 <= old.x + 1:
        x += new.x - old.x
    if port.y + port.height / 2 >= old.y + old.height - 1:
        y += (new.y + new.height) - (old.y + old.height)
    elif port.y + port.height / 2 <= old.y + 1:
        y += new.y - old.y
    return replace(port, x=x, y=y)


def _route(start: Box, end: Box, boxes: Mapping[str, Box], owners: Mapping[str, str], orthogonal: bool) -> tuple[Point, ...]:
    a = _attachment(start, _centre(end), boxes, owners)
    b = _attachment(end, _centre(start), boxes, owners)
    if not orthogonal:
        return (a, b)
    return _simplify(_orthogonal_route(a, _direction(start, a), b, _direction(end, b)))


def _orthogonal_route(a: Point, da: Point, b: Point, db: Point) -> tuple[Point, ...]:
    """An orthogonal line from `a` to `b`, which leaves `a` in direction `da`, and arrives at `b` from direction `db`
    (pointing away from `b`): with one bend if the ends point at each other on different axes, a Z if they do on the
    same axis, and otherwise first straight out of both ends."""
    horizontal = da[1] == 0, db[1] == 0
    a2, b2 = (a[0] + da[0] * STUB, a[1] + da[1] * STUB), (b[0] + db[0] * STUB, b[1] + db[1] * STUB)
    if horizontal[0] != horizontal[1]:
        corner = (b[0], a[1]) if horizontal[0] else (a[0], b[1])
        if _ahead(a, corner, da) and _ahead(b, corner, db):
            return (a, corner, b)
        return (a, a2, (a2[0], b2[1]) if horizontal[0] else (b2[0], a2[1]), b2, b)
    if horizontal[0]:
        middle = (a[0] + b[0]) / 2
        if _ahead(a, (middle, a[1]), da) and _ahead(b, (middle, b[1]), db):
            return (a, (middle, a[1]), (middle, b[1]), b)
        middle = (a2[1] + b2[1]) / 2
        return (a, a2, (a2[0], middle), (b2[0], middle), b2, b)
    middle = (a[1] + b[1]) / 2
    if _ahead(a, (a[0], middle), da) and _ahead(b, (b[0], middle), db):
        return (a, (a[0], middle), (b[0], middle), b)
    middle = (a2[0] + b2[0]) / 2
    return (a, a2, (middle, a2[1]), (middle, b2[1]), b2, b)


def _ahead(point: Point, other: Point, direction: Point) -> bool:
    """Whether `other` lies ahead of `point`, in `direction`."""
    return (other[0] - point[0]) * direction[0] + (other[1] - point[1]) * direction[1] > 0.5


def _direction(box: Box, point: Point) -> Point:
    """The direction in which a line leaves a block or port at `point`, on its outline: outwards."""
    if abs(point[0] - box.x) < 0.5:
        return (-1.0, 0.0)
    if abs(point[0] - (box.x + box.width)) < 0.5:
        return (1.0, 0.0)
    return (0.0, -1.0) if abs(point[1] - box.y) < 0.5 else (0.0, 1.0)


def _simplify(points: tuple[Point, ...]) -> tuple[Point, ...]:
    """The same line without repeated points, and without points in the middle of a straight segment."""
    result: list[Point] = []
    for point in points:
        if result and abs(point[0] - result[-1][0]) < 0.5 and abs(point[1] - result[-1][1]) < 0.5:
            continue
        if len(result) >= 2:
            (x0, y0), (x1, y1) = result[-2], result[-1]
            if (abs(x0 - x1) < 0.5 and abs(x1 - point[0]) < 0.5) or (abs(y0 - y1) < 0.5 and abs(y1 - point[1]) < 0.5):
                result[-1] = point
                continue
        result.append(point)
    return tuple(result)


def _centre(box: Box) -> Point:
    return box.x + box.width / 2, box.y + box.height / 2


def _attachment(box: Box, towards: Point, boxes: Mapping[str, Box], owners: Mapping[str, str]) -> Point:
    """Where a line attaches to a block or port: for a port, the middle of its outer side; for a block, the middle
    of the side that faces `towards`."""
    cx, cy = _centre(box)
    owner = boxes.get(owners.get(box.element, ""))
    if box.kind == "port" and owner is not None:
        return {
            "left": (box.x, cy), "right": (box.x + box.width, cy), "top": (cx, box.y), "bottom": (cx, box.y + box.height),
        }[port_side(box, owner)]  # fmt: skip
    dx, dy = towards[0] - cx, towards[1] - cy
    if abs(dx) * box.height >= abs(dy) * box.width:
        return (box.x + box.width if dx > 0 else box.x), cy
    return cx, (box.y + box.height if dy > 0 else box.y)


def port_side(port: Box, owner: Box) -> str:
    """The side of its block a port is on: the side nearest to its centre. Ports straddle that side, or lie outside
    it."""
    cx, cy = _centre(port)
    distances = {
        "left": abs(cx - owner.x), "right": abs(cx - (owner.x + owner.width)),
        "top": abs(cy - owner.y), "bottom": abs(cy - (owner.y + owner.height)),
    }  # fmt: skip
    return min(distances, key=lambda side: distances[side])


def fit(geometry: Geometry) -> Geometry:
    """Make the diagram as large as its contents, and move them into view if a hint placed them at negative
    coordinates."""
    xs = [b.x for b in geometry.boxes] + [x for p in geometry.paths for x, _ in p.points]
    ys = [b.y for b in geometry.boxes] + [y for p in geometry.paths for _, y in p.points]
    if not xs:
        return geometry
    dx = MARGIN - min(xs) if min(xs) < 0 else 0.0
    dy = MARGIN - min(ys) if min(ys) < 0 else 0.0
    if dx or dy:
        geometry = Geometry(
            geometry.width,
            geometry.height,
            [replace(b, x=b.x + dx, y=b.y + dy) for b in geometry.boxes],
            [Path(p.element, p.kind, tuple((x + dx, y + dy) for x, y in p.points)) for p in geometry.paths],
            [replace(label, x=label.x + dx, y=label.y + dy) for label in geometry.labels],
        )
    right = max([b.x + b.width for b in geometry.boxes] + [x for p in geometry.paths for x, _ in p.points])
    bottom = max([b.y + b.height for b in geometry.boxes] + [y for p in geometry.paths for _, y in p.points])
    geometry.width = max(geometry.width, right + MARGIN)
    geometry.height = max(geometry.height, bottom + MARGIN)
    return geometry
