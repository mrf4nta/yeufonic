"""The note samples the score preview plays with."""
from app import config, soundfonts


def fake_samples(monkeypatch, tmp_path, fail_on=None, absent=()):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    fetched = []

    class Reply:
        def __init__(self, content, status=200):
            self.content = content
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise soundfonts.httpx.HTTPStatusError(
                    "no such note", request=soundfonts.httpx.Request("GET", "http://x"), response=self)

    def get(url, **kwargs):
        fetched.append(url)
        if fail_on and url.endswith(fail_on):
            raise RuntimeError("network down")
        if any(url.endswith(note) for note in absent):
            return Reply(b"", 404)               # the publisher's set stops short of this note
        return Reply(b"mp3:" + url.rsplit("/", 1)[1].encode())
    monkeypatch.setattr(soundfonts.httpx, "get", get)
    return fetched


def test_the_note_names_are_the_88_keys_named_as_the_files_are():
    assert len(soundfonts.NOTES) == 88 == len(set(soundfonts.NOTES))
    assert soundfonts.NOTES[:4] == ["A0", "Bb0", "B0", "C1"] and soundfonts.NOTES[-1] == "C8"
    assert {"Db1", "Eb4", "Gb7", "Ab3", "Bb7"} <= set(soundfonts.NOTES) and not any("#" in n for n in soundfonts.NOTES)


def test_the_sounds_are_fetched_only_when_asked_and_then_served(client, monkeypatch, tmp_path):
    fetched = fake_samples(monkeypatch, tmp_path)
    status = client.get("/api/soundfonts").json()
    assert status["installed"] == [] and status["ready"] is False and status["megabytes"] == 7
    # Every set the preview can choose between is offered, and only those.
    assert {item["id"] for item in status["available"]} == set(soundfonts.SETS)
    assert {"acoustic_grand_piano", "electric_guitar_clean", "voice_oohs"} <= set(soundfonts.SETS)
    assert client.get("/soundfonts/acoustic_grand_piano-mp3/C4.mp3").status_code == 404      # nothing fetched by looking
    assert fetched == []
    reply = client.post("/api/soundfonts/acoustic_grand_piano/download")
    assert reply.status_code == 200 and reply.json()["fetched"] == 88 and reply.json()["installed"] == ["acoustic_grand_piano"]
    assert all(u.startswith(soundfonts.UPSTREAM) for u in fetched) and len(fetched) == 88
    note = client.get("/soundfonts/acoustic_grand_piano-mp3/Bb3.mp3")
    assert note.status_code == 200 and note.content == b"mp3:Bb3.mp3" and note.headers["content-type"] == "audio/mpeg"
    assert client.get("/api/soundfonts").json()["ready"] is True
    assert client.post("/api/soundfonts/acoustic_grand_piano/download").json()["fetched"] == 0        # and not again


def test_only_known_instruments_and_note_names_are_served(client, monkeypatch, tmp_path):
    fake_samples(monkeypatch, tmp_path)
    client.post("/api/soundfonts/acoustic_grand_piano/download")
    (tmp_path / "secret.mp3").write_bytes(b"no")
    for bad in ("/soundfonts/acoustic_grand_piano-mp3/..%2F..%2Fsecret.mp3", "/soundfonts/acoustic_grand_piano-mp3/H4.mp3",
                "/soundfonts/tuba-mp3/C4.mp3", "/soundfonts/acoustic_grand_piano-mp3/C9.mp3"):
        assert client.get(bad).status_code == 404, bad
    assert client.post("/api/soundfonts/tuba/download").status_code == 404


def test_a_set_that_stops_short_still_installs(client, monkeypatch, tmp_path):
    """A bass set holds 64 notes and a voice 76: what the publisher has is what plays."""
    fake_samples(monkeypatch, tmp_path, absent=("C8.mp3", "B7.mp3"))
    reply = client.post("/api/soundfonts/acoustic_grand_piano/download")
    assert reply.status_code == 200 and reply.json()["fetched"] == 86
    assert reply.json()["installed"] == ["acoustic_grand_piano"]
    status = client.get("/api/soundfonts").json()
    assert status["ranges"] == {"acoustic_grand_piano": [21, 106]}      # Bb7 is the top note left
    assert client.get("/soundfonts/acoustic_grand_piano-mp3/C8.mp3").status_code == 404
    assert client.get("/soundfonts/acoustic_grand_piano-mp3/Bb7.mp3").status_code == 200


def test_a_failed_fetch_says_so_and_leaves_no_half_files(client, monkeypatch, tmp_path):
    fake_samples(monkeypatch, tmp_path, fail_on="C5.mp3")
    reply = client.post("/api/soundfonts/acoustic_grand_piano/download")
    assert reply.status_code == 502 and "try again" in reply.json()["detail"]
    folder = tmp_path / "models" / "soundfonts" / "acoustic_grand_piano-mp3"
    assert not list(folder.glob("*.part")) and not (folder / "C5.mp3").exists()
    assert client.get("/api/soundfonts").json()["ready"] is False        # a partial set is not ready
