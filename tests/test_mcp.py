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
    assert "wait_for_take" in result["instructions"] and "listen_url" in result["instructions"]
    assert rpc(client, "initialize", {"protocolVersion": "1999-01-01"}).json()["result"]["protocolVersion"] == "2025-06-18"


def test_a_notification_gets_no_reply_and_ping_is_answered(client, on):
    assert rpc(client, "notifications/initialized", id=None).status_code == 202
    assert rpc(client, "ping").json()["result"] == {}


def test_tools_are_listed_with_schemas(client, on):
    tools = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert {"list_takes", "get_take", "wait_for_take", "list_spaces", "make_instrumental", "make_song", "make_cover", "list_recordings", "list_style_loras", "try_more", "status", "transcribe_recording", "make_stems", "get_stems", "star_take", "rename_take", "move_take", "delete_take", "render_take", "cancel_take"} <= set(tools)
    assert all(t["inputSchema"]["type"] == "object" and t["description"] for t in tools.values())
    assert tools["make_song"]["inputSchema"]["required"] == ["style", "lyrics"]
    assert "max_duration" in tools["make_song"]["inputSchema"]["properties"]
    assert "max_duration" in tools["make_instrumental"]["inputSchema"]["properties"]


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


def test_wait_for_take_returns_at_once_for_a_finished_take_and_times_out_for_a_running_one(client, on):
    import time
    done = make_take(title="Finished", status="done")
    began = time.monotonic()
    error, result = call(client, "wait_for_take", take_id=done["id"], seconds=30)
    assert not error and result["finished"] is True and time.monotonic() - began < 5
    running = make_take(title="Still going", status="running")
    error, result = call(client, "wait_for_take", take_id=running["id"], seconds=1)
    assert not error and result["finished"] is False and 1 <= result["waited_seconds"] < 4 and result["status"] == "running"
    failed = make_take(title="Broke", status="failed")
    assert call(client, "wait_for_take", take_id=failed["id"], seconds=30)[1]["finished"] is True
    assert call(client, "wait_for_take", take_id="nothing")[0] is True


def test_a_plan_that_will_render_is_not_the_end_of_the_wait(client, on):
    from app.db import execute
    going = make_take(title="Plan then render", status="planned")
    execute("UPDATE takes SET auto_render = 1 WHERE id = ?", (going["id"],))
    assert call(client, "wait_for_take", take_id=going["id"], seconds=1)[1]["finished"] is False
    resting = make_take(title="Plan only", status="planned")
    assert call(client, "wait_for_take", take_id=resting["id"], seconds=1)[1]["finished"] is True


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


def test_a_length_asked_for_is_the_cap_the_take_gets(client, on, monkeypatch):
    from app import jobs
    from app.db import one
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", ["yue2_3b_bf16.safetensors"])
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", True)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    error, made = call(client, "make_instrumental", style="edm", max_duration=60)
    assert not error
    assert one("SELECT max_duration FROM takes WHERE id = ?", (made["id"],))["max_duration"] == 60
    error, refused = call(client, "make_instrumental", style="edm", max_duration=5)         # below the route's minimum
    assert error and "max_duration" in refused


def a_space(name):
    from app.db import execute
    import time, uuid
    ident = uuid.uuid4().hex[:12]
    execute("INSERT INTO spaces(id, name, created_at) VALUES(?, ?, ?)", (ident, name, time.time()))
    return ident


def test_a_space_is_named_by_its_name(client, on, monkeypatch):
    from app import jobs
    from app.db import one
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", ["yue2_3b_bf16.safetensors"])
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", True)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    edm = a_space("EDM")
    for asked in ("EDM", "edm", "  Edm  ", "EDM space", edm):
        error, made = call(client, "make_instrumental", style="edm", space=asked)
        assert not error, asked
        assert one("SELECT space_id FROM takes WHERE id = ?", (made["id"],))["space_id"] == edm, asked
        assert made["space"] == "EDM"


def test_an_unknown_space_is_an_error_that_names_the_ones_there_are(client, on):
    a_space("Folk")
    error, text = call(client, "make_instrumental", style="edm", space="Nowhere")
    assert error and "No space is called 'Nowhere'" in text and "Folk" in text and "Default" in text


def test_two_spaces_with_one_name_are_not_guessed_between(client, on):
    a_space("Twins")
    a_space("twins")
    error, text = call(client, "make_song", style="folk", lyrics="[Verse]\nla", space="Twins")
    assert error and "More than one space" in text


