"""Freeing the engine by hand, from the menu.

The app calls the same thing before a training run; this is the route behind the menu's
Free engine item, which exists to be watched rather than to be used.
"""
import pytest

from app.main import ENGINE


def test_the_route_asks_the_engine_to_free(client, monkeypatch):
    # After the client fixture, not before: starting the app sets the engine offline, and a
    # fixture that ran first would be overwritten by its own start-up.
    monkeypatch.setattr(ENGINE, "online", True)
    asked = []

    async def free():
        asked.append(True)
    monkeypatch.setattr(ENGINE, "free", free)

    assert client.post("/api/engine/free").json() == {"ok": True}
    assert asked == [True]


def test_an_offline_engine_says_so(client, monkeypatch):
    monkeypatch.setattr(ENGINE, "online", False)
    reply = client.post("/api/engine/free")
    assert reply.status_code == 503
    assert "offline" in reply.json()["detail"]
