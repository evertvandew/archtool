"""Loading and saving a model repository: settings, meta model, model tables and diagrams.

See "Repository layout" in doc/file_formats.md.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from archtool.errors import FormatError
from archtool.formats.diagram_file import DiagramFile, format_diagram_file, read_diagram_file
from archtool.formats.tables import Table, format_model_table, read_model_table
from archtool.identifiers import split_identifier
from archtool.metamodel import MetaModel, load_metamodel
from archtool.model import Element, Model

SETTINGS_FILE = "archtool.toml"
MODEL_DIRECTORY = "model"
DIAGRAM_DIRECTORY = "diagrams"


@dataclass(frozen=True, slots=True)
class Settings:
    metamodel: Path = Path("metamodel.csv")
    elk: str = "elk"
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass(slots=True)
class Repository:
    root: Path
    settings: Settings
    metamodel: MetaModel
    model: Model
    # The diagram types that have an index table, even if it is empty.
    diagram_tables: set[str] = field(default_factory=set)


def load_settings(root: Path) -> Settings:
    path = root / SETTINGS_FILE
    if not path.exists():
        return Settings()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        # The message includes the line and column; TOMLDecodeError only has them as attributes from Python 3.14.
        raise FormatError(path, 1, 1, str(error)) from None
    model = data.get("model", {})
    render = data.get("render", {})
    server = data.get("server", {})
    return Settings(
        metamodel=Path(str(model.get("metamodel", "metamodel.csv"))),
        elk=str(render.get("elk", "elk")),
        host=str(server.get("host", "127.0.0.1")),
        port=int(server.get("port", 8080)),
    )


def load_repository(root: Path) -> Repository:
    """Load a model repository. Raises FormatError for the first error found."""
    settings = load_settings(root)
    metamodel = load_metamodel(root / settings.metamodel)
    repository = Repository(root, settings, metamodel, Model(metamodel))
    model_directory = root / MODEL_DIRECTORY
    if model_directory.is_dir():
        for path in sorted(model_directory.glob("*.csv")):
            _load_model_table(repository, path)
    diagram_directory = root / DIAGRAM_DIRECTORY
    if diagram_directory.is_dir():
        for path in sorted(diagram_directory.glob("*.csv")):
            _load_model_table(repository, path, diagrams=True)
        for path in sorted(diagram_directory.glob("*.diag")):
            _load_diagram_file(repository, path)
        for identifier in sorted(_diagram_identifiers(repository) - set(repository.model.diagrams)):
            raise FormatError(diagram_directory / f"{identifier}.diag", 1, 1, f"diagram {identifier} has no diagram file")
    return repository


def _load_model_table(repository: Repository, path: Path, *, diagrams: bool = False) -> None:
    metamodel = repository.metamodel
    type_name = path.stem
    type_def = metamodel.types.get(type_name)
    if type_def is None or type_def.stereotype.is_diagram() != diagrams:
        kind = "diagram type" if diagrams else "type"
        raise FormatError(path, 1, 1, f"the meta model defines no {kind} '{type_name}'")
    last_number, table = read_model_table(path.read_text(encoding="utf-8"), path)
    _check_columns(repository, table, type_name, path)
    model = repository.model
    model.record_table(type_name, last_number)
    if diagrams:
        repository.diagram_tables.add(type_name)
    for row in table.rows:
        values = dict(row.values)
        identifier = str(values.pop("id", ""))
        parts = split_identifier(identifier)
        if parts is None or parts[0] != type_name:
            raise FormatError(path, row.line, 1, f"identifier '{identifier}' does not belong to type '{type_name}'")
        if identifier in model:
            raise FormatError(path, row.line, 1, f"identifier '{identifier}' is used more than once")
        for column, target in model.references_from(Element(identifier, type_name, values)):
            if split_identifier(target) is None:
                raise FormatError(path, row.line, 1, f"column '{column}': '{target}' is not a valid identifier")
        model.add(Element(identifier, type_name, values))


def _check_columns(repository: Repository, table: Table, type_name: str, path: Path) -> None:
    expected = {column.name: column for column in repository.metamodel.columns(type_name)}
    present = {column.name for column in table.columns}
    for column in table.columns:
        if column.name not in expected:
            raise FormatError(path, table.line, 1, f"type '{type_name}' has no attribute '{column.name}'")
        if column != expected[column.name]:
            raise FormatError(path, table.line, 1, f"column '{column.name}' must be '{expected[column.name].header()}'")
    core = {column.name for column in repository.metamodel.core_columns(type_name)}
    for name in sorted(core - present):
        raise FormatError(path, table.line, 1, f"the table must have a column '{name}'")


def _load_diagram_file(repository: Repository, path: Path) -> None:
    diagram = read_diagram_file(path.read_text(encoding="utf-8"), path)
    if diagram.id != path.stem:
        raise FormatError(path, 1, 10, f"the identifier must be '{path.stem}', as in the file name")
    if diagram.id not in repository.model:
        raise FormatError(path, 1, 10, f"diagram '{diagram.id}' is not in the index table of its diagram type")
    if repository.model.get(diagram.id).type != diagram.type:
        raise FormatError(path, 1, 1, f"diagram '{diagram.id}' is of type '{repository.model.get(diagram.id).type}'")
    repository.model.diagrams[diagram.id] = diagram


def _diagram_identifiers(repository: Repository) -> set[str]:
    return {e.id for name in repository.diagram_tables for e in repository.model.elements_of(name, include_subtypes=False)}


def save_repository(repository: Repository, root: Path | None = None) -> None:
    """Write the model tables, diagram index tables and diagram files in canonical form.

    Files whose content is unchanged are not rewritten. Diagram files of diagrams that no longer exist are
    removed; tables are never removed, as they record the highest identifier number ever used.
    The meta model and settings are not written.
    """
    root = repository.root if root is None else root
    model = repository.model
    for type_name in model.table_types():
        is_diagram = model.metamodel.types[type_name].stereotype.is_diagram()
        directory = root / (DIAGRAM_DIRECTORY if is_diagram else MODEL_DIRECTORY)
        columns = model.metamodel.columns(type_name)
        rows = [{"id": e.id, **e.values} for e in model.elements_of(type_name, include_subtypes=False)]
        _write_if_changed(directory / f"{type_name}.csv", format_model_table(model.last_number(type_name), columns, rows))
    for diagram in model.diagrams.values():
        _write_if_changed(root / DIAGRAM_DIRECTORY / f"{diagram.id}.diag", format_diagram_file(diagram))
    diagram_directory = root / DIAGRAM_DIRECTORY
    if diagram_directory.is_dir():
        for path in diagram_directory.glob("*.diag"):
            if path.stem not in model.diagrams:
                path.unlink()


def add_diagram(repository: Repository, element: Element, diagram: DiagramFile) -> None:
    """Add a diagram: its element in the index table of its type, and its diagram file."""
    repository.model.add(element)
    repository.diagram_tables.add(element.type)
    repository.model.diagrams[element.id] = diagram


def _write_if_changed(path: Path, text: str) -> None:
    """Write a file atomically, unless it already has this content."""
    data = text.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
