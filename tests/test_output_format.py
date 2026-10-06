"""One output format, set in Settings, for stems and for a take's Save.  A setting
that only repeats its default is not stored, so a better default reaches everyone."""
import subprocess

from app.db import get_setting, set_setting

from conftest import make_take, tone


def test_saving_a_default_does_not_store_it(client):
    client.put("/api/settings", json={"key": "stems.format", "value": "flac"})
    assert get_setting("stems.format") is None
    client.put("/api/settings", json={"key": "stems.format", "value": "mp3"})
    assert get_setting("stems.format") == "mp3"


def test_old_frozen_defaults_are_forgotten_at_start(client):
    from app.main import forget_frozen_defaults

    set_setting("stems.format", "wav")               # the old default, stored by a save
    set_setting("stems.model", "htdemucs")           # the default, stored by a save
    set_setting("stems.folder", "/data/my-stems")    # a real choice
    assert forget_frozen_defaults() == 2
    assert get_setting("stems.format") is None and get_setting("stems.model") is None
    assert get_setting("stems.folder") == "/data/my-stems"


def test_the_setting_is_named_for_takes_too(client):
    item = {s["key"]: s for s in client.get("/api/settings").json()["settings"]}["stems.format"]
    assert item["label"] == "Output audio format" and item["value"] == "flac"
    assert "takes" in item["help"]


def probe(content: bytes, tmp_path) -> str:
    path = tmp_path / "got"
    path.write_bytes(content)
    return subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True).stdout.strip()


def test_save_hands_over_a_take_in_the_chosen_format(client, tmp_path):
    take = make_take(title="Save Me", audio_path=str(tone(tmp_path / "take.flac", 1.0)))
    url = f"/api/takes/{take['id']}/audio?download=1"

    got = client.get(url)
    assert got.headers["content-type"] == "audio/flac" and "Save%20Me.flac" in got.headers["content-disposition"]
    assert probe(got.content, tmp_path) == "flac"

    set_setting("stems.format", "wav")
    got = client.get(url)
    assert got.headers["content-type"] == "audio/wav" and "Save%20Me.wav" in got.headers["content-disposition"]
    assert probe(got.content, tmp_path) == "pcm_s16le"

    set_setting("stems.format", "mp3")
    got = client.get(url)
    assert got.headers["content-type"] == "audio/mpeg" and probe(got.content, tmp_path) == "mp3"

    # Playing is always the FLAC as kept, whatever the setting.
    assert client.get(f"/api/takes/{take['id']}/audio").headers["content-type"] == "audio/flac"


def test_save_can_ask_for_a_format_over_the_setting(client, tmp_path):
    take = make_take(title="Pick", audio_path=str(tone(tmp_path / "take.flac", 1.0)))
    url = f"/api/takes/{take['id']}/audio?download=1"
    set_setting("stems.format", "mp3")

    got = client.get(url + "&format=wav")
    assert got.headers["content-type"] == "audio/wav" and "Pick.wav" in got.headers["content-disposition"]
    got = client.get(url + "&format=flac")
    assert got.headers["content-type"] == "audio/flac" and probe(got.content, tmp_path) == "flac"
    assert client.get(url + "&format=ogg").status_code == 400


# ---------- the tags on a saved take ----------
WORDS = "[Verse]\nPaper lanterns on the tide\nNamed for no one\n\n[Chorus]\nLa la la"


def id3_frames(content: bytes) -> dict[str, list[bytes]]:
    """Frame id to bodies, read straight from an ID3v2.3 tag, so a real COMM or USLT
    frame cannot pass for a TXXX that ffprobe would also show as 'comment'."""
    assert content[:3] == b"ID3" and content[3] == 3
    size = sum((b & 0x7F) << (7 * (3 - i)) for i, b in enumerate(content[6:10]))   # syncsafe
    frames, at = {}, 10
    while at < 10 + size and content[at:at + 4].strip(b"\0"):
        n = int.from_bytes(content[at + 4:at + 8], "big")
        frames.setdefault(content[at:at + 4].decode(), []).append(content[at + 10:at + 10 + n])
        at += 10 + n
    return frames


def flac_comments(content: bytes) -> tuple[str, dict[str, str]]:
    """The vendor string and fields of a FLAC's tag block, read raw: ffprobe shows a
    DESCRIPTION as 'comment' too, so it cannot tell the two apart."""
    assert content[:4] == b"fLaC"
    at, last = 4, False
    while not last:
        last, kind = bool(content[at] & 0x80), content[at] & 0x7F
        size = int.from_bytes(content[at + 1:at + 4], "big")
        body = content[at + 4:at + 4 + size]
        if kind == 4:
            n = int.from_bytes(body[:4], "little")
            vendor, pos, fields = body[4:4 + n].decode(), 8 + n, {}
            for _ in range(int.from_bytes(body[4 + n:8 + n], "little")):
                length = int.from_bytes(body[pos:pos + 4], "little")
                key, _, value = body[pos + 4:pos + 4 + length].decode().partition("=")
                fields[key] = value
                pos += 4 + length
            return vendor, fields
        at += 4 + size
    raise AssertionError("no tag block")