def test_list_takes_can_be_limited_to_a_space_by_name(client, on):
    folk, edm = a_space("Folk"), a_space("EDM")
    from app.db import execute
    for title, space in (("In folk", folk), ("In edm", edm)):
        execute("UPDATE takes SET space_id = ? WHERE id = ?", (space, make_take(title=title)["id"]))
    error, found = call(client, "list_takes", space="folk")
    assert not error and [t["title"] for t in found] == ["In folk"] and found[0]["space"] == "Folk"


def test_move_take_moves_by_id_to_a_space_by_name(client, on):
    from app.db import one
    folk = a_space("Folk")
    mine = make_take(title="Wanderer")
    error, moved = call(client, "move_take", take_id=mine["id"], space="folk")
    assert not error and moved["space"] == "Folk"
    assert one("SELECT space_id FROM takes WHERE id = ?", (mine["id"],))["space_id"] == folk
    assert call(client, "move_take", take_id=mine["id"], space="Nowhere")[0] is True
    assert call(client, "move_take", take_id="nothing", space="Folk")[0] is True
    assert call(client, "move_take", take_id=mine["id"])[0] is True


def test_takes_that_share_a_title_say_so_and_carry_a_time_to_tell_them_apart(client, on):
    a = make_take(title="Same name", created_at=1_700_000_000.0)
    b = make_take(title="Same name", created_at=1_700_000_500.0)
    make_take(title="Different")
    error, found = call(client, "list_takes", limit=10)
    same = [t for t in found if t["title"] == "Same name"]
    assert {t["id"] for t in same} == {a["id"], b["id"]}
    assert all(t["same_title_count"] == 2 for t in same) and same[0]["made"] != same[1]["made"]
    assert "same_title_count" not in [t for t in found if t["title"] == "Different"][0]


def test_delete_without_confirm_deletes_nothing_and_shows_what_would_go(client, on):
    from app.db import one
    keep = make_take(title="Twin", created_at=1_700_000_000.0)
    other = make_take(title="Twin", created_at=1_700_000_900.0)
    error, plan = call(client, "delete_take", take_id=keep["id"])
    assert not error and plan["deleted"] is False and "NOTHING WAS DELETED" in plan["message"]
    assert plan["would_delete"]["id"] == keep["id"]
    assert [t["id"] for t in plan["other_takes_with_this_title"]] == [other["id"]]      # the twin is named, so it can be told apart
    assert one("SELECT id FROM takes WHERE id = ?", (keep["id"],)) and one("SELECT id FROM takes WHERE id = ?", (other["id"],))


def test_delete_with_confirm_deletes_that_take_and_only_that_one(client, on):
    from app.db import one
    gone = make_take(title="Twin")
    kept = make_take(title="Twin")
    error, done = call(client, "delete_take", take_id=gone["id"], confirm=True)
    assert not error and done["deleted"] is True and done["take"]["id"] == gone["id"]
    assert one("SELECT id FROM takes WHERE id = ?", (gone["id"],)) is None
    assert one("SELECT id FROM takes WHERE id = ?", (kept["id"],))
    assert call(client, "delete_take", take_id="nothing", confirm=True)[0] is True


def test_a_starred_take_needs_to_be_asked_for_twice(client, on):
    from app.db import execute, one
    loved = make_take(title="Loved")
    execute("UPDATE takes SET favourite = 1 WHERE id = ?", (loved["id"],))
    error, text = call(client, "delete_take", take_id=loved["id"], confirm=True)
    assert error and "starred" in text and one("SELECT id FROM takes WHERE id = ?", (loved["id"],))
    error, done = call(client, "delete_take", take_id=loved["id"], confirm=True, even_if_starred=True)
    assert not error and done["deleted"] is True
    assert one("SELECT id FROM takes WHERE id = ?", (loved["id"],)) is None


def test_a_title_is_never_taken_for_an_id(client, on):
    make_take(title="By title")
    assert call(client, "delete_take", take_id="By title", confirm=True)[0] is True


