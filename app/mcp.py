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

import asyncio
import datetime
import json
import time
from typing import Any, Awaitable, Callable

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
Api = Callable[..., Awaitable[Any]]      # api(method, path, json=None, params=None) -> the route's JSON

LIMIT = 100                              # most takes one call returns
MOST_WAIT = 55                           # seconds one wait_for_take may hold a call: short of a client's timeout
POLL = 2.0                               # how often it looks while waiting

TOOLS: list[dict] = [
    {
        "name": "list_takes",
        "description": "List takes in the library, newest first: id, title, kind (song, cover or instrumental), "
                       "status, length, style and when it was made. Titles are NOT unique: several takes can share one, "
                       "and `same_title_count` says so. Always act on a take by its id, and when more than one matches "
                       "what the person said, show them the choices (made, length, style) and ask which. "
                       "Use get_take for one in full.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Words that must appear in the title, style or lyrics."},
            "space": {"type": "string", "description": "Only the takes in this space, by name (see list_spaces)."},
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
        "name": "wait_for_take",
        "description": "Wait for a take that is being made, for up to about a minute, and return as soon as it is done or "
                       "has failed (or, for a take that is not rendering, as soon as its plan is ready). Returns the same "
                       "as get_take plus `finished`: if it is false the take is still going, so call this again. Use this "
                       "after make_song, make_instrumental or render_take rather than asking the person to check back.",
        "inputSchema": {"type": "object", "required": ["take_id"], "properties": {
            "take_id": {"type": "string"},
            "seconds": {"type": "integer", "description": f"How long to wait, at most {MOST_WAIT}. Default 45."},
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
            "max_duration": {"type": "integer", "description": "The most seconds the take may run, 10 to 900. Default 360. "
                                                                 "Ask for the length wanted: 60 for a minute."},
            "title": {"type": "string"},
            "seed": {"type": "integer"},
            "space": {"type": "string", "description": "The space to make it in, by name, such as \"EDM\" (see list_spaces). "
                                                      "Omit for the default space."},
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
            "max_duration": {"type": "integer", "description": "The most seconds the take may run, 10 to 900. Default 360. "
                                                                 "Ask for the length wanted: 60 for a minute."},
            "title": {"type": "string"},
            "seed": {"type": "integer"},
            "space": {"type": "string", "description": "The space to make it in, by name, such as \"EDM\" (see list_spaces). "
                                                      "Omit for the default space."},
            "render": {"type": "boolean", "description": "Render as well as plan. Default true."},
        }},
    },
    {
        "name": "move_take",
        "description": "Move a take to another space, by the space's name. Reversible: move it back. Take the id from "
                       "list_takes; never act on a title, since several takes can share one.",
        "inputSchema": {"type": "object", "required": ["take_id", "space"], "properties": {
            "take_id": {"type": "string"},
            "space": {"type": "string", "description": "The space to move it to, by name (see list_spaces)."},
        }},
    },
    {
        "name": "delete_take",
        "description": "Delete a take for good: its audio and its record cannot be got back. Two steps. Called with just "
                       "take_id it deletes NOTHING and returns what it would delete, with any other takes that share the "
                       "title. Show the person that, ask whether to go ahead, and only if they say yes call again with "
                       "confirm true. A starred take also needs even_if_starred true, and the person must have said so. "
                       "Take the id from list_takes; never act on a title.",
        "inputSchema": {"type": "object", "required": ["take_id"], "properties": {
            "take_id": {"type": "string"},
            "confirm": {"type": "boolean", "description": "True only after the person has agreed to this deletion."},
            "even_if_starred": {"type": "boolean", "description": "Needed as well when the take is starred."},
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

_BRIEF = ("id", "title", "kind", "status", "duration", "style", "favourite", "error")


def _when(stamp: Any) -> str | None:
    """A time a person can tell takes apart by."""
    try:
        return datetime.datetime.fromtimestamp(float(stamp)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return None


def _brief(take: dict, spaces: dict | None = None) -> dict:
    out = {key: take.get(key) for key in _BRIEF if take.get(key) not in (None, "")}
    out["has_audio"] = bool(take.get("has_audio"))
    out["made"] = _when(take.get("created_at"))
    if spaces and take.get("space_id") in spaces:
        out["space"] = spaces[take["space_id"]]           # the name, which an agent can say to a person
    return out


async def _space_names(api: Api) -> dict:
    return {space["id"]: space["name"] for space in await api("GET", "/api/spaces")}


def _full(take: dict, include_score: bool, spaces: dict | None = None) -> dict:
    out = {key: value for key, value in take.items()
           if value is not None and key not in ("abc", "audio_path", "prompt_id", "live", "weak_dismissed")}
    if spaces and take.get("space_id") in spaces:
        out["space"] = spaces[take["space_id"]]
    if take.get("live"):
        out["progress"] = take["live"]
    if include_score:
        out["score"] = take.get("abc")
    if take.get("has_audio"):
        out["audio_url"] = f"/api/takes/{take['id']}/audio"
    return out


def _settled(take: dict) -> bool:
    """Whether there is nothing more to wait for: done, failed, stopped, or a plan that is not going on to render."""
    status = take.get("status")
    if status in ("done", "failed", "cancelled", "stopped"):
        return True
    return status == "planned" and not take.get("auto_render")


async def _space_of(api: Api, asked: Any) -> str | None:
    """The id of the space an agent named, by name (any case, with or without the word "space") or by id.
    None when it named none. A name that matches nothing is an error that lists the spaces there are."""
    name = str(asked or "").strip()
    if not name:
        return None
    spaces = await api("GET", "/api/spaces")
    for space in spaces:
        if space["id"] == name:
            return space["id"]
    wanted = {name.lower()}
    if name.lower().endswith(" space"):
        wanted.add(name[:-6].strip().lower())
    found = [space for space in spaces if space["name"].strip().lower() in wanted]
    if len(found) == 1:
        return found[0]["id"]
    names = ", ".join(space["name"] for space in spaces)
    raise ApiRefused(f"{'More than one space is' if found else 'No space is'} called '{name}'. The spaces are: {names}.")


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
            space = await _space_of(api, args.get("space") or args.get("space_id"))
            if space:
                params["space_id"] = space
            spaces = await _space_names(api)
            found = [_brief(take, spaces) for take in await api("GET", "/api/takes", params=params)]
            same = {}
            for item in found:
                same[item.get("title")] = same.get(item.get("title"), 0) + 1
            for item in found:
                if same[item.get("title")] > 1:
                    item["same_title_count"] = same[item.get("title")]       # so an agent knows the title is not enough
            return _text(found)
        if name == "get_take":
            take = await api("GET", f"/api/takes/{args['take_id']}")
            return _text(_full(take, bool(args.get("include_score")), await _space_names(api)))
        if name == "wait_for_take":
            wait = max(1, min(MOST_WAIT, int(args.get("seconds") or 45)))
            deadline, started = time.monotonic() + wait, time.monotonic()
            while True:
                take = await api("GET", f"/api/takes/{args['take_id']}")
                if _settled(take) or time.monotonic() >= deadline:
                    break
                await asyncio.sleep(min(POLL, max(0.05, deadline - time.monotonic())))
            result = _full(take, False, await _space_names(api))
            result["finished"] = _settled(take)
            result["waited_seconds"] = round(time.monotonic() - started, 1)
            return _text(result)
        if name == "list_spaces":
            return _text(await api("GET", "/api/spaces"))
        if name in ("make_instrumental", "make_song"):
            body = {"style": args["style"], "auto_render": args.get("render") is not False}
            space = await _space_of(api, args.get("space") or args.get("space_id"))
            if space:
                body["space_id"] = space
            for key in ("title", "seed", "max_duration"):
                if args.get(key) not in (None, ""):
                    body[key] = args[key]
            if name == "make_instrumental":
                if args.get("structure"):
                    body["structure"] = args["structure"]
                made = await api("POST", "/api/instrumentals", json=body)
            else:
                body["lyrics"] = args["lyrics"]
                made = await api("POST", "/api/songs", json=body)
            return _text(_brief(made, await _space_names(api)) if isinstance(made, dict) and "id" in made else made)
        if name == "move_take":
            space = await _space_of(api, args.get("space"))
            if not space:
                return _text("say which space to move it to", True)
            await api("POST", f"/api/takes/{args['take_id']}/move", json={"space_id": space})
            return _text(_brief(await api("GET", f"/api/takes/{args['take_id']}"), await _space_names(api)))
        if name == "delete_take":
            take = await api("GET", f"/api/takes/{args['take_id']}")
            if take.get("favourite") and not args.get("even_if_starred"):
                return _text(f"'{take.get('title')}' ({take['id']}) is starred, so it was not deleted. If the person really wants it "
                             "gone, ask them, then call again with confirm and even_if_starred both true.", True)
            if not args.get("confirm"):
                spaces = await _space_names(api)
                same = [t for t in await api("GET", "/api/takes", params={"q": take.get("title") or "", "limit": LIMIT})
                        if t["id"] != take["id"] and t.get("title") == take.get("title")]
                return _text({
                    "deleted": False,
                    "message": "NOTHING WAS DELETED. This is the take that would be. Show the person its details, ask whether to "
                               "delete it for good, and if they agree call delete_take again with confirm true.",
                    "would_delete": _brief(take, spaces) | ({"running": "it is being made and would be stopped"}
                                                           if take.get("status") in ("queued", "running") else {}),
                    "other_takes_with_this_title": [_brief(t, spaces) for t in same],
                })
            await api("DELETE", f"/api/takes/{args['take_id']}")
            return _text({"deleted": True, "take": {"id": take["id"], "title": take.get("title"), "made": _when(take.get("created_at"))}})
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