def tags_of(content: bytes, tmp_path, suffix: str) -> dict:
    import json
    path = tmp_path / f"got.{suffix}"
    path.write_bytes(content)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    return {k.lower(): v for k, v in json.loads(out)["format"].get("tags", {}).items()}


def pcm_md5(path) -> str:
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "md5", "-"],
                          capture_output=True, text=True).stdout.strip()


def engine_take(tmp_path, **fields):
    """A take whose FLAC carries a graph in 'prompt', as the engine's save node writes."""
    rendered = tone(tmp_path / "rendered.flac", 1.0)
    stored = tmp_path / "take.flac"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(rendered), "-c", "copy",
                    "-metadata", 'prompt={"10": {"class_type": "CheckpointLoaderSimple"}}', str(stored)], check=True)
    return make_take(audio_path=str(stored), **fields)


def test_an_mp3_says_what_it_is_in_frames_players_read(client, tmp_path):
    from app import config
    take = engine_take(tmp_path, title="Paper Lanterns", lyrics=WORDS)
    got = client.get(f"/api/takes/{take['id']}/audio?download=1&format=mp3").content

    frames = id3_frames(got)
    assert frames["TIT2"] == [b"\x01" + "Paper Lanterns".encode("utf-16")]
    assert frames["COMM"] == [b"\x01eng" + "".encode("utf-16") + b"\0\0" + "Made with Yeufonic".encode("utf-16")]
    assert frames["USLT"] == [b"\x01XXX" + "".encode("utf-16") + b"\0\0" + WORDS.encode("utf-16")]
    assert frames["TSSE"] == [b"\x01" + f"Yeufonic {config.VERSION}".encode("utf-16")]
    # The engine's graph rides along; ffmpeg's own name for itself does not.
    txxx = frames["TXXX"]
    assert len(txxx) == 1 and txxx[0].startswith(b"\x01" + "prompt".encode("utf-16") + b"\0\0")

    tags = tags_of(got, tmp_path, "mp3")
    assert tags["title"] == "Paper Lanterns" and tags["comment"] == "Made with Yeufonic"
    assert "CheckpointLoaderSimple" in tags["prompt"]
    assert probe(got, tmp_path) == "mp3"


def test_a_flac_gains_tags_and_keeps_its_audio_to_the_bit(client, tmp_path):
    take = engine_take(tmp_path, title="Paper Lanterns", lyrics=WORDS)
    got = client.get(f"/api/takes/{take['id']}/audio?download=1&format=flac")
    assert got.headers["content-type"] == "audio/flac"

    from app import config
    vendor, fields = flac_comments(got.content)
    assert vendor == f"Yeufonic {config.VERSION}"
    assert fields["TITLE"] == "Paper Lanterns" and fields["COMMENT"] == "Made with Yeufonic"
    assert "DESCRIPTION" not in fields and fields["LYRICS"] == WORDS
    assert "CheckpointLoaderSimple" in fields["prompt"]
    # ffprobe and ffmpeg still read the file, and the audio is the take's to the bit.
    assert tags_of(got.content, tmp_path, "flac")["title"] == "Paper Lanterns"
    assert pcm_md5(tmp_path / "got.flac") == pcm_md5(take["audio_path"])
    # Playing still hands over the file as kept.
    played = client.get(f"/api/takes/{take['id']}/audio").content
    assert played == open(take["audio_path"], "rb").read()


def test_a_wav_has_a_title_and_the_comment(client, tmp_path):
    take = engine_take(tmp_path, title="Paper Lanterns", lyrics=WORDS)
    got = client.get(f"/api/takes/{take['id']}/audio?download=1&format=wav").content
    tags = tags_of(got, tmp_path, "wav")
    assert tags["title"] == "Paper Lanterns" and tags["comment"] == "Made with Yeufonic"


def test_nothing_sung_means_no_lyrics_tag(client, tmp_path):
    from app.library import sung_words
    assert sung_words("instrumental", WORDS) is None
    assert sung_words("song", "[intro]\n[verse]\n[chorus]\n[outro]") is None
    assert sung_words("song", "") is None and sung_words("cover", None) is None
    assert sung_words("cover", WORDS) == WORDS

    take = engine_take(tmp_path, title="Tide Table", kind="instrumental", lyrics="[instrumental]")
    frames = id3_frames(client.get(f"/api/takes/{take['id']}/audio?download=1&format=mp3").content)
    assert "USLT" not in frames and "COMM" in frames
    got = client.get(f"/api/takes/{take['id']}/audio?download=1&format=flac").content
    assert "LYRICS" not in flac_comments(got)[1]
