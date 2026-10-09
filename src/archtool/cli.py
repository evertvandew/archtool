"""The `archtool` command: one executable, with a subcommand per tool."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from archtool.checker import Finding, Severity, check_repository
from archtool.diagrams.render import RenderError, Renderer
from archtool.errors import FormatError
from archtool.identifiers import identifier_key
from archtool.language.runtime import RuleError, Runner, load_rules
from archtool.repository import load_repository


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archtool", description="Tools to build, check and render architecture models.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
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
    arguments = parser.parse_args(argv)
    if arguments.command == "render":
        output = arguments.output if arguments.output is not None else arguments.repository / "rendered"
        return run_render(arguments.repository, arguments.diagrams, output, sys.stdout, sys.stderr)
    if arguments.command == "check":
        return run_check(arguments.repository, sys.stdout)
    if arguments.command == "query":
        return run_query(arguments.repository, arguments.query, arguments.arguments, sys.stdout, sys.stderr)
    raise AssertionError(f"unknown command {arguments.command}")


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