def test_a_take_with_audio_gives_a_link_that_plays_in_a_browser(client, on, tmp_path):
    from app.db import execute
    sound = tmp_path / "take.flac"
    sound.write_bytes(b"fLaC" + b"\0" * 64)
    mine = make_take(title="Has sound")
    execute("UPDATE takes SET audio_path = ? WHERE id = ?", (str(sound), mine["id"]))
    error, one = call(client, "get_take", take_id=mine["id"])
    assert not error and one["listen_url"] == f"http://localhost/api/takes/{mine['id']}/audio"
    silent = make_take(title="Silent")
    assert "listen_url" not in call(client, "get_take", take_id=silent["id"])[1]
    played = client.get(f"/api/takes/{mine['id']}/audio")
    assert played.status_code == 200 and played.headers["content-disposition"].startswith("inline")      # plays, does not save
    saved = client.get(f"/api/takes/{mine['id']}/audio?download=true&format=flac")
    assert saved.status_code in (200, 500)             # the save path is unchanged; the stand-in file is not real audio


# ------------------------------------------------------------- recordings, covers, LoRAs, star and rename

def a_recording(tmp_path, title="Home demo", abc=None):
    from app.db import execute
    import uuid
    if abc is None:
        abc = ("X:1\nM:4/4\nL:1/16\nQ:1/4=90\nV: Vocal\nV: Ins\nK:C\n% verse\nV: Vocal\n" + '"C"z16|"G"z16|"Am"z16|"F"z16|\n' * 2 +
               "V: Ins\n" + "c4e4g4e4|B4d4g4d4|A4c4e4c4|F4A4c4A4|\n" * 2)
    path = tmp_path / f"{title}.wav"
    path.write_bytes(b"RIFF" + b"\0" * 64)
    ident = uuid.uuid4().hex[:12]
    execute("INSERT INTO sources(id, title, filename, stored_path, sha256, created_at, abc) VALUES(?, ?, ?, ?, ?, 1.0, ?)",
            (ident, title, path.name, str(path), ident, abc))
    return ident


