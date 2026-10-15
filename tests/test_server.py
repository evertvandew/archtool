import json
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient

from archtool.diagrams.render import Renderer
from archtool.formats.diagram_file import DiagramFile, Generate
from archtool.repository import Repository, load_repository
from archtool.server.app import Session, create_app
from tests.conftest import SIMPLIFIED_ARCADIA

type Client = TestClient
type ClientFactory = Callable[..., Awaitable[Client]]


class FakeRenderer(Renderer):
    """Renders a diagram as a tiny SVG, so that the tests do not need elk-cli."""

    def __init__(self, repository: Repository) -> None:
        super().__init__(repository, ["true"])
        self.calls = 0

    def render_file(self, diagram: DiagramFile) -> str:
        self.calls += 1
        generate = next((s for s in diagram.statements if isinstance(s, Generate)), None)
        arguments = "".join(f" data-{name}={value!r}" for name, value in generate.arguments) if generate else ""
        return f'<svg xmlns="http://www.w3.org/2000/svg" data-diagram="{diagram.id}"{arguments}/>'


@pytest.fixture
def example(tmp_path: Path) -> Path:
    copy = tmp_path / "example"
    shutil.copytree(SIMPLIFIED_ARCADIA, copy)
    return copy


@pytest.fixture
def session(example: Path) -> Session:
    repository = load_repository(example)
    return Session(repository, FakeRenderer(repository))


@pytest.fixture
async def client(aiohttp_client: ClientFactory, session: Session) -> Client:
    return await aiohttp_client(create_app(session))


async def test_client_files(client: Client) -> None:
    response = await client.get("/")
    assert response.status == 200 and "<title>Architecting tool</title>" in await response.text()
    response = await client.get("/static/app.js")
    assert response.status == 200 and response.content_type == "text/javascript"
    assert (await client.get("/static/style.css")).content_type == "text/css"
    assert (await client.get("/static/missing.js")).status == 404
    assert (await client.get("/static/..%2Fapp.py")).status == 404


async def test_model_snapshot(client: Client) -> None:
    model = await (await client.get("/api/model")).json()
    assert model["version"] == 0
    assert model["elements"]["component_2"] == {
        "type": "component", "label": "Controller", "values": {"name": "Controller"}, "parent": "component_1",
    }  # fmt: skip
    assert model["elements"]["function_port_1"]["values"] == {
        "owner": "logical_function_1", "name": "Start command", "direction": "output",
    }  # fmt: skip
    assert model["elements"]["functional_chain_1"]["values"]["relationships"] == ["functional_exchange_2", "functional_exchange_3"]
    requirement = model["types"]["requirement"]
    assert requirement["stereotype"] == "Entity"
    priority = next(c for c in requirement["columns"] if c["name"] == "priority")
    assert priority == {"list": False, "kind": "enum", "values": ["high", "medium", "low"], "name": "priority",
                        "core": False, "required": True}  # fmt: skip
    assert model["types"]["component_port"]["properties"]["owner"] == ["component", "actor"]
    assert model["types"]["system_function"]["ancestors"] == ["function", "system_function"]
    diagram = next(d for d in model["diagrams"] if d["id"] == "logical_dataflow_2")
    shown = ["functional_exchange_2", "functional_exchange_3", "logical_function_2", "logical_function_3", "logical_function_4"]
    assert diagram == {
        "id": "logical_dataflow_2", "type": "logical_dataflow", "label": "Heating and brewing", "kind": "BlockDiagram",
        "generated": False, "generate": None, "shown": shown,
        # The elements in the diagram include the ports that its lines use.
        "elements": ["function_port_3", "function_port_4", "function_port_5", "function_port_6", *shown],
    }  # fmt: skip
    # For a generated diagram, the elements follow from its generation rule.
    mission = next(d for d in model["diagrams"] if d["id"] == "mission_1")
    assert mission["generate"] == {"rule": "mission", "arguments": {}}
    physical = next(d for d in model["diagrams"] if d["id"] == "physical_architecture_1")
    assert physical["generate"] == {"rule": "component_internals", "arguments": {"root": "component_1", "depth": "1"}}
    assert mission["elements"] == ["actor_1", "involves_1", "system_function_2"]
    # An element appears in a generated diagram if it passes the diagram's generation rule.
    allocation = next(d for d in model["diagrams"] if d["id"] == "allocation_1")
    assert "component_1" in allocation["elements"] and "logical_function_1" in allocation["elements"]
    function_breakdown = next(d for d in model["diagrams"] if d["id"] == "function_breakdown_1")
    assert "system_function_2" in function_breakdown["elements"]
    assert "logical_function_1" not in function_breakdown["elements"]
    sequence = next(d for d in model["diagrams"] if d["id"] == "functional_sequence_1")
    assert "functional_exchange_1" in sequence["elements"] and "logical_function_1" in sequence["elements"]
    assert model["findings"] == []


