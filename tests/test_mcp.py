"""Yeufonic as an MCP server (app/mcp.py): the protocol's few requests, the tools, and the switch that keeps it off."""
import pytest

from app.db import set_setting
from app.jobs import QUEUE
from conftest import make_take


def rpc(client, method, params=None, id=1):
    message = {"jsonrpc": "2.0", "method": method}
    if id is not None:
        message["id"] = id
    if params is not None:
        message["params"] = params
    return client.post("/mcp", json=message)


@pytest.fixture
def on(client):
    set_setting("mcp.enabled", "on")
    yield
    set_setting("mcp.enabled", "off")


def test_it_is_off_until_it_is_turned_on(client):
    reply = rpc(client, "tools/list")
    # Not 401 or 403: a client reads those as "sign in first" and goes looking for an OAuth server this does not have.
    assert reply.status_code == 503
    assert "off" in reply.json()["error"]["message"].lower()


def test_a_page_on_another_site_cannot_reach_it(client, on):
    reply = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"origin": "https://elsewhere.example"})
    assert reply.status_code == 403
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"host": "evil.example"}).status_code == 421


def test_initialize_names_the_server_and_agrees_a_protocol_version(client, on):
    result = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}).json()["result"]
    assert result["serverInfo"]["name"] == "yeufonic" and result["protocolVersion"] == "2025-03-26"
    assert "tools" in result["capabilities"]
    assert rpc(client, "initialize", {"protocolVersion": "1999-01-01"}).json()["result"]["protocolVersion"] == "2025-06-18"


def test_a_notification_gets_no_reply_and_ping_is_answered(client, on):
    assert rpc(client, "notifications/initialized", id=None).status_code == 202
    assert rpc(client, "ping").json()["result"] == {}


def test_tools_are_listed_with_schemas(client, on):
    tools = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert {"list_takes", "get_take", "list_spaces", "make_instrumental", "make_song", "render_take", "cancel_take"} <= set(tools)
    assert all(t["inputSchema"]["type"] == "object" and t["description"] for t in tools.values())
    assert tools["make_song"]["inputSchema"]["required"] == ["style", "lyrics"]


def test_an_unknown_method_and_a_bad_message_are_errors(client, on):
    assert rpc(client, "no/such").json()["error"]["code"] == -32601
    assert client.post("/mcp", json={"hello": 1}).json()["error"]["code"] == -32600
    assert client.post("/mcp", content=b"not json", headers={"content-type": "application/json"}).status_code == 400


def call(client, name, **arguments):
    reply = rpc(client, "tools/call", {"name": name, "arguments": arguments}).json()["result"]
    import json
    return reply["isError"], json.loads(reply["content"][0]["text"]) if not reply["isError"] else reply["content"][0]["text"]


def test_list_and_get_take_read_the_library(client, on):
    mine = make_take(title="A calm piece", style="ambient, piano", kind="instrumental", abc="X:1\nK:C\nabc|")
    make_take(title="Something loud", style="metal")
    error, found = call(client, "list_takes", query="calm")
    assert not error and [t["id"] for t in found] == [mine["id"]]
    assert isinstance(found[0]["space"], str) and found[0]["space"]       # the space's name, not only its id
    error, one = call(client, "get_take", take_id=mine["id"])
    assert not error and one["title"] == "A calm piece" and "score" not in one and "abc" not in one
    assert isinstance(one["space"], str) and one["space"]
    assert call(client, "get_take", take_id=mine["id"], include_score=True)[1]["score"].startswith("X:1")
    error, missing = call(client, "get_take", take_id="nothing")
    assert error and "no such take" in missing
    assert call(client, "get_take")[0] is True                    # a missing argument is an error the agent can read


def test_list_spaces(client, on):
    error, spaces = call(client, "list_spaces")
    assert not error and spaces and "name" in spaces[0]


def test_make_song_queues_a_plan_like_the_page_does(client, on, monkeypatch):
    from app import jobs
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", ["yue2_3b_bf16.safetensors"])
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    error, made = call(client, "make_song", style="folk", lyrics="[Verse]\nla la la", title="From an agent")
    assert not error and made["title"] == "From an agent" and made["kind"] == "song"
    queued = []
    while not QUEUE.empty():
        queued.append(QUEUE.get_nowait())
    assert queued, "the plan went to the queue"
    error, refused = call(client, "make_song", style="folk", lyrics="   ")
    assert error and "lyrics" in refused                          # the route's own check, passed on as written


def test_the_page_still_works_with_it_off(client):
    assert client.get("/api/spaces").status_code == 200
