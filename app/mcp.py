"""Yeufonic as an MCP server: an agent can ask the app for songs, instrumentals and takes.

Only the part of the Model Context Protocol this needs: JSON-RPC 2.0 over one POST address (the
"streamable HTTP" transport, without sessions or server-sent streams), with the three requests a client makes
to use tools (`initialize`, `tools/list`, `tools/call`) and `ping`. A tool does what the page does, by
calling the app's own routes, so it has the same checks and the same effect, and a job it starts is an
ordinary take in the library.

It is off until `mcp.enabled` is switched on in Settings: a tool call can queue GPU work, and a client on
the same network could otherwise start it. The Host and cross-site checks the app applies to everything
apply to it too."""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
Api = Callable[..., Awaitable[Any]]      # api(method, path, json=None, params=None) -> the route's JSON

LIMIT = 100                              # most takes one call returns

TOOLS: list[dict] = [
    {
        "name": "list_takes",
        "description": "List takes in the library, newest first: id, title, kind (song, cover or instrumental), "
                       "status, length and style. Use get_take for one in full.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Words that must appear in the title, style or lyrics."},
            "space_id": {"type": "string", "description": "Only this space (see list_spaces)."},
            "favourites": {"type": "boolean", "description": "Only starred takes."},
            "limit": {"type": "integer", "description": f"How many, at most {LIMIT}. Default 20."},
        }},
    },
    {
        "name": "get_take",
        "description": "One take in full: how it was made, its status, any error, its lyrics or structure, and "
                       "where to fetch its audio once it has some.",
        "inputSchema": {"type": "object", "required": ["take_id"], "properties": {
            "take_id": {"type": "string"},
            "include_score": {"type": "boolean", "description": "Also return the score (ABC text). Default false: it is long."},
        }},
    },
    {
        "name": "list_spaces",
        "description": "The spaces takes are kept in, with how many each holds.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "make_instrumental",
        "description": "Make an instrumental from a style (and optionally a structure such as "
                       "'[intro]\\n[verse]\\n[chorus]\\n[outro]'). It plans the score and, unless render is false, "
                       "renders it. Takes minutes: check progress with get_take. Returns the new take.",
        "inputSchema": {"type": "object", "required": ["style"], "properties": {
            "style": {"type": "string", "description": "Comma-separated tags: genre, mood, instruments, tempo."},
            "structure": {"type": "string", "description": "One section tag per line. Omit to let the model decide."},
            "title": {"type": "string"},
            "seed": {"type": "integer"},
            "space_id": {"type": "string"},
            "render": {"type": "boolean", "description": "Render as well as plan. Default true."},
        }},
    },
    {
        "name": "make_song",
        "description": "Make a song from a style and lyrics (section tags like [Verse] and [Chorus] in the lyrics). "
                       "It plans the score and, unless render is false, renders it. Takes minutes: check progress "
                       "with get_take. Returns the new take.",
        "inputSchema": {"type": "object", "required": ["style", "lyrics"], "properties": {
            "style": {"type": "string"},
            "lyrics": {"type": "string"},
            "title": {"type": "string"},
            "seed": {"type": "integer"},
            "space_id": {"type": "string"},
            "render": {"type": "boolean", "description": "Render as well as plan. Default true."},
        }},
    },
    {
        "name": "render_take",
        "description": "Render a planned take, or render a finished one again (with new_seed for a different result).",
        "inputSchema": {"type": "object", "required": ["take_id"], "properties": {
            "take_id": {"type": "string"},
            "new_seed": {"type": "boolean"},
        }},
    },
    {
        "name": "cancel_take",
        "description": "Stop a take that is queued or running.",
        "inputSchema": {"type": "object", "required": ["take_id"], "properties": {"take_id": {"type": "string"}}},
    },
]

_BRIEF = ("id", "title", "kind", "status", "duration", "style", "space_id", "favourite", "created_at", "error")


def _brief(take: dict) -> dict:
    out = {key: take.get(key) for key in _BRIEF if take.get(key) not in (None, "")}
    out["has_audio"] = bool(take.get("has_audio"))
    return out


def _full(take: dict, include_score: bool) -> dict:
    out = {key: value for key, value in take.items()
           if value is not None and key not in ("abc", "audio_path", "prompt_id", "live", "weak_dismissed")}
    if take.get("live"):
        out["progress"] = take["live"]
    if include_score:
        out["score"] = take.get("abc")
    if take.get("has_audio"):
        out["audio_url"] = f"/api/takes/{take['id']}/audio"
    return out


def _text(value: Any, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": value if isinstance(value, str) else json.dumps(value, indent=2, default=str)}],
            "isError": error}


async def call_tool(name: str, args: dict, api: Api) -> dict:
    """Run one tool. A refusal from the app comes back as an error result the agent can read."""
    args = args or {}
    try:
        if name == "list_takes":
            limit = max(1, min(LIMIT, int(args.get("limit") or 20)))
            params = {"limit": limit, "q": args.get("query") or "", "favourite": bool(args.get("favourites"))}
            if args.get("space_id"):
                params["space_id"] = args["space_id"]
            return _text([_brief(take) for take in await api("GET", "/api/takes", params=params)])
        if name == "get_take":
            take = await api("GET", f"/api/takes/{args['take_id']}")
            return _text(_full(take, bool(args.get("include_score"))))
        if name == "list_spaces":
            return _text(await api("GET", "/api/spaces"))
        if name in ("make_instrumental", "make_song"):
            body = {"style": args["style"], "auto_render": args.get("render") is not False}
            for key in ("title", "seed", "space_id"):
                if args.get(key) not in (None, ""):
                    body[key] = args[key]
            if name == "make_instrumental":
                if args.get("structure"):
                    body["structure"] = args["structure"]
                made = await api("POST", "/api/instrumentals", json=body)
            else:
                body["lyrics"] = args["lyrics"]
                made = await api("POST", "/api/songs", json=body)
            return _text(_brief(made) if isinstance(made, dict) and "id" in made else made)
        if name == "render_take":
            made = await api("POST", f"/api/takes/{args['take_id']}/render", json={"reseed": bool(args.get("new_seed"))})
            return _text(made)
        if name == "cancel_take":
            return _text(await api("POST", f"/api/takes/{args['take_id']}/cancel"))
    except KeyError as missing:
        return _text(f"missing argument: {missing}", True)
    except ApiRefused as refused:
        return _text(str(refused), True)
    return _text(f"unknown tool: {name}", True)


class ApiRefused(Exception):
    """The app turned a request down, with its own reason."""


def error_reply(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def handle(message: Any, api: Api, version: str) -> dict | None:
    """One JSON-RPC message in, its reply out; None for a notification, which has none."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return error_reply(None, -32600, "not a JSON-RPC 2.0 request")
    request_id, method, params = message.get("id"), message.get("method"), message.get("params") or {}
    if "id" not in message:
        return None                                  # notifications/initialized, notifications/cancelled
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "yeufonic", "version": version},
            "instructions": "Yeufonic makes songs and instrumentals with YuE2. Making one takes minutes: start it, then "
                            "poll get_take until its status is done or failed.",
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        if not isinstance(params.get("name"), str):
            return error_reply(request_id, -32602, "a tool name is needed")
        return {"jsonrpc": "2.0", "id": request_id, "result": await call_tool(params["name"], params.get("arguments"), api)}
    return error_reply(request_id, -32601, f"method not found: {method}")
