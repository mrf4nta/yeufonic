"""The version check: what it says, and what it must never do.

Every test here is offline.  Both places it would ask are replaced, so the suite is about
what the answers mean rather than whether yeufonic.com is up — and one of the cases below
is that neither answer arrives at all.
"""
import pytest

from app import config, update
from app.db import set_setting

MANIFEST = {
    "latest": "0.0.12",
    "released": "2026-10-02T09:00:00Z",
    "notes": "https://example.invalid/releases/v0.0.12",
    "installer": {"url": "https://example.invalid/Yeufonic-Setup-0.0.12.exe",
                  "sha256": "abc123", "bytes": 612345},
    "docker": "git pull && docker compose up -d --build",
}

RELEASE = {
    "tag_name": "v0.0.12",
    "html_url": "https://example.invalid/releases/tag/v0.0.12",
    "assets": [{"name": "Yeufonic-Setup-0.0.12.exe",
                "browser_download_url": "https://example.invalid/setup.exe",
                "digest": "sha256:deadbeef"}],
}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """A known build, and the state that goes with it.  Pinning the version keeps these
    tests from depending on what VERSION happens to say today: the fixtures name 0.0.12,
    and the day the app really became 0.0.12, four of them started failing for the right
    reason — 0.0.12 is not newer than 0.0.12."""
    monkeypatch.setattr(config, "VERSION", "0.0.10")
    monkeypatch.setattr(update, "STATE", update._initial())


def answering(monkeypatch, manifest=None, release=None):
    """A stand-in for the network: each source answers with what it was given, and one
    that was given nothing is unreachable, which is the offline case as well."""
    def fetch(url):
        source = manifest if url == update.MANIFEST_URL else release
        if source is None:
            raise OSError("no route to host")
        return source
    monkeypatch.setattr(update, "_fetch_json", fetch)


def test_versions_are_compared_as_numbers():
    # The one that bites: as text, '0.0.9' sorts after '0.0.10'.
    assert update.is_newer("0.0.10", "0.0.9") is True
    assert update.is_newer("v0.0.10", "0.0.9") is True
    assert update.is_newer("0.0.9", "0.0.10") is False
    assert update.is_newer("0.0.10", "0.0.10") is False
    assert update.is_newer("0.0.13-beta", "0.0.12") is True
    assert update.is_newer(None, "0.0.10") is False
    assert update.is_newer("nonsense", "0.0.10") is False


@pytest.mark.anyio
async def test_a_newer_manifest_is_news(monkeypatch):
    answering(monkeypatch, manifest=MANIFEST)
    state = await update.check(force=True)
    assert state["newer"] is True
    assert state["latest"] == "0.0.12"
    assert state["installer"] == MANIFEST["installer"]["url"]
    assert state["sha256"] == "abc123"
    assert state["error"] is None
    assert state["checked"] > 0
    assert state["source"] == "yeufonic.com"
    assert state["source_url"] == update.MANIFEST_URL


@pytest.mark.anyio
async def test_the_release_notes_are_the_fallback_when_the_site_is_silent(monkeypatch):
    answering(monkeypatch, release=RELEASE)          # the manifest raises
    state = await update.check(force=True)
    assert state["newer"] is True
    assert state["latest"] == "0.0.12"               # the 'v' comes off the tag
    assert state["installer"] == "https://example.invalid/setup.exe"
    assert state["sha256"] == "sha256:deadbeef"
    assert state["notes"] == RELEASE["html_url"]
    assert state["source"] == "github"
    assert state["source_url"] == update.RELEASE_API


@pytest.mark.anyio
async def test_a_build_ahead_of_the_last_release_says_nothing(monkeypatch):
    # Which is the normal case here: every deploy bumps VERSION, only releases get tagged.
    answering(monkeypatch, manifest={**MANIFEST, "latest": "0.0.1"})
    state = await update.check(force=True)
    assert state["latest"] == "0.0.1"
    assert state["newer"] is False


