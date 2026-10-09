"""The `archtool` command: one executable, with a subcommand per tool."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from archtool.checker import Finding, Severity, check_repository
from archtool.errors import FormatError
from archtool.repository import load_repository


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archtool", description="Tools to build, check and render architecture models.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    check = commands.add_parser(
        "check",
        help="check a model against its meta model",
        description="Check a model against its meta model. Writes the findings as JSON lines, and exits with "
        "status 1 if any finding is an error.",
    )
    check.add_argument("repository", nargs="?", type=Path, default=Path("."), help="the model repository (default: .)")
    arguments = parser.parse_args(argv)
    if arguments.command == "check":
        return run_check(arguments.repository, sys.stdout)
    raise AssertionError(f"unknown command {arguments.command}")


def run_check(root: Path, output: TextIO) -> int:
    """Check the repository at `root`, and write the findings to `output`. Returns the exit status."""
    try:
        findings = check_repository(load_repository(root))
    except FormatError as error:
        findings = [Finding(Severity.ERROR, "syntax", error.message, None, _relative(error.path, root), error.line, error.column)]
    for finding in findings:
        output.write(json.dumps(finding.to_json(), ensure_ascii=False) + "\n")
    return 1 if any(finding.severity is Severity.ERROR for finding in findings) else 0


def _relative(path: str, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path

