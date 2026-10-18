"""Exports: files made from an element by a command that the repository declares in archtool.toml.

    [[exports]]
    name = "Meta-model file"
    type = "metamodel"
    command = ["{python}", "generate_metamodel.py", "{repository}", "--metamodel", "{element}"]
    file = "{label}.csv"

The command runs in the repository's directory, and writes the file to stdout; it fails with a non-zero exit status,
with the reason on stderr. In the command and the file name, `{element}` is the element's identifier, `{label}` its
default label, `{repository}` the repository's directory, and `{python}` the Python that runs the tools, so that a
Python script can use the archtool library. See "archtool.toml" in doc/file_formats.md.
"""

import re
import subprocess
import sys
from dataclasses import dataclass

from archtool.repository import Repository

TIMEOUT = 120  # Seconds.


class ExportError(Exception):
    """An export cannot be made. `status` is the matching HTTP status: 404 if the export or element does not exist,
    400 if the export does not apply to the element, and 500 if its command failed."""

    def __init__(self, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class Exported:
    file: str
    content: bytes


def run_export(repository: Repository, number: int, identifier: str, label: str) -> Exported:
    """Make export `number` (counted from 0) of an element. Raises ExportError."""
    if not 0 <= number < len(repository.settings.exports):
        raise ExportError(f"there is no export {number}", 404)
    export = repository.settings.exports[number]
    if identifier not in repository.model:
        raise ExportError(f"{identifier} is not an element of the model", 404)
    element = repository.model.get(identifier)
    if not repository.metamodel.is_a(element.type, export.type):
        raise ExportError(f"{export.name} is made from a {export.type}, but {identifier} is a {element.type}", 400)
    values = {"python": sys.executable, "repository": str(repository.root.resolve()), "element": identifier, "label": label}
    command = [_substitute(part, values) for part in export.command]
    try:
        process = subprocess.run(command, cwd=repository.root, capture_output=True, timeout=TIMEOUT, check=False)
    except FileNotFoundError:
        raise ExportError(f"{export.name}: cannot run '{command[0]}'") from None
    except subprocess.TimeoutExpired:
        raise ExportError(f"{export.name}: the command did not finish within {TIMEOUT} seconds") from None
    if process.returncode != 0:
        reason = (process.stderr or process.stdout).decode("utf-8", "replace").strip()
        raise ExportError(f"{export.name} failed: {reason or f'exit status {process.returncode}'}")
    return Exported(_file_name(_substitute(export.file, values)), process.stdout)


def _substitute(text: str, values: dict[str, str]) -> str:
    """Replace the placeholders in a part of a command; other braces, e.g. in a script, are left alone."""
    for key, value in values.items():
        text = text.replace(f"{{{key}}}", value)
    return text


def _file_name(text: str) -> str:
    """A file name that is safe on every system."""
    name = re.sub(r"[^A-Za-z0-9 ._-]+", "_", text).strip(" .")
    return name or "export"
