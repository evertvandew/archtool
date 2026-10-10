"""Creating a model repository for a meta model (`archtool init`).

The new repository has a settings file that names the meta model, a copy of the meta model (or a reference to it),
an empty table for every type and diagram type, and the git settings that the file formats need. See "Repository
layout" in doc/file_formats.md.
"""

import json
import os
import shutil
from pathlib import Path

from archtool.errors import FormatError
from archtool.language.runtime import load_rules
from archtool.metamodel import MetaModel, load_metamodel
from archtool.model import Model
from archtool.repository import DIAGRAM_DIRECTORY, MODEL_DIRECTORY, SETTINGS_FILE, Repository, Settings, save_repository

METAMODEL_FILE = "metamodel.csv"

# Git must never convert the line endings of model files.
GITATTRIBUTES = "*.csv  text eol=lf\n*.diag text eol=lf\n"
# Rendered diagrams can be made again at any time.
GITIGNORE = "rendered/\n"


class InitError(Exception):
    """A repository cannot be created, e.g. because one already exists."""


def check_metamodel(path: Path) -> tuple[MetaModel | None, list[FormatError]]:
    """Read a meta model and its rules. Returns the meta model, and the errors found in it."""
    try:
        metamodel = load_metamodel(path)
    except FormatError as error:
        return None, [error]
    except OSError as error:
        return None, [FormatError(path, 1, 1, error.strerror or str(error))]
    return metamodel, list(load_rules(metamodel).program.errors)


def init_repository(root: Path, metamodel_path: Path, *, link: bool = False) -> list[Path]:
    """Create a model repository in `root` for the meta model at `metamodel_path`, and return the files created,
    relative to `root`.

    The meta model is copied to `root/metamodel.csv`, unless `link` is set: the settings then refer to it where it
    is. `.gitattributes` and `.gitignore` are only created if they do not exist yet. Raises InitError if `root`
    already holds (part of) a repository, and FormatError for the first error in the meta model; nothing is created
    then.
    """
    metamodel, errors = check_metamodel(metamodel_path)
    if errors:
        raise errors[0]
    assert metamodel is not None
    copy = root / METAMODEL_FILE
    # A meta model that is already in place, as metamodel.csv, is used as it is.
    in_place = copy.exists() and copy.resolve() == metamodel_path.resolve()
    if root.exists() and not root.is_dir():
        raise InitError(f"{root} is not a directory")
    existing = [root / name for name in (SETTINGS_FILE, MODEL_DIRECTORY, DIAGRAM_DIRECTORY) if (root / name).exists()]
    if not link and not in_place and copy.exists():
        existing.append(copy)
    if existing:
        names = ", ".join(path.name for path in existing)
        raise InitError(f"{root} already contains {names}; a repository can only be created where there is none")

    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    if link:
        reference = Path(os.path.relpath(metamodel_path.resolve(), root.resolve())).as_posix()
    else:
        reference = METAMODEL_FILE
        if not in_place:
            shutil.copyfile(metamodel_path, copy)
            created.append(Path(METAMODEL_FILE))
    (root / SETTINGS_FILE).write_text(_settings(reference), encoding="utf-8")
    created.append(Path(SETTINGS_FILE))
    for name, text in ((".gitattributes", GITATTRIBUTES), (".gitignore", GITIGNORE)):
        if not (root / name).exists():
            (root / name).write_text(text, encoding="utf-8")
            created.append(Path(name))

    # An empty table for every type, which records that no identifiers have been used yet.
    repository = Repository(root, Settings(metamodel=Path(reference)), metamodel, Model(metamodel))
    for name, type_def in metamodel.types.items():
        repository.model.record_table(name, 0)
        directory = DIAGRAM_DIRECTORY if type_def.stereotype.is_diagram() else MODEL_DIRECTORY
        if type_def.stereotype.is_diagram():
            repository.diagram_tables.add(name)
        created.append(Path(directory) / f"{name}.csv")
    (root / MODEL_DIRECTORY).mkdir()
    (root / DIAGRAM_DIRECTORY).mkdir()
    save_repository(repository)
    return created


def _settings(metamodel: str) -> str:
    defaults = Settings()
    return f"""# The settings of this model repository. The settings in comments show their default values.

[model]
metamodel = {json.dumps(metamodel)}

# [render]
# elk = {json.dumps(defaults.elk)}

# [server]
# host = {json.dumps(defaults.host)}
# port = {defaults.port}
"""
