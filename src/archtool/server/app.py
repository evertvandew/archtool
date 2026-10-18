"""The collaboration server.

One server serves one model. It holds the model in memory, with the editing engine, and:

* serves the web client (`/`), and a snapshot of the model as JSON (`/api/model`);
* executes commands sent by clients over a WebSocket (`/api/socket`), one at a time, writing the changes to the files,
  and tells all clients that the model changed, so that they refresh;
* renders diagrams as SVG (`/api/diagrams/<id>.svg`), and previews of generated diagrams that are not stored
  (`/api/preview.svg`);
* allocates identifiers (`POST /api/identifiers`);
* makes the exports that archtool.toml declares, files made from an element by a command (`/api/exports/<n>/<id>`).

When two users edit the same element at the same moment, the last write wins. See "Collaboration server" in
doc/architecture.md.
"""

import asyncio
import json
import mimetypes
from importlib import resources
from pathlib import Path

from aiohttp import WSMsgType, web

from archtool.diagrams.render import RenderError, Renderer
from archtool.editing.editor import Editor
from archtool.exports import Exported, ExportError, run_export
from archtool.language.runtime import Runner
from archtool.repository import Repository, save_repository
from archtool.server.snapshot import snapshot

STATIC = resources.files("archtool.server") / "static"
_SESSION: web.AppKey["Session"] = web.AppKey("session")


class Session:
    """The state of the server: the model, its version, and the connected clients."""

    def __init__(self, repository: Repository, renderer: Renderer | None = None) -> None:
        self.repository = repository
        self.editor = Editor(repository)
        self.renderer = renderer if renderer is not None else Renderer(repository)
        self.version = 0
        self.lock = asyncio.Lock()
        self.sockets: set[web.WebSocketResponse] = set()
        self._svg: dict[str, tuple[int, str]] = {}

    async def execute(self, line: str) -> dict[str, object]:
        """Execute a command line, and tell all clients when the model changed."""
        async with self.lock:
            result = self.editor.run(line)
            if result is None:
                return {"ok": True, "command": "", "created": [], "changed": [], "deleted": [], "issues": [], "resolved": []}
            if result.ok:
                self.version += 1
            record = result.to_json()
        if result.ok:
            await self.broadcast({"type": "changed", "version": self.version})
        return record

    async def broadcast(self, message: dict[str, object]) -> None:
        text = json.dumps(message)
        for socket in list(self.sockets):
            if not socket.closed:
                await socket.send_str(text)

    async def preview(self, diagram_type: str, rule: str, arguments: tuple[tuple[str, str], ...]) -> str:
        """The SVG of a generated diagram that is not stored, rendered at most once per version of the model."""
        key = f"{diagram_type}:{rule}:{arguments}"
        async with self.lock:
            cached = self._svg.get(key)
            if cached is not None and cached[0] == self.version:
                return cached[1]
            loop = asyncio.get_running_loop()
            svg = await loop.run_in_executor(None, self.renderer.preview, diagram_type, rule, arguments)
            self._svg[key] = (self.version, svg)
            return svg

    async def export(self, number: int, identifier: str) -> Exported:
        """Make an export of an element. The model cannot change meanwhile, as the command reads its files."""
        async with self.lock:
            model = self.repository.model
            label = Runner(self.editor.rules, model).default_label(identifier) if identifier in model else identifier
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, run_export, self.repository, number, identifier, label)

    async def svg(self, identifier: str) -> str:
        """The SVG of a diagram, rendered at most once per version of the model."""
        async with self.lock:
            cached = self._svg.get(identifier)
            if cached is not None and cached[0] == self.version:
                return cached[1]
            # Rendering runs elk-cli, so it runs in a thread; commands wait, as the model must not change meanwhile.
            loop = asyncio.get_running_loop()
            svg = await loop.run_in_executor(None, self.renderer.render, identifier)
            self._svg[identifier] = (self.version, svg)
            return svg


def create_app(session: Session) -> web.Application:
    app = web.Application()
    app[_SESSION] = session
    app.router.add_get("/", index)
    app.router.add_get("/static/{name}", static)
    app.router.add_get("/api/model", model)
    app.router.add_get("/api/diagrams/{identifier}.svg", diagram)
    app.router.add_get("/api/preview.svg", preview)
    app.router.add_get("/api/exports/{number:[0-9]+}/{identifier}", export)
    app.router.add_post("/api/identifiers", identifier)
    app.router.add_post("/api/commands", command)
    app.router.add_get("/api/socket", socket)
    return app


