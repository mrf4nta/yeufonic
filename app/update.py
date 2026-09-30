"""Is there a newer release than this build?

The app asks one small file on its own site — the manifest a release writes — and falls
back to GitHub's release for the same repository, in case the site is down.  A release
procedure that has to remember something is a release procedure that forgets, so this is
deliberately the only place that knows about either.

Nothing here may matter: one request a day, its own timeout, silence when it fails, and
never anything a page request waits on.  A tool that phones home loudly is worse than one
that does not check at all.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import time
from typing import Any

import httpx

from app import config, db

log = logging.getLogger("yue2.update")

# The manifest the site serves: a file in its public/ folder, written when a release is
# cut.  Whatever it says is what the app believes; the release API is only a fallback.
MANIFEST_URL = "https://yeufonic.com/updates.json"
RELEASE_API = "https://api.github.com/repos/yeufonic/yeufonic/releases/latest"
RELEASES_PAGE = "https://github.com/yeufonic/yeufonic/releases/latest"

TIMEOUT = 6.0
EVERY = 24 * 60 * 60          # a day, which is also how often the watcher wakes
USER_AGENT = "Yeufonic/" + config.VERSION + " (+https://yeufonic.com)"

# Where the last answer is kept between restarts.  Not settings: nobody chooses these.
# The whole answer is kept, not just the version, because the notice outlives the process:
# a restart in the evening must not lose the link it was offering in the afternoon.
KEY_CHECKED = "update.checked"
KEY_SEEN = "update.seen"
KEY_ANSWER = "update.answer"

def _initial() -> dict:
    """What we know before asking anything.  A function, so the state can be rebuilt:
    `config.VERSION` and the platform are read when this module is imported, and a test
    that wants a different answer builds its own."""
    return {
        "current": config.VERSION,
        "latest": None,
        "newer": False,
        "checked": 0.0,
        "notes": None,
        "installer": None,
        "sha256": None,
        "install": "windows" if sys.platform == "win32" else "docker",
        "line": None,
        "seen": False,
        "error": None,
        "checking": False,
        "source": None,
    }


# What we know now.  The page reads this; the watcher and the menu item fill it.
STATE: dict[str, Any] = _initial()


def parse_version(text: str | None) -> tuple[int, ...]:
    """`v0.0.11` and `0.0.11` are the same version; a suffix is not part of the order.
    Compared as numbers, never as text: '0.0.9' sorts after '0.0.10' as a string."""
    found = re.match(r"\s*v?(\d+(?:\.\d+)*)", str(text or ""))
    if not found:
        return ()
    return tuple(int(part) for part in found.group(1).split("."))


def is_newer(latest: str | None, mine: str | None = None) -> bool:
    """Whether the release is ahead of what is running.  A build of ours that is *ahead*
    of the last release is the normal case between a deploy and a release, and says
    nothing: only a genuinely newer release is worth telling anyone about."""
    theirs = parse_version(latest)
    ours = parse_version(mine or config.VERSION)
    if not theirs or not ours:
        return False
    return theirs > ours


def _installer_from(assets: list[dict] | None) -> tuple[str | None, str | None]:
    """The setup file and its hash, from a release's assets.  The installer is what a
    Windows user is sent to, so it is worth finding by name; anything else can fall back
    to the release page."""
    for asset in assets or []:
        name = str(asset.get("name") or "")
        if name.lower().startswith("yeufonic-setup") and name.lower().endswith(".exe"):
            return asset.get("browser_download_url"), asset.get("digest") or None
    return None, None


def _from_manifest(data: dict) -> dict:
    installer = data.get("installer") or {}
    if isinstance(installer, str):                    # a plain URL is allowed too
        installer = {"url": installer}
    return {
        "latest": data.get("latest") or data.get("version"),
        "notes": data.get("notes") or data.get("notes_url") or RELEASES_PAGE,
        "installer": installer.get("url"),
        "sha256": installer.get("sha256"),
        "line": data.get("docker"),
    }


def _from_release(data: dict) -> dict:
    installer, digest = _installer_from(data.get("assets"))
    return {
        "latest": str(data.get("tag_name") or "").lstrip("v") or None,
        "notes": data.get("html_url") or RELEASES_PAGE,
        "installer": installer,
        "sha256": digest,
        "line": None,
    }


def _fetch_json(url: str) -> dict:
    """One GET, with the user agent GitHub insists on and the app's own name in it."""
    response = httpx.get(url, timeout=TIMEOUT, follow_redirects=True,
                         headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    response.raise_for_status()
    return response.json()


def _ask() -> dict:
    """The manifest first, GitHub second.  Raises if neither answers.  Which one answered
    is kept, because "is the site's manifest doing its job?" cannot be told from the answer
    alone: the fallback and the manifest can name the same version."""
    first_error: Exception | None = None
    for url, read, source in ((MANIFEST_URL, _from_manifest, "yeufonic.com"),
                              (RELEASE_API, _from_release, "github")):
        try:
            answer = read(_fetch_json(url))
            answer["source"] = source
            return answer
        except Exception as exc:                       # noqa: BLE001 - any failure is the same here
            log.info("Update check: %s did not answer (%s)", url, exc)
            first_error = first_error or exc
    raise first_error or RuntimeError("no update source answered")


def advice() -> str:
    """What to do about it, in the words of the install this is running in."""
    if STATE["install"] == "windows":
        return "Run the installer over this one: your library and models are kept."
    return "Pull the new version and rebuild: " + (STATE["line"] or "git pull && docker compose up -d --build")


def state() -> dict:
    """What the page reads.  No network, nothing to wait for."""
    out = dict(STATE)
    out["line"] = out.get("line") or ("git pull && docker compose up -d --build"
                                      if out["install"] == "docker" else None)
    out["advice"] = advice()
    return out


async def check(force: bool = False, enabled: bool = True) -> dict:
    """Ask, unless it is off or recently asked.  The manual check passes force=True and
    is not subject to the setting, which governs the automatic one only."""
    if not force and not enabled:
        return state()
    if not force and STATE["checked"] and time.time() - STATE["checked"] < EVERY:
        return state()
    STATE["checking"] = True
    try:
        answer = await asyncio.to_thread(_ask)
        STATE.update(answer)
        STATE["latest"] = (answer.get("latest") or "").lstrip("v") or None
        STATE["newer"] = is_newer(STATE["latest"])
        STATE["error"] = None
        STATE["checked"] = time.time()
        db.set_setting(KEY_CHECKED, str(int(STATE["checked"])))
        db.set_setting(KEY_ANSWER, json.dumps({key: STATE[key] for key in
                                               ("latest", "notes", "installer", "sha256", "line", "source")}))
        STATE["seen"] = (db.get_setting(KEY_SEEN) or "") == (STATE["latest"] or "")
        if STATE["newer"]:
            log.info("Version %s is out, this build is %s (from %s)",
                     STATE["latest"], config.VERSION, STATE["source"])
        else:
            log.info("Version check: %s is the latest, this build is %s (from %s)",
                     STATE["latest"] or "unknown", config.VERSION, STATE["source"])
    except Exception as exc:                           # noqa: BLE001 - offline is normal
        STATE["error"] = str(exc) or exc.__class__.__name__
        STATE["checked"] = time.time()
        db.set_setting(KEY_CHECKED, str(int(STATE["checked"])))
        log.info("Version check did not get an answer: %s", STATE["error"])
    finally:
        STATE["checking"] = False
    return state()


def mark_seen(version: str | None = None) -> dict:
    """The notice has been shown and acted on, so it is not shown again for this release."""
    db.set_setting(KEY_SEEN, version or STATE["latest"] or "")
    STATE["seen"] = True
    return state()


def restore() -> None:
    """Pick up where the last run left off: the hour of the last check, and the answer it
    gave, so a restart neither asks again at once nor forgets what it was offering."""
    try:
        STATE["checked"] = float(db.get_setting(KEY_CHECKED) or 0)
    except (TypeError, ValueError):
        STATE["checked"] = 0.0
    try:
        remembered = json.loads(db.get_setting(KEY_ANSWER) or "{}")
    except ValueError:
        remembered = {}
    for key in ("latest", "notes", "installer", "sha256", "line", "source"):
        if key in remembered:
            STATE[key] = remembered[key]
    STATE["latest"] = (STATE["latest"] or "").lstrip("v") or None
    STATE["newer"] = is_newer(STATE["latest"])
    STATE["seen"] = bool(STATE["latest"]) and (db.get_setting(KEY_SEEN) or "") == STATE["latest"]


async def watcher(enabled) -> None:
    """Ask at startup and then daily.  `enabled` is called each time, so the setting can
    be changed without a restart."""
    restore()
    while True:
        try:
            await check(force=False, enabled=bool(enabled()))
        except asyncio.CancelledError:
            raise
        except Exception as exc:                       # noqa: BLE001 - a watcher never dies
            log.warning("Update watcher: %s", exc)
        await asyncio.sleep(EVERY)
