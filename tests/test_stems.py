from app.stems import Progress


def run(passes, sequence):
    parser = Progress(passes)
    return [step for step in (parser.feed(p) for p in sequence) if step]


def test_a_bag_of_four_models_rises_steadily_through_writing():
    # What htdemucs_ft printed for a 20 second take, writing two MP3 stems.
    printed = [6, 21, 66, 90, 5, 39, 84, 0, 33, 92, 9, 49, 99, 25, 50, 75, 100, 25, 50, 75, 100]
    steps = run(4, printed)
    figures = [frac for frac, _ in steps]
    assert figures == sorted(figures), figures
    assert steps[4][1] == "Separating (model 2 of 4)"
    assert steps[-1] == (0.96, "Writing the stems")


def test_a_single_model():
    steps = run(1, [0, 50, 100])
    assert steps[1] == (0.5, "Separating")
    assert steps[-1] == (0.95, "Separating")


def test_asking_for_stems_is_answered_for_a_take_and_a_recording(client, tmp_path):
    """The request queues the job and says so.  A log line after the queueing once
    named a field the request does not have, and every request came back as an error
    although the stems were made."""
    from app.db import execute
    from app.jobs import STEM_QUEUE
    from conftest import make_take, tone

    audio = tone(tmp_path / "take.flac", 1.0)
    take = make_take(audio_path=str(audio))
    execute("""INSERT INTO sources(id, title, filename, stored_path, sha256, created_at)
               VALUES('src1', 'Song', 'song.flac', ?, 'abc', 1.0)""", (str(audio),))
    try:
        for url in (f"/api/takes/{take['id']}/stems", "/api/sources/src1/stems"):
            answer = client.post(url, json={"model": "htdemucs", "stems": ["vocals"]})
            assert answer.status_code == 200, answer.text
            assert answer.json()["id"]
    finally:
        while not STEM_QUEUE.empty():
            STEM_QUEUE.get_nowait()


def fake_demucs(tmp_path, monkeypatch):
    """A demucs that writes what the real one would, and notes what it was asked."""
    import os
    import stat

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "demucs"
    script.write_text("""#!/bin/sh
printf '%s\n' "$*" > "$DEMUCS_ARGS"
out=""; model=""; two=""; ext="wav"
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift ;;
    -n) model="$2"; shift ;;
    --two-stems) two="$2"; shift ;;
    --flac) ext="flac" ;;
  esac
  shift
done
mkdir -p "$out/$model/clip"
if [ -n "$two" ]; then names="$two no_$two"; else names="vocals drums bass other"; fi
for name in $names; do echo x > "$out/$model/clip/$name.$ext"; done
echo "100%|"
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("DEMUCS_ARGS", str(tmp_path / "args.txt"))
    return tmp_path / "args.txt"


def test_vocals_and_instruments_is_demucs_two_stem_split(tmp_path, monkeypatch):
    """The two-stem entries run the named model with --two-stems vocals, and the
    everything-but-the-vocal stem demucs calls no_vocals is kept as instruments."""
    import asyncio
    from pathlib import Path

    from app import stems

    args = fake_demucs(tmp_path, monkeypatch)
    src = tmp_path / "clip.flac"
    src.write_bytes(b"x")

    got = asyncio.run(stems.separate(src, tmp_path / "out", "htdemucs_ft_2s", ["instruments"], "flac",
                                     work_root=tmp_path / "work"))
    asked = args.read_text().split()
    assert asked[asked.index("-n") + 1] == "htdemucs_ft"
    assert asked[asked.index("--two-stems") + 1] == "vocals"
    assert got["stems"] == {"instruments": str(tmp_path / "out" / "instruments.flac")}
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["instruments.flac"], "an unticked vocal is not kept"

    both = asyncio.run(stems.separate(src, tmp_path / "both", "htdemucs_2s", ["vocals", "instruments"], "wav",
                                      work_root=tmp_path / "work"))
    assert sorted(Path(p).name for p in both["stems"].values()) == ["instruments.wav", "vocals.wav"]

    asyncio.run(stems.separate(src, tmp_path / "four", "htdemucs", ["drums"], "wav", work_root=tmp_path / "work"))
    asked = args.read_text().split()
    assert "--two-stems" not in asked and asked[asked.index("-n") + 1] == "htdemucs"


def test_instruments_only_comes_from_a_two_stem_model(client, tmp_path):
    """A four-stem model has no instruments stem, so asking one for it gets its own
    stems; a two-stem model keeps just what was ticked."""
    from app.db import execute
    from app.jobs import STEM_QUEUE
    from conftest import tone

    audio = tone(tmp_path / "song.flac", 1.0)
    execute("""INSERT INTO sources(id, title, filename, stored_path, sha256, created_at)
               VALUES('src1', 'Song', 'song.flac', ?, 'abc', 1.0)""", (str(audio),))
    try:
        two = client.post("/api/sources/src1/stems", json={"model": "htdemucs_2s", "stems": ["instruments"]}).json()
        assert (two["model"], two["stems"]) == ("htdemucs_2s", ["instruments"])
        four = client.post("/api/sources/src1/stems", json={"model": "htdemucs", "stems": ["instruments"]}).json()
        assert four["stems"] == ["vocals", "drums", "bass", "other"]
        offered = {m["id"]: m["stems"] for m in client.get("/api/stems/options").json()["models"]}
        assert offered["htdemucs_2s"] == offered["htdemucs_ft_2s"] == ["vocals", "instruments"]
    finally:
        while not STEM_QUEUE.empty():
            STEM_QUEUE.get_nowait()