def a_lora(monkeypatch, tmp_path, name="jazz.safetensors", trigger="jazzy", title="Jazz club", strengths="Planner 0.70, Sound 0.50"):
    import json, struct
    from app import jobs, loras
    root = tmp_path / "loras"
    root.mkdir(exist_ok=True)
    header = {"text_encoders.layer.0.weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]},
              "diffusion_model.block.1.weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}
    raw = json.dumps(header).encode()
    (root / name).write_bytes(struct.pack("<Q", len(raw)) + raw + b"\0" * 4)
    (root / name.replace(".safetensors", ".txt")).write_text(f"{title}\nTrigger: {trigger}\nStrengths: {strengths}\n")
    monkeypatch.setattr(loras, "folder", lambda: root)
    monkeypatch.setitem(jobs.ENGINE.options, "loras", [*jobs.ENGINE.options.get("loras", []), name])


def test_list_recordings_says_which_can_be_covered(client, on, tmp_path):
    ready = a_recording(tmp_path, "Home demo")
    bare = a_recording(tmp_path, "Voice memo", abc="")
    error, found = call(client, "list_recordings")
    by_id = {r["id"]: r for r in found}
    assert not error and by_id[ready]["has_score"] is True and by_id[bare]["has_score"] is False
    assert [r["id"] for r in call(client, "list_recordings", query="memo")[1]] == [bare]


def test_make_cover_queues_a_render_from_the_recordings_score(client, on, tmp_path, monkeypatch):
    from app import jobs
    from app.db import one
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", ["yue2_3b_bf16.safetensors"])
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    recording = a_recording(tmp_path)
    edm = a_space("EDM")
    error, made = call(client, "make_cover", recording_id=recording, style="synthwave, female vocal", lyrics="[Verse]\nla la la",
                       title="A cover", space="EDM")
    assert not error and made["kind"] == "cover" and made["space"] == "EDM"
    row = one("SELECT source_id, space_id, lyrics, status FROM takes WHERE id = ?", (made["id"],))
    assert row["source_id"] == recording and row["space_id"] == edm and "la la la" in row["lyrics"]
    queued = []
    while not jobs.QUEUE.empty():
        queued.append(jobs.QUEUE.get_nowait())
    assert any(item.get("kind") == "render" and item.get("id") == made["id"] for item in queued)


def test_make_cover_without_a_score_says_what_to_do(client, on, tmp_path):
    error, text = call(client, "make_cover", recording_id=a_recording(tmp_path, "Bare", abc=""), style="rock")
    assert error and "Transcribe" in text
    assert call(client, "make_cover", recording_id="nothing", style="rock")[0] is True


def test_make_cover_with_no_words_given_uses_the_recordings_own(client, on, tmp_path, monkeypatch):
    from app import jobs
    from app.db import execute, one
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", ["yue2_3b_bf16.safetensors"])
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    recording = a_recording(tmp_path)
    execute("UPDATE sources SET lyrics = ? WHERE id = ?", ("[Verse]\nheard in the recording", recording))
    error, made = call(client, "make_cover", recording_id=recording, style="rock")
    assert not error and "heard in the recording" in one("SELECT lyrics FROM takes WHERE id = ?", (made["id"],))["lyrics"]


def test_list_style_loras_gives_the_trigger_and_saved_strengths(client, on, tmp_path, monkeypatch):
    a_lora(monkeypatch, tmp_path)
    error, found = call(client, "list_style_loras")
    mine = [item for item in found if item["name"] == "jazz.safetensors"]
    assert not error and mine and mine[0]["trigger"] == "jazzy" and mine[0]["saved_planner"] == 0.7 and mine[0]["saved_sound"] == 0.5


def test_a_style_lora_is_chosen_by_title_with_its_trigger_put_first_and_its_saved_strengths(client, on, tmp_path, monkeypatch):
    from app import jobs
    from app.db import one
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", ["yue2_3b_bf16.safetensors"])
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    a_lora(monkeypatch, tmp_path)
    error, made = call(client, "make_song", style="swing, upright bass", lyrics="[Verse]\nla", style_lora="jazz club")
    assert not error
    row = one("SELECT style, style_lora, style_lora_clip, style_lora_model FROM takes WHERE id = ?", (made["id"],))
    assert row["style"].startswith("jazzy, ") and row["style_lora"] == "jazz.safetensors"
    assert (row["style_lora_clip"], row["style_lora_model"]) == (0.7, 0.5)           # the strengths saved with it
    error, again = call(client, "make_song", style="jazzy, swing", lyrics="[Verse]\nla", style_lora="jazz", lora_planner=0.3)
    row = one("SELECT style, style_lora_clip, style_lora_model FROM takes WHERE id = ?", (again["id"],))
    assert row["style"] == "jazzy, swing" and (row["style_lora_clip"], row["style_lora_model"]) == (0.3, 0.5)   # not added twice; asked-for strength wins


def test_an_unknown_style_lora_lists_the_ones_there_are(client, on, tmp_path, monkeypatch):
    a_lora(monkeypatch, tmp_path)
    error, text = call(client, "make_song", style="rock", lyrics="[Verse]\nla", style_lora="Nope")
    assert error and "No style LoRA is called 'Nope'" in text and "Jazz club" in text


def test_star_and_rename_work_by_id(client, on):
    from app.db import one
    mine = make_take(title="Draft")
    twin = make_take(title="Draft")
    assert call(client, "star_take", take_id=mine["id"])[1]["starred"] is True
    assert one("SELECT favourite FROM takes WHERE id = ?", (mine["id"],))["favourite"] == 1
    assert one("SELECT favourite FROM takes WHERE id = ?", (twin["id"],))["favourite"] == 0          # only the one asked for
    call(client, "star_take", take_id=mine["id"], starred=False)
    assert one("SELECT favourite FROM takes WHERE id = ?", (mine["id"],))["favourite"] == 0
    error, renamed = call(client, "rename_take", take_id=mine["id"], title="  Sunrise  ")
    assert not error and renamed["title"] == "Sunrise"
    assert one("SELECT title FROM takes WHERE id = ?", (twin["id"],))["title"] == "Draft"
    assert call(client, "rename_take", take_id=mine["id"], title="  ")[0] is True
    assert call(client, "star_take", take_id="nothing")[0] is True


def test_a_timed_structure_adds_up_to_the_length_asked_and_is_one_the_app_accepts():
    from app import instrumental
    from app.mcp import timed_structure
    for total in (30, 45, 60, 90, 100, 120, 150, 190, 240, 300, 600, 900):
        structure = timed_structure(total)
        assert instrumental.normalise(structure) == structure, total          # sections, in order, each starting where the last ended
        assert instrumental.seconds(structure) == total, total
        assert all(int(end[0]) * 60 + int(end[1]) - int(start[0]) * 60 - int(start[1]) >= 5
                   for start, end in [(l.split()[1].strip("]").split("-")[0].split(":"), l.split()[1].strip("]").split("-")[1].split(":"))
                                      for l in structure.splitlines()]), total      # no section under five seconds
    assert instrumental.seconds(timed_structure(10)) == 30                     # too short to hold four sections: the least that can
    assert timed_structure(60).splitlines()[0].startswith("[intro 0:00-")
    assert len(timed_structure(60).splitlines()) == 4 and len(timed_structure(300).splitlines()) == 8


def test_make_instrumental_never_sends_a_bare_structure(client, on, monkeypatch):
    from app import instrumental, jobs
    from app.db import one
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", ["yue2_3b_bf16.safetensors"])
    monkeypatch.setitem(jobs.ENGINE.options, "instrumental", True)
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    error, short = call(client, "make_instrumental", style="edm", max_duration=60)
    row = one("SELECT lyrics, max_duration FROM takes WHERE id = ?", (short["id"],))
    assert not error and instrumental.seconds(row["lyrics"]) == 60 and row["max_duration"] == 60
    error, plain = call(client, "make_instrumental", style="edm")
    row = one("SELECT lyrics, max_duration FROM takes WHERE id = ?", (plain["id"],))
    assert instrumental.seconds(row["lyrics"]) == 150 and row["max_duration"] == 180        # a default length, with room past it
    error, named = call(client, "make_instrumental", style="edm", structure="[verse]\n[chorus]")
    assert one("SELECT lyrics FROM takes WHERE id = ?", (named["id"],))["lyrics"] == "[verse]\n[chorus]"   # the person's own is kept as given


def test_a_take_can_be_named_by_the_start_of_its_id(client, on):
    from app.db import one
    a = make_take(title="Twin", id="abcd1234ef01")
    b = make_take(title="Twin", id="abcd9999ef02")
    c = make_take(title="Other", id="0f0f0f0f0f03")
    error, found = call(client, "list_takes", limit=10)
    assert {t["short_id"] for t in found} == {"abcd12", "abcd99", "0f0f0f"}
    assert call(client, "get_take", take_id="0f0f0f")[1]["id"] == c["id"]                 # the short id shown in the list
    assert call(client, "get_take", take_id="ABCD12")[1]["id"] == a["id"]                 # any case
    error, text = call(client, "get_take", take_id="abcd")                                 # starts two takes: not guessed
    assert error and "starts 2 takes" in text and a["id"] in text and b["id"] in text
    error, text = call(client, "delete_take", take_id="abc", confirm=True)                 # too short to be trusted
    assert error and "no such take" in text and one("SELECT id FROM takes WHERE id = ?", (a["id"],))
    assert call(client, "delete_take", take_id="abcd12", confirm=True)[1]["deleted"] is True
    assert one("SELECT id FROM takes WHERE id = ?", (a["id"],)) is None and one("SELECT id FROM takes WHERE id = ?", (b["id"],))
    assert call(client, "rename_take", take_id="abcd99", title="Renamed")[1]["title"] == "Renamed"
    assert call(client, "get_take", take_id="deadbeef")[0] is True


def test_the_instructions_ask_for_the_short_id_to_be_shown(client, on):
    result = rpc(client, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
    assert "short_id" in result["instructions"]
    tools = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert "short_id" in tools["list_takes"]["description"]


# ------------------------------------------------------------- try more, status, transcribe, stems

@pytest.fixture
def stems_idle(monkeypatch):
    import asyncio
    from app import jobs
    held = asyncio.Event()

    async def idle():
        await held.wait()
    monkeypatch.setattr(jobs, "stems_worker", idle)
    yield
    held.set()


def a_rendered_take(tmp_path, title="Finished", kind="cover", abc=None):
    from app.db import execute
    sound = tmp_path / f"{title}.flac"
    sound.write_bytes(b"fLaC" + b"\0" * 64)
    take = make_take(title=title, kind=kind, abc=abc or "", status="done")
    execute("UPDATE takes SET audio_path = ? WHERE id = ?", (str(sound), take["id"]))
    return take


def test_try_more_queues_new_takes_from_a_score_it_already_has(client, on, tmp_path, monkeypatch):
    from app import jobs
    from app.db import one, rows
    monkeypatch.setitem(jobs.ENGINE.options, "checkpoints", ["yue2_3b_bf16.safetensors"])
    monkeypatch.setattr(jobs.ENGINE, "options_loaded", True)
    recording = a_recording(tmp_path)
    original = make_take(title="Song", kind="cover", status="done", abc=one("SELECT abc FROM sources WHERE id = ?", (recording,))["abc"])
    error, made = call(client, "try_more", take_id=original["id"], count=3)
    assert not error and len(made["queued"]) == 3
    assert all(t["title"].startswith("Song") and t["short_id"] == t["id"][:6] for t in made["queued"])
    assert len({t["seed"] for t in made["queued"]}) == 3                                   # new seeds, each its own
    assert len(rows("SELECT id FROM takes WHERE title LIKE 'Song%'")) == 4                 # the original and three more
    error, text = call(client, "try_more", take_id=make_take(title="Empty", abc="")["id"])
    assert error and "no score" in text                                                    # the route's own refusal, as written


def test_status_says_whether_the_engine_is_ready_and_what_is_waiting(client, on):
    error, status = call(client, "status")
    assert not error and status["engine_online"] is False and "not online" in status["advice"]
    assert status["version"]


def test_transcribe_queues_a_recording_and_reports_where_it_is(client, on, tmp_path):
    from app import jobs
    from app.db import one
    bare = a_recording(tmp_path, "Voice memo", abc="")
    error, state = call(client, "transcribe_recording", recording_id=bare, wait_seconds=0)
    assert not error and state["transcription"] == "queued" and state["has_score"] is False and "call again" in state["next"]
    assert one("SELECT transcribe_state FROM sources WHERE id = ?", (bare,))["transcribe_state"] == "queued"
    queued = []
    while not jobs.QUEUE.empty():
        queued.append(jobs.QUEUE.get_nowait())
    assert any(item.get("kind") == "transcribe" and item.get("id") == bare for item in queued)
    again, state = call(client, "transcribe_recording", recording_id=bare, wait_seconds=0)        # already queued: not an error
    assert not again and state["transcription"] == "queued"
    assert call(client, "transcribe_recording", recording_id="nothing")[0] is True


def test_a_recording_that_has_a_score_is_not_transcribed_again_unless_asked(client, on, tmp_path):
    from app.db import execute, one
    ready = a_recording(tmp_path)
    execute("UPDATE sources SET transcribe_state = 'done' WHERE id = ?", (ready,))
    error, state = call(client, "transcribe_recording", recording_id=ready, wait_seconds=0)
    assert not error and state["has_score"] is True and "already has a score" in state["next"]
    assert one("SELECT transcribe_state FROM sources WHERE id = ?", (ready,))["transcribe_state"] == "done"      # left as it was
    assert call(client, "transcribe_recording", recording_id=ready, wait_seconds=0, again=True)[1]["transcription"] == "queued"


def test_make_stems_and_get_stems_follow_a_take_through(client, on, tmp_path, stems_idle):
    from app.db import execute
    take = a_rendered_take(tmp_path)
    error, made = call(client, "make_stems", take_id=take["id"], kind="vocals_and_instruments", format="flac")
    assert not error and made["parts"] == ["vocals", "instruments"] and made["status"] == "queued"
    error, got = call(client, "get_stems", take_id=take["id"])
    assert not error and got["any_running"] is True and got["stem_sets"][0]["model"] == "htdemucs_2s"
    # once done, the files come with links a browser can open
    folder = tmp_path / "stems"
    folder.mkdir()
    (folder / "vocals.flac").write_bytes(b"fLaC")
    (folder / "instruments.flac").write_bytes(b"fLaC")
    execute("UPDATE stem_sets SET status = 'done', folder = ? WHERE id = ?", (str(folder), made["stem_set"]))
    error, done = call(client, "get_stems", take_id=take["id"])
    first = done["stem_sets"][0]
    assert not error and done["any_running"] is False and first["status"] == "done"
    assert {f["name"] for f in first["files"]} == {"vocals", "instruments"}
    assert first["files"][0]["url"].startswith(f"http://localhost/api/stem-sets/{made['stem_set']}/")
    assert first["zip_url"] == f"http://localhost/api/stem-sets/{made['stem_set']}/zip"


def test_stems_need_a_finished_take_and_a_known_kind(client, on, tmp_path, stems_idle):
    error, text = call(client, "make_stems", take_id=make_take(title="No sound")["id"])
    assert error and "no audio" in text
    take = a_rendered_take(tmp_path, "Has sound")
    assert call(client, "make_stems", take_id=take["id"], kind="seven")[0] is True
    error, none = call(client, "get_stems", take_id=take["id"])
    assert not error and none["stem_sets"] == [] and "No stems have been made" in none["message"]


def test_list_recordings_says_where_transcription_is(client, on, tmp_path):
    bare = a_recording(tmp_path, "Memo", abc="")
    found = {r["id"]: r for r in call(client, "list_recordings")[1]}
    assert "transcription" in found[bare]
