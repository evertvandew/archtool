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

import io
import shutil
from pathlib import Path

import pytest

from archtool.checker import check_repository
from archtool.cli import run_edit, run_init
from archtool.errors import FormatError
from archtool.init import InitError, init_repository
from archtool.repository import load_repository, load_settings
from tests.conftest import SIMPLIFIED_ARCADIA

METAMODEL = SIMPLIFIED_ARCADIA / "metamodel.csv"


def test_init_creates_a_checked_repository(tmp_path: Path) -> None:
    root = tmp_path / "new"
    created = init_repository(root, METAMODEL)
    assert created[:4] == [Path("metamodel.csv"), Path("archtool.toml"), Path(".gitattributes"), Path(".gitignore")]
    assert (root / "metamodel.csv").read_bytes() == METAMODEL.read_bytes()
    assert load_settings(root).metamodel == Path("metamodel.csv")
    # A table for every type, and an index table for every diagram type, in the same form as in the example.
    tables = sorted(p.relative_to(root).as_posix() for p in root.glob("*/*.csv"))
    assert tables == sorted(p.as_posix() for p in created[4:])
    assert "model/requirement.csv" in tables and "diagrams/mission.csv" in tables and "model/function.csv" in tables
    header = (SIMPLIFIED_ARCADIA / "model" / "requirement.csv").read_text().splitlines()[1]
    assert (root / "model" / "requirement.csv").read_text() == f"@last_number 0\n{header}\n"
    assert (root / ".gitattributes").read_text() == "*.csv  text eol=lf\n*.diag text eol=lf\n"
    repository = load_repository(root)
    assert check_repository(repository) == []
    # The repository can be edited straight away.
    output = io.StringIO()
    status = run_edit(root, io.StringIO('add actor name="User"\nadd mission name="Mission" generate="mission"\n'), output, io.StringIO())
    assert status == 0 and '"created": ["actor_1"]' in output.getvalue() and (root / "diagrams" / "mission_1.diag").exists()


def test_init_with_a_linked_metamodel(tmp_path: Path) -> None:
    root = tmp_path / "models" / "coffee"
    created = init_repository(root, METAMODEL, link=True)
    assert Path("metamodel.csv") not in created and not (root / "metamodel.csv").exists()
    settings = load_settings(root)
    assert (root / settings.metamodel).resolve() == METAMODEL.resolve()
    assert check_repository(load_repository(root)) == []


def test_init_uses_a_metamodel_already_in_place(tmp_path: Path) -> None:
    shutil.copyfile(METAMODEL, tmp_path / "metamodel.csv")
    (tmp_path / ".gitignore").write_text("*.png\n")
    created = init_repository(tmp_path, tmp_path / "metamodel.csv")
    assert Path("metamodel.csv") not in created and Path(".gitignore") not in created
    assert (tmp_path / ".gitignore").read_text() == "*.png\n"  # Existing files are left alone.
    assert check_repository(load_repository(tmp_path)) == []


def test_init_refuses_an_existing_repository(tmp_path: Path) -> None:
    shutil.copytree(SIMPLIFIED_ARCADIA, tmp_path / "example")
    with pytest.raises(InitError, match="already contains archtool.toml, model, diagrams"):
        init_repository(tmp_path / "example", METAMODEL)
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "metamodel.csv").write_text("something else\n")
    with pytest.raises(InitError, match="already contains metamodel.csv"):
        init_repository(tmp_path / "other", METAMODEL)
    assert sorted(p.name for p in (tmp_path / "other").iterdir()) == ["metamodel.csv"]


def test_init_refuses_a_metamodel_with_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.csv"
    broken.write_text(METAMODEL.read_text().replace("show actor.targets(involves)", "show actor.targets(involvs)"))
    with pytest.raises(FormatError, match="argument of 'targets' must be a Relationship type"):
        init_repository(tmp_path / "new", broken)
    assert not (tmp_path / "new").exists()
    errors = io.StringIO()
    assert run_init(tmp_path / "missing.csv", tmp_path / "new", False, io.StringIO(), errors) == 1
    assert "missing.csv:1:1:" in errors.getvalue() and not (tmp_path / "new").exists()


def test_init_command_lists_the_files(tmp_path: Path) -> None:
    output = io.StringIO()
    assert run_init(METAMODEL, tmp_path / "new", False, output, io.StringIO()) == 0
    lines = output.getvalue().splitlines()
    assert lines[0] == f'{{"file": "{(tmp_path / "new" / "metamodel.csv").as_posix()}"}}'
    assert len(lines) == len(list((tmp_path / "new").rglob("*"))) - 2  # All files, but not the two directories.
