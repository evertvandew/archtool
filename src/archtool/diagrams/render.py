"""Rendering the diagrams of a repository as SVG files."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from archtool.diagrams.content import diagram_content
from archtool.diagrams.elk import LayoutError, elk_command, elk_layout
from archtool.diagrams.presentation import Presentation
from archtool.diagrams.sequence import sequence_layout
from archtool.diagrams.svg import render_svg
from archtool.formats.diagram_file import DiagramFile, Generate, Layout, Style
from archtool.identifiers import identifier_key
from archtool.language.runtime import RuleError, Runner, load_rules
from archtool.metamodel import Stereotype
from archtool.repository import Repository


class RenderError(Exception):
    """A diagram could not be rendered."""


@dataclass(frozen=True, slots=True)
class Rendered:
    diagram: str
    path: Path


class Renderer:
    def __init__(self, repository: Repository, command: list[str] | None = None) -> None:
        self.repository = repository
        self.rules = load_rules(repository.metamodel)
        if self.rules.errors:
            error = self.rules.errors[0]
            raise RenderError(f"{error.path}:{error.line}:{error.column}: {error.message}")
        self.command = command if command is not None else elk_command(repository.settings.elk)
        metamodel = repository.metamodel
        self.defs = "".join(section.text for section in metamodel.defs)
        self.styles = "".join(section.text for section in metamodel.styles)

    def render(self, identifier: str) -> str:
        """The SVG of a diagram."""
        if identifier not in self.repository.model.diagrams:
            raise RenderError(f"there is no diagram '{identifier}'")
        return self.render_file(self.repository.model.diagrams[identifier])

    def preview(self, diagram_type: str, rule: str, arguments: tuple[tuple[str, str], ...]) -> str:
        """The SVG of a generated diagram that is not stored in the model."""
        type_def = self.repository.metamodel.types.get(diagram_type)
        if type_def is None or not type_def.stereotype.is_diagram():
            raise RenderError(f"there is no diagram type '{diagram_type}'")
        rules = self.repository.metamodel.property(diagram_type, "rules")
        if not isinstance(rules, tuple) or rule not in rules:
            raise RenderError(f"'{rule}' is not a generation rule of {diagram_type}")
        return self.render_file(DiagramFile(f"{diagram_type}_preview", diagram_type, [Generate(rule, arguments)]))

    def render_file(self, diagram: DiagramFile) -> str:
        """The SVG of a diagram file."""
        identifier = diagram.id
        model = self.repository.model
        runner = Runner(self.rules, model)  # Created for every rendering, as the model may have changed.
        try:
            content = diagram_content(runner, diagram)
        except RuleError as error:
            raise RenderError(f"{identifier}: {error}") from None
        presentation = Presentation(runner, diagram.type)
        if content.stereotype is Stereotype.SEQUENCE_DIAGRAM:
            geometry = sequence_layout(content, presentation, model, runner.evaluator)
        else:
            hints = {s.element: s for s in diagram.statements if isinstance(s, Layout)}
            try:
                geometry = elk_layout(content, presentation, hints, self.command)
            except LayoutError as error:
                raise RenderError(f"{identifier}: {error}") from None
        element_styles = {s.element: s.css for s in diagram.statements if isinstance(s, Style)}
        return render_svg(content, geometry, presentation, element_styles, self.defs, self.styles)

    def render_to(self, directory: Path, identifiers: Iterable[str] | None = None) -> list[Rendered]:
        """Render diagrams (by default all of them) to `<directory>/<id>.svg`."""
        selected = sorted(identifiers if identifiers is not None else self.repository.model.diagrams, key=identifier_key)
        directory.mkdir(parents=True, exist_ok=True)
        results: list[Rendered] = []
        for identifier in selected:
            path = directory / f"{identifier}.svg"
            path.write_text(self.render(identifier), encoding="utf-8")
            results.append(Rendered(identifier, path))
        return results
