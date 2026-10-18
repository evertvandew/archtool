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

"""The `archtool` command: one executable, with a subcommand per tool."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from archtool.checker import Finding, Severity, check_repository
from archtool.diagrams.render import RenderError, Renderer
from archtool.editing.editor import Editor
from archtool.errors import FormatError
from archtool.identifiers import identifier_key
from archtool.init import InitError, init_repository
from archtool.language.runtime import RuleError, Runner, load_rules
from archtool.repository import load_repository
from archtool.server.app import serve


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archtool", description="Tools to build, check and render architecture models.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    init = commands.add_parser(
        "init",
        help="create a model repository for a meta model",
        description="Create a model repository for a meta model: the settings, a copy of the meta model, an empty "
        "table for every type and diagram type, and .gitattributes and .gitignore files if there are none. Writes a "
        "JSON line for every file created. Nothing is created if the meta model has errors, or if the directory "
        "already contains a repository.",
    )
    init.add_argument("metamodel", type=Path, help="the meta-model file")
    init.add_argument("repository", nargs="?", type=Path, default=Path("."),
                      help="the directory of the new repository, created if needed (default: .)")  # fmt: skip
    init.add_argument("--link", action="store_true",
                      help="refer to the meta model where it is, instead of copying it into the repository")  # fmt: skip
    check = commands.add_parser(
        "check",
        help="check a model against its meta model",
        description="Check a model against its meta model, and evaluate its verification rules. Writes the findings "
        "as JSON lines, and exits with status 1 if any finding is an error.",
    )
    check.add_argument("repository", nargs="?", type=Path, default=Path("."), help="the model repository (default: .)")
    query = commands.add_parser(
        "query",
        help="run a query, or evaluate an expression",
        description="Run a query of the meta model, or evaluate an expression in the selection language. Writes the "
        "results as JSON lines.",
    )
    query.add_argument("query", help="the name of a query, or an expression")
    query.add_argument("arguments", nargs="*", metavar="name=value", help="arguments of the query")
    query.add_argument("-r", "--repository", type=Path, default=Path("."), help="the model repository (default: .)")
    render = commands.add_parser(
        "render",
        help="render diagrams as SVG",
        description="Render the diagrams of a model as SVG files. Writes a JSON line for every file written, and exits "
        "with status 1 if any diagram could not be rendered.",
    )
    render.add_argument("diagrams", nargs="*", metavar="diagram", help="the diagrams to render (default: all)")
    render.add_argument("-r", "--repository", type=Path, default=Path("."), help="the model repository (default: .)")
    render.add_argument("-o", "--output", type=Path, default=None,
                        help="the directory for the SVG files (default: rendered/ in the repository)")  # fmt: skip
    edit = commands.add_parser(
        "edit",
        help="change a model with commands",
        description="Execute commands, one per line, from a file or stdin, and write the changes to the model's "
        "files. Writes a JSON line with the result of every command, and exits with status 1 if any command failed.",
    )
    edit.add_argument("file", nargs="?", default="-", help="the file with commands (default: stdin)")
    edit.add_argument("-r", "--repository", type=Path, default=Path("."), help="the model repository (default: .)")
    serve = commands.add_parser(
        "serve",
        help="share a model with web clients",
        description="Start the collaboration server for a model, with its web client. The host and port default to "
        "the settings in archtool.toml.",
    )
    serve.add_argument("repository", nargs="?", type=Path, default=Path("."), help="the model repository (default: .)")
    serve.add_argument("--host", help="the address to listen on")
    serve.add_argument("--port", type=int, help="the port to listen on")
    arguments = parser.parse_args(argv)
    if arguments.command == "init":
        return run_init(arguments.metamodel, arguments.repository, arguments.link, sys.stdout, sys.stderr)
    if arguments.command == "serve":
        return run_serve(arguments.repository, arguments.host, arguments.port, sys.stderr)
    if arguments.command == "edit":
        if arguments.file == "-":
            return run_edit(arguments.repository, sys.stdin, sys.stdout, sys.stderr)
        with open(arguments.file, encoding="utf-8") as commands_file:
            return run_edit(arguments.repository, commands_file, sys.stdout, sys.stderr)
    if arguments.command == "render":
        output = arguments.output if arguments.output is not None else arguments.repository / "rendered"
        return run_render(arguments.repository, arguments.diagrams, output, sys.stdout, sys.stderr)
    if arguments.command == "check":
        return run_check(arguments.repository, sys.stdout)
    if arguments.command == "query":
        return run_query(arguments.repository, arguments.query, arguments.arguments, sys.stdout, sys.stderr)
    raise AssertionError(f"unknown command {arguments.command}")


def run_init(metamodel: Path, root: Path, link: bool, output: TextIO, errors: TextIO) -> int:
    """Create a model repository, and write the files created to `output`. Returns the exit status."""
    try:
        created = init_repository(root, metamodel, link=link)
    except FormatError as error:
        errors.write(f"{error.path}:{error.line}:{error.column}: {error.message}\n")
        return 1
    except InitError as error:
        errors.write(f"{error}\n")
        return 1
    for path in created:
        output.write(json.dumps({"file": (root / path).as_posix()}) + "\n")
    return 0


def run_check(root: Path, output: TextIO) -> int:
    """Check the repository at `root`, and write the findings to `output`. Returns the exit status."""
    try:
        findings = check_repository(load_repository(root))
    except FormatError as error:
        findings = [Finding(Severity.ERROR, "syntax", error.message, None, error.path, error.line, error.column)]
    for finding in findings:
        record = finding.to_json()
        if "path" in record:
            record["path"] = _relative(str(record["path"]), root)
        output.write(json.dumps(record, ensure_ascii=False) + "\n")
    return 1 if any(finding.severity is Severity.ERROR for finding in findings) else 0


def run_query(root: Path, text: str, arguments: Sequence[str], output: TextIO, errors: TextIO) -> int:
    """Run a query or evaluate an expression, and write the results to `output`. Returns the exit status."""
    try:
        repository = load_repository(root)
        rules = load_rules(repository.metamodel)
        runner = Runner(rules, repository.model)
        if text in rules.program.queries:
            pairs = tuple(_argument(argument) for argument in arguments)
            result = runner.query(text, pairs)
        else:
            if arguments:
                raise RuleError("arguments can only be given to queries")
            result = runner.expression(text)
    except FormatError as error:
        errors.write(f"{_relative(error.path, root)}:{error.line}:{error.column}: {error.message}\n")
        return 1
    except RuleError as error:
        errors.write(f"{error}\n")
        return 1
    for record in result.records():
        output.write(json.dumps(record, ensure_ascii=False) + "\n")
    return 0


def run_render(root: Path, diagrams: Sequence[str], output_directory: Path, output: TextIO, errors: TextIO) -> int:
    """Render diagrams to SVG files. Returns the exit status."""
    try:
        renderer = Renderer(load_repository(root))
    except FormatError as error:
        errors.write(f"{_relative(error.path, root)}:{error.line}:{error.column}: {error.message}\n")
        return 1
    except RenderError as error:
        errors.write(f"{error}\n")
        return 1
    status = 0
    for identifier in diagrams or sorted(renderer.repository.model.diagrams, key=identifier_key):
        try:
            rendered = renderer.render_to(output_directory, [identifier])
        except RenderError as error:
            errors.write(f"{error}\n")
            status = 1
            continue
        for result in rendered:
            output.write(json.dumps({"diagram": result.diagram, "file": str(result.path)}) + "\n")
    return status


def run_edit(root: Path, commands: TextIO, output: TextIO, errors: TextIO) -> int:
    """Execute commands, and write their results to `output` as they are executed. Returns the exit status."""
    try:
        editor = Editor(load_repository(root))
    except FormatError as error:
        errors.write(f"{_relative(error.path, root)}:{error.line}:{error.column}: {error.message}\n")
        return 1
    status = 0
    for number, line in enumerate(commands, 1):
        result = editor.run(line.rstrip("\n"), number)
        if result is None:
            continue
        if not result.ok:
            status = 1
        record = result.to_json()
        for key in ("issues", "resolved"):
            findings = record.get(key, [])
            assert isinstance(findings, list)
            for finding in findings:
                if "path" in finding:
                    finding["path"] = _relative(str(finding["path"]), root)
        output.write(json.dumps(record, ensure_ascii=False) + "\n")
        output.flush()
    return status


def run_serve(root: Path, host: str | None, port: int | None, errors: TextIO) -> int:
    try:
        repository = load_repository(root)
    except FormatError as error:
        errors.write(f"{_relative(error.path, root)}:{error.line}:{error.column}: {error.message}\n")
        return 1
    host = host or repository.settings.host
    port = port or repository.settings.port
    errors.write(f"Serving {root} on http://{host}:{port}/\n")
    serve(repository, host, port)
    return 0


def _argument(text: str) -> tuple[str, str]:
    name, equals, value = text.partition("=")
    if not equals:
        raise RuleError(f"argument '{text}' must be written as name=value")
    return name, value


def _relative(path: str, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path
