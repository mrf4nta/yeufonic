"""A take's folder follows its title, and nothing it holds is left behind: a renamed
take once left its file as rendered in the old folder, so Normalise could not be
undone."""
from pathlib import Path

from app import config
from app.db import execute, one
from app.library import normalised_path, original_path, relayout, rendered_path, take_audio_path

from conftest import make_take


def put(path: Path, content: bytes = b"audio") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def folders() -> list[str]:
    return sorted(p.name for p in config.TAKES_DIR.iterdir() if p.is_dir())


def test_a_renamed_normalised_take_takes_its_file_as_rendered_along(client):
    take = make_take(title="Night drive")
    rendered = put(take_audio_path(take["id"], "Night drive"), b"as rendered")
    louder = put(normalised_path(rendered), b"louder")
    put(rendered.with_name("night-drive.peaks.json"), b"{}")
    put(rendered.parent / "take.json", b"{}")
    execute("UPDATE takes SET audio_path = ?, normalised = 1, title = 'Coast road' WHERE id = ?", (str(louder), take["id"]))

    relayout()

    now = Path(one("SELECT audio_path FROM takes WHERE id = ?", (take["id"],))["audio_path"])
    assert now == normalised_path(take_audio_path(take["id"], "Coast road")) and now.read_bytes() == b"louder"
    assert rendered_path(now).read_bytes() == b"as rendered", "Normalise can still be undone"
    assert folders() == [f"coast-road-{take['id']}"], "the old folder is gone"


def test_a_file_as_rendered_left_behind_by_an_earlier_rename_is_put_back(client):
    take = make_take(title="Coast road")
    louder = put(normalised_path(take_audio_path(take["id"], "Coast road")), b"louder")
    execute("UPDATE takes SET audio_path = ?, normalised = 1 WHERE id = ?", (str(louder), take["id"]))
    old = config.TAKES_DIR / f"night-drive-{take['id']}"
    put(old / "night-drive.flac", b"as rendered")
    put(old / "night-drive.normalised.peaks.json", b"{}")
    put(old / "take.json", b"{}")

    relayout()

    assert rendered_path(louder).read_bytes() == b"as rendered"
    assert not old.exists()


def test_a_take_normalised_in_place_gets_its_original_back_and_the_present_layout(client):
    """The first version of normalising made song.flac louder and kept song.original.flac
    as rendered.  A rename left the original behind; put back, the take is converted."""
    take = make_take(title="Lantern good")
    louder = put(take_audio_path(take["id"], "Lantern good"), b"louder")
    execute("UPDATE takes SET audio_path = ?, normalised = 1 WHERE id = ?", (str(louder), take["id"]))
    old = config.TAKES_DIR / f"lantern-{take['id']}"
    put(old / "lantern.original.flac", b"as rendered")
    put(old / "lantern.peaks.json", b"{}")

    relayout()

    now = Path(one("SELECT audio_path FROM takes WHERE id = ?", (take["id"],))["audio_path"])
    assert now == normalised_path(louder) and now.read_bytes() == b"louder"
    assert louder.read_bytes() == b"as rendered" and not original_path(louder).exists()
    assert not old.exists()


def test_old_folders_lose_only_what_is_made_again(client):
    """A deleted take's folder of waveforms goes.  Audio with no take to go to stays,
    and so does a folder holding two candidates, where it is not clear which to put back."""
    gone = config.TAKES_DIR / "old-take-0123456789ab"
    put(gone / "old-take.peaks.json", b"{}")
    put(gone / "take.json", b"{}")
    orphan = config.TAKES_DIR / "lost-take-ba9876543210"
    put(orphan / "lost-take.flac")
    put(orphan / "lost-take.peaks.json", b"{}")
    take = make_take(title="Two")
    louder = put(normalised_path(take_audio_path(take["id"], "Two")), b"louder")
    execute("UPDATE takes SET audio_path = ?, normalised = 1 WHERE id = ?", (str(louder), take["id"]))
    unclear = config.TAKES_DIR / f"one-{take['id']}"
    put(unclear / "one.flac")
    put(unclear / "one-b.flac")
    elsewhere = put(config.TAKES_DIR / "notes" / "keep.txt", b"mine")

    relayout()

    assert not gone.exists()
    assert (orphan / "lost-take.flac").exists() and not (orphan / "lost-take.peaks.json").exists()
    assert (unclear / "one.flac").exists() and (unclear / "one-b.flac").exists()
    assert not rendered_path(louder).exists()
    assert elsewhere.exists(), "a folder that is not a take's is not touched"
