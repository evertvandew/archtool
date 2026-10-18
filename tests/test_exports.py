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

"""Exports: files made from an element by a command declared in archtool.toml."""

import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient

from archtool.errors import FormatError
from archtool.exports import ExportError, run_export
from archtool.repository import Export, load_repository, load_settings
from archtool.server.app import Session, create_app
from tests.conftest import EXAMPLES, SIMPLIFIED_ARCADIA

type Client = TestClient
type ClientFactory = Callable[..., Awaitable[Client]]


@pytest.fixture
def metamodelling(tmp_path: Path) -> Path:
    copy = tmp_path / "metamodelling"
    shutil.copytree(EXAMPLES / "metamodelling", copy, ignore=shutil.ignore_patterns("__pycache__"))
    return copy


def settings_with(root: Path, exports: str) -> Path:
    shutil.copytree(SIMPLIFIED_ARCADIA, root)
    (root / "archtool.toml").write_text(exports + '[model]\nmetamodel = "metamodel.csv"\n')
    return root


def test_settings(metamodelling: Path) -> None:
    assert load_settings(metamodelling).exports == (
        Export("Meta-model file", "metamodel",
               ("{python}", "generate_metamodel.py", "{repository}", "--metamodel", "{element}"), "{label}.csv"),
    )  # fmt: skip


@pytest.mark.parametrize(
    ("exports", "message"),
    [
        ('exports = "x"\n', "'exports' must be a list of tables, written as \\[\\[exports\\]\\]"),
        ('[[exports]]\ntype = "test"\ncommand = ["cat"]\n', "export 1: needs a name"),
        ('[[exports]]\nname = "X"\ncommand = ["cat"]\n', "export 1: needs the type of the elements it exports"),
        ('[[exports]]\nname = "X"\ntype = "test"\ncommand = "cat"\n', "export 1: needs a command, as a list of strings"),
        ('[[exports]]\nname = "X"\ntype = "test"\ncommand = ["cat"]\nformat = "csv"\n', "export 1: unknown key 'format'"),
        ('[[exports]]\nname = "X"\ntype = "printer"\ncommand = ["cat"]\n', "export 1 (X): the meta model has no type or stereotype 'printer'"),
    ],
)
def test_invalid_settings(tmp_path: Path, exports: str, message: str) -> None:
    root = settings_with(tmp_path / "example", exports)
    with pytest.raises(FormatError, match=message.replace("(", r"\(").replace(")", r"\)")):
        load_repository(root)


def test_run_export(tmp_path: Path) -> None:
    script = "import sys; print(sys.argv[1:]); print('{braces} stay')"
    root = settings_with(tmp_path / "example", (
        '[[exports]]\nname = "Test report"\ntype = "test"\nfile = "{label}: report?.txt"\n'
        f'command = ["{{python}}", "-c", "{script}", "{{element}}", "{{label}}"]\n'
        '[[exports]]\nname = "Broken"\ntype = "Entity"\ncommand = ["{python}", "-c", "import sys; sys.exit(\'no luck\')"]\n'
    ))  # fmt: skip
    repository = load_repository(root)
    exported = run_export(repository, 0, "test_1", "Brew a cup")
    assert exported.file == "Brew a cup_ report_.txt"
    assert exported.content.decode() == "['test_1', 'Brew a cup']\n{braces} stay\n"
    with pytest.raises(ExportError, match="Broken failed: no luck") as failed:
        run_export(repository, 1, "test_1", "Brew a cup")
    assert failed.value.status == 500
    with pytest.raises(ExportError, match="Test report is made from a test, but actor_1 is a actor") as wrong:
        run_export(repository, 0, "actor_1", "User")
    assert wrong.value.status == 400
    for number, identifier in ((2, "test_1"), (0, "test_9")):
        with pytest.raises(ExportError) as missing:
            run_export(repository, number, identifier, "")
        assert missing.value.status == 404


async def test_export_meta_model_file(aiohttp_client: ClientFactory, metamodelling: Path) -> None:
    client = await aiohttp_client(create_app(Session(load_repository(metamodelling))))
    model = await (await client.get("/api/model")).json()
    assert model["exports"] == [{"name": "Meta-model file", "type": "metamodel"}]
    response = await client.get("/api/exports/0/metamodel_2")
    assert response.status == 200, await response.text()
    assert response.headers["Content-Disposition"] == 'attachment; filename="State machines.csv"'
    assert (await response.text()).startswith("# State machines\n")
    response = await client.get("/api/exports/0/entity_type_1")
    assert response.status == 400 and "is made from a metamodel" in (await response.json())["error"]
    assert (await client.get("/api/exports/3/metamodel_2")).status == 404


async def test_failed_export(aiohttp_client: ClientFactory, metamodelling: Path) -> None:
    """A link across meta models: the script refuses to generate the file, and says why."""
    starts_at = metamodelling / "model" / "starts_at.csv"
    starts_at.write_text(starts_at.read_text().replace("starts_at_3;relationship_type_3;entity_type_3", "starts_at_3;relationship_type_3;entity_type_2"))
    client = await aiohttp_client(create_app(Session(load_repository(metamodelling))))
    response = await client.get("/api/exports/0/metamodel_2")
    assert response.status == 500
    assert "relationship_type_3 refers to entity_type_2 (starts_at)" in (await response.json())["error"]
