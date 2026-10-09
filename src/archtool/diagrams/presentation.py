"""How elements are presented: their CSS classes, label texts, shapes and line endings.

See "Labels", "Styles" and "Shapes and line endings" in doc/file_formats.md.
"""

from collections.abc import Callable
from dataclasses import dataclass

from archtool.language.runtime import Runner
from archtool.metamodel import Shape, Stereotype

DEFAULT_SHAPE = "rectangle"
DEFAULT_PORT_SHAPE = "rectangle"
DEFAULT_START = "none"
DEFAULT_END = "arrow"


@dataclass(frozen=True, slots=True)
class Look:
    """The shape of a block, and the line endings of a line."""

    shape: str
    start: str
    end: str


@dataclass(frozen=True, slots=True)
class Label:
    text: str
    anchor: str | None


class Presentation:
    def __init__(self, runner: Runner, diagram_type: str) -> None:
        self.runner = runner
        self.metamodel = runner.model.metamodel
        self.diagram_type = diagram_type

    def owners(self, identifier: str) -> list[str]:
        """The type of an element, the types it extends, and its stereotypes, from the most specific."""
        type_name = self.runner.model.get(identifier).type
        owners = list(reversed(self.metamodel.ancestors(type_name)))
        return owners + [s.value for s in reversed(self.metamodel.types[type_name].stereotype.chain())]

    def classes(self, identifier: str) -> str:
        return " ".join(self.owners(identifier))

    def labels(self, identifier: str) -> list[Label]:
        texts = self.runner.label_texts(identifier, self.diagram_type)
        labels = [Label(text, anchor) for text, anchor in texts if text.strip()]
        if not labels and not texts:
            return [Label(identifier, None)]
        return labels

    def look(self, identifier: str) -> Look:
        """The shape and line endings of an element. Each is taken from the most specific type or stereotype that
        defines it; a row for this diagram type takes precedence over a row for all diagram types."""
        is_port = self.metamodel.types[self.runner.model.get(identifier).type].stereotype is Stereotype.PORT
        shape = self._property(identifier, lambda s: s.shape) or (DEFAULT_PORT_SHAPE if is_port else DEFAULT_SHAPE)
        start = self._property(identifier, lambda s: s.start) or DEFAULT_START
        end = self._property(identifier, lambda s: s.end) or DEFAULT_END
        return Look(shape, start, end)

    def _property(self, identifier: str, get: Callable[[Shape], str | None]) -> str | None:
        for owner in self.owners(identifier):
            for diagram_type in (self.diagram_type, None):
                for shape in self.metamodel.shapes:
                    if shape.type == owner and shape.diagram_type == diagram_type:
                        value = get(shape)
                        if value:
                            return value
        return None