async def index(request: web.Request) -> web.Response:
    return web.Response(text=(STATIC / "index.html").read_text(encoding="utf-8"), content_type="text/html")


async def static(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    types = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
    content_type = types.get(Path(name).suffix)
    resource = STATIC / name
    if content_type is None or "/" in name or not resource.is_file():
        raise web.HTTPNotFound()
    return web.Response(text=resource.read_text(encoding="utf-8"), content_type=content_type)


async def model(request: web.Request) -> web.Response:
    session = request.app[_SESSION]
    async with session.lock:
        model = session.repository.model
        data = snapshot(model, session.editor.rules, session.editor.findings, session.version, session.repository.settings.exports)
    return web.json_response(data)


async def diagram(request: web.Request) -> web.Response:
    session = request.app[_SESSION]
    try:
        svg = await session.svg(request.match_info["identifier"])
    except RenderError as error:
        return web.json_response({"error": str(error)}, status=404 if "no diagram" in str(error) else 500)
    return web.Response(text=svg, content_type="image/svg+xml")


async def preview(request: web.Request) -> web.Response:
    """A generated diagram that is not stored: `?type=<diagram type>&rule=<rule>&<parameter>=<value>…`."""
    session = request.app[_SESSION]
    query = request.query
    diagram_type, rule = query.get("type", ""), query.get("rule", "")
    arguments = tuple((key, value) for key, value in query.items() if key not in ("type", "rule", "version"))
    try:
        svg = await session.preview(diagram_type, rule, arguments)
    except RenderError as error:
        return web.json_response({"error": str(error)}, status=400)
    return web.Response(text=svg, content_type="image/svg+xml")


async def export(request: web.Request) -> web.Response:
    """A file made from an element by an export of archtool.toml, as a download."""
    session = request.app[_SESSION]
    try:
        exported = await session.export(int(request.match_info["number"]), request.match_info["identifier"])
    except ExportError as error:
        return web.json_response({"error": str(error)}, status=error.status)
    content_type = mimetypes.guess_type(exported.file)[0] or "application/octet-stream"
    disposition = f'attachment; filename="{exported.file}"'
    return web.Response(body=exported.content, content_type=content_type, headers={"Content-Disposition": disposition})


async def identifier(request: web.Request) -> web.Response:
    """Allocate an identifier for a new element of a type: `{"type": "function"}` → `{"id": "function_43"}`."""
    session = request.app[_SESSION]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "expected a JSON object"}, status=400)
    type_name = body.get("type") if isinstance(body, dict) else None
    if not isinstance(type_name, str) or type_name not in session.repository.metamodel.types:
        return web.json_response({"error": f"unknown type {type_name!r}"}, status=400)
    async with session.lock:
        allocated = session.repository.model.new_identifier(type_name)
        save_repository(session.repository)
    return web.json_response({"id": allocated})


async def command(request: web.Request) -> web.Response:
    """Execute a command sent as `{"command": "…"}`, for clients without a WebSocket."""
    session = request.app[_SESSION]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "expected a JSON object"}, status=400)
    line = body.get("command") if isinstance(body, dict) else None
    if not isinstance(line, str):
        return web.json_response({"error": "expected {\"command\": \"…\"}"}, status=400)
    return web.json_response(await session.execute(line))


async def socket(request: web.Request) -> web.WebSocketResponse:
    """Clients send `{"request": n, "command": "…"}`, and receive `{"type": "result", "request": n, …}`. All clients
    receive `{"type": "changed", "version": v}` when the model changes."""
    session = request.app[_SESSION]
    websocket = web.WebSocketResponse(heartbeat=30)
    await websocket.prepare(request)
    session.sockets.add(websocket)
    try:
        await websocket.send_str(json.dumps({"type": "hello", "version": session.version}))
        async for message in websocket:
            if message.type != WSMsgType.TEXT:
                continue
            try:
                body = json.loads(message.data)
            except json.JSONDecodeError:
                await websocket.send_str(json.dumps({"type": "error", "error": "expected a JSON object"}))
                continue
            line = body.get("command") if isinstance(body, dict) else None
            if not isinstance(line, str):
                await websocket.send_str(json.dumps({"type": "error", "error": "expected a command"}))
                continue
            result = await session.execute(line)
            await websocket.send_str(json.dumps({"type": "result", "request": body.get("request"), **result}))
    finally:
        session.sockets.discard(websocket)
    return websocket


def serve(repository: Repository, host: str, port: int) -> None:
    web.run_app(create_app(Session(repository)), host=host, port=port, print=None)