async def test_commands_over_http(client: Client, example: Path) -> None:
    response = await client.post("/api/commands", json={"command": 'add actor name="Barista"'})
    result = await response.json()
    assert result["ok"] and result["created"] == ["actor_2"]
    assert "actor_2;Barista" in (example / "model" / "actor.csv").read_text()
    model = await (await client.get("/api/model")).json()
    assert model["version"] == 1 and model["elements"]["actor_2"]["label"] == "Barista"
    result = await (await client.post("/api/commands", json={"command": "set actor_2 age=3"})).json()
    assert not result["ok"] and "no attribute 'age'" in result["error"]
    assert (await (await client.get("/api/model")).json())["version"] == 1
    assert (await client.post("/api/commands", data="nonsense")).status == 400


async def test_websocket_broadcasts_changes(client: Client) -> None:
    first = await client.ws_connect("/api/socket")
    second = await client.ws_connect("/api/socket")
    assert json.loads((await first.receive()).data) == {"type": "hello", "version": 0}
    assert json.loads((await second.receive()).data) == {"type": "hello", "version": 0}
    await first.send_str(json.dumps({"request": 7, "command": "delete test_2"}))
    # Every client is told that the model changed; the sender also receives the result.
    messages = [json.loads((await first.receive()).data) for _ in range(2)]
    assert {"type": "changed", "version": 1} in messages
    result = next(m for m in messages if m["type"] == "result")
    assert result["request"] == 7 and result["deleted"] == ["covers_2", "test_2"]
    assert [issue["check"] for issue in result["issues"]] == ["requirement_covered"]
    assert json.loads((await second.receive()).data) == {"type": "changed", "version": 1}
    # A failed command changes nothing, so nobody is told about it.
    await second.send_str(json.dumps({"request": 1, "command": "delete test_2"}))
    failed = json.loads((await second.receive()).data)
    assert failed["type"] == "result" and not failed["ok"]
    await second.send_str("not json")
    assert json.loads((await second.receive()).data)["type"] == "error"
    await first.close()
    await second.close()


async def test_identifiers(client: Client, example: Path) -> None:
    response = await client.post("/api/identifiers", json={"type": "test"})
    assert await response.json() == {"id": "test_4"}
    assert (await (await client.post("/api/identifiers", json={"type": "test"})).json()) == {"id": "test_5"}
    assert (example / "model" / "test.csv").read_text().startswith("@last_number 5\n")
    response = await client.post("/api/identifiers", json={"type": "printer"})
    assert response.status == 400


async def test_diagrams_are_cached_per_version(client: Client, session: Session) -> None:
    response = await client.get("/api/diagrams/mission_1.svg")
    assert response.status == 200 and 'data-diagram="mission_1"' in await response.text()
    await client.get("/api/diagrams/mission_1.svg")
    renderer = session.renderer
    assert isinstance(renderer, FakeRenderer) and renderer.calls == 1
    await client.post("/api/commands", json={"command": "add actor name=Barista"})
    await client.get("/api/diagrams/mission_1.svg")
    assert renderer.calls == 2
    response = await client.get("/api/diagrams/mission_7.svg")
    assert response.status == 404 and "no diagram" in (await response.json())["error"]


async def test_generation_rules_in_snapshot(client: Client) -> None:
    rules = (await (await client.get("/api/model")).json())["rules"]
    assert rules["requirement_breakdown"] == {
        "parameters": [{"name": "root", "type": "requirement", "default": None},
                       {"name": "depth", "type": "int", "default": 3}],
    }  # fmt: skip
    assert rules["mission"] == {"parameters": []}


async def test_preview(client: Client, session: Session) -> None:
    url = "/api/preview.svg?type=requirement_breakdown&rule=requirement_breakdown&root=requirement_1&version=0"
    response = await client.get(url)
    assert response.status == 200
    assert await response.text() == (
        '<svg xmlns="http://www.w3.org/2000/svg" data-diagram="requirement_breakdown_preview" data-root=\'requirement_1\'/>'
    )
    await client.get(url)
    renderer = session.renderer
    assert isinstance(renderer, FakeRenderer) and renderer.calls == 1  # Cached until the model changes.
    # Nothing is stored in the model.
    assert "requirement_breakdown_preview" not in session.repository.model.diagrams
    response = await client.get("/api/preview.svg?type=requirement&rule=x&root=requirement_1")
    assert response.status == 400 and "no diagram type 'requirement'" in (await response.json())["error"]
    response = await client.get("/api/preview.svg?type=requirement_breakdown&rule=mission&root=requirement_1")
    assert response.status == 400 and "not a generation rule" in (await response.json())["error"]
