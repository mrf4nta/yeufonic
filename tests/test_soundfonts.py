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



def test_sf2_soundfonts_discovery_and_selection(client, monkeypatch, tmp_path):
    """Verify available .sf2 soundfonts are listed and can be selected."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    sf2_dir = tmp_path / "models" / "soundfonts" / "sf2"
    sf2_dir.mkdir(parents=True, exist_ok=True)
    (sf2_dir / "Arachno_SoundFont_Version_1.0.sf2").write_bytes(b"RIFFdummy1")
    (sf2_dir / "github_Jnsgm2.sf2").write_bytes(b"RIFFdummy2")

    res = client.get("/api/soundfonts/sf2")
    assert res.status_code == 200
    data = res.json()
    assert len(data["soundfonts"]) == 2
    assert data["selected"] == "Arachno_SoundFont_Version_1.0.sf2"

    sel_res = client.post("/api/soundfonts/sf2/select", json={"filename": "github_Jnsgm2.sf2"})
    assert sel_res.status_code == 200
    assert sel_res.json()["selected"] == "github_Jnsgm2.sf2"

    res2 = client.get("/api/soundfonts/sf2")
    assert res2.json()["selected"] == "github_Jnsgm2.sf2"


def test_midi_rendered_audio_and_peaks(client, monkeypatch, data_dir):
    """Verify MIDI source provides rendered audio and waveform peaks."""
    import io
    from tests.test_midi import create_smf
    from tests.conftest import tone
    from app import library

    sf2_dir = data_dir / "models" / "soundfonts" / "sf2"
    sf2_dir.mkdir(parents=True, exist_ok=True)
    (sf2_dir / "Arachno_SoundFont_Version_1.0.sf2").write_bytes(b"dummy")

    def fake_render(midi_path, output_path, sf2_filename=None, gain=0.8):
        tone(output_path, 1.0)
        library.ensure_peaks(output_path)
        return output_path

    monkeypatch.setattr(soundfonts, "render_midi_to_audio", fake_render)

    events = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),  # 120 bpm
        (0, b"\xFF\x58\x04\x04\x02\x18\x08"),
        (0, bytes([0x90, 60, 80])),
        (480, bytes([0x80, 60, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    midi_data = create_smf([events], division=480, fmt=0)
    upload_res = client.post(
        "/api/sources",
        files={"file": ("mini.mid", io.BytesIO(midi_data), "audio/midi")},
        data={"title": "Mini MIDI"},
    )
    assert upload_res.status_code == 200
    src_id = upload_res.json()["id"]

    # Test rendered-audio
    aud_res = client.get(f"/api/sources/{src_id}/rendered-audio")
    assert aud_res.status_code == 200
    assert aud_res.headers["content-type"] == "audio/flac"

    # Test peaks
    peaks_res = client.get(f"/api/sources/{src_id}/peaks")
    assert peaks_res.status_code == 200
    assert "peaks" in peaks_res.json()
    assert len(peaks_res.json()["peaks"]) > 0

    # Test render-audio trigger
    re_res = client.post(f"/api/sources/{src_id}/render-audio")
    assert re_res.status_code == 200
    assert re_res.json()["status"] == "ok"


def test_score_render_sf2_fallback_and_success(client, monkeypatch, tmp_path):
    """Verify score rendering endpoint falls back gracefully when no SF2 is installed, and succeeds when available."""
    import base64
    from tests.test_midi import create_smf
    from tests.conftest import tone
    from app import library

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "tmp")

    events = [
        (0, b"\xFF\x51\x03\x07\xA1\x20"),
        (0, bytes([0x90, 60, 80])),
        (480, bytes([0x80, 60, 0])),
        (0, b"\xFF\x2F\x00"),
    ]
    b64_midi = base64.b64encode(create_smf([events], division=480, fmt=0)).decode("ascii")

    # 1. No soundfonts installed:
    res = client.get("/api/soundfonts/sf2")
    assert res.status_code == 200
    assert res.json()["available"] is False
    assert res.json()["soundfonts"] == []

    render_unavail = client.post("/api/score/render-sf2", json={"midi_base64": b64_midi})
    assert render_unavail.status_code == 200
    assert render_unavail.json()["status"] == "unavailable"

    # 2. SoundFont installed:
    sf2_dir = tmp_path / "models" / "soundfonts" / "sf2"
    sf2_dir.mkdir(parents=True, exist_ok=True)
    (sf2_dir / "Arachno_SoundFont_Version_1.0.sf2").write_bytes(b"dummy_sf2")

    def fake_render(midi_path, output_path, sf2_filename=None, gain=0.8):
        tone(output_path, 0.5)
        library.ensure_peaks(output_path)
        return output_path

    monkeypatch.setattr(soundfonts, "render_midi_to_audio", fake_render)

    render_ok = client.post("/api/score/render-sf2", json={"midi_base64": b64_midi})
    assert render_ok.status_code == 200
    data = render_ok.json()
    assert data["status"] == "ok"
    assert "audio_url" in data
    assert data["soundfont"] == "Arachno_SoundFont_Version_1.0.sf2"

    key = data["key"]
    aud_res = client.get(f"/api/score/rendered-audio/{key}")
    assert aud_res.status_code == 200
    assert aud_res.headers["content-type"] == "audio/flac"

    peaks_res = client.get(f"/api/score/rendered-audio/{key}/peaks")
    assert peaks_res.status_code == 200
    assert "peaks" in peaks_res.json()