@pytest.mark.anyio
async def test_offline_is_quiet(monkeypatch):
    answering(monkeypatch)                           # neither source answers
    state = await update.check(force=True)
    assert state["newer"] is False
    assert state["latest"] is None
    assert state["error"]
    assert state["checked"] > 0                      # it will try again tomorrow
    assert update.state()["advice"]                  # and the page still gets an answer


def test_the_gap_between_checks_is_deliberate():
    # Four hours: a release reaches an install the same working session, and six small
    # requests a day to our own static file costs nobody anything.
    assert update.EVERY == 4 * 60 * 60


@pytest.mark.anyio
async def test_the_check_waits_between_times_and_the_manual_one_does_not(monkeypatch):
    asked = []

    def fetch(url):
        asked.append(url)
        return MANIFEST
    monkeypatch.setattr(update, "_fetch_json", fetch)

    await update.check(force=False)                  # the watcher's, first thing
    await update.check(force=False)                  # inside the gap: no request
    assert len(asked) == 1
    await update.check(force=True)                   # the menu's: asks again
    assert len(asked) == 2


@pytest.mark.anyio
async def test_the_setting_stops_the_automatic_check_only(monkeypatch):
    asked = []

    def fetch(url):
        asked.append(url)
        return MANIFEST
    monkeypatch.setattr(update, "_fetch_json", fetch)

    set_setting("app.update_check", "off")
    await update.check(force=False, enabled=False)
    assert asked == []
    await update.check(force=True)                   # Check for updates still asks
    assert len(asked) == 1


@pytest.mark.anyio
async def test_being_told_once_is_enough(monkeypatch, data_dir):
    answering(monkeypatch, manifest=MANIFEST)
    assert (await update.check(force=True))["seen"] is False
    update.mark_seen("0.0.12")
    assert update.state()["seen"] is True
    # A later check of the same release does not raise the notice again.
    assert (await update.check(force=True))["seen"] is True


@pytest.mark.anyio
async def test_the_advice_matches_the_install(monkeypatch):
    answering(monkeypatch, manifest=MANIFEST)
    await update.check(force=True)
    update.STATE["install"] = "windows"
    assert "installer" in update.state()["advice"]
    update.STATE["install"] = "docker"
    assert "git pull" in update.state()["advice"]


@pytest.mark.anyio
async def test_a_restart_remembers_what_it_was_offering(monkeypatch):
    answering(monkeypatch, manifest=MANIFEST)
    await update.check(force=True)
    # A new process: the same answer, without asking again and without losing the link.
    monkeypatch.setattr(update, "STATE", update._initial())
    update.restore()
    state = update.state()
    assert state["latest"] == "0.0.12"
    assert state["newer"] is True
    assert state["installer"] == MANIFEST["installer"]["url"]
    assert state["seen"] is False


def test_the_page_is_given_it_with_the_rest_of_the_state(client):
    body = client.get("/api/state").json()
    info = body["update"]
    assert info["current"] == config.VERSION
    assert info["newer"] is False
    assert info["install"] in ("windows", "docker")
    assert "advice" in info


def test_the_menu_can_ask_whatever_the_setting_says(client, monkeypatch):
    answering(monkeypatch, manifest=MANIFEST)
    set_setting("app.update_check", "off")
    body = client.post("/api/update/check").json()
    assert body["newer"] is True and body["latest"] == "0.0.12"
    # And the daily setting is still off: nothing was asked on its behalf.
    assert client.post("/api/update/seen", json={"version": "0.0.12"}).json()["seen"] is True


def test_the_setting_is_offered_with_a_sensible_default(client):
    spec = [item for item in client.get("/api/state").json()["settings"]
            if item["key"] == "app.update_check"]
    assert spec and spec[0]["default"] == "on"
    assert [option["value"] for option in spec[0]["options"]] == ["on", "off"]
