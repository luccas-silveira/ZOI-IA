from __future__ import annotations

import json
from pathlib import Path

import pytest

from zoi_ia import storage as storage_mod


def test_store_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store_path = tmp_path / "store.json"
    monkeypatch.setattr(storage_mod, "STORE_PATH", store_path)

    store = storage_mod.load_store()
    assert store["contactIds"] == []
    assert "lastUpdate" in store

    store["contactIds"] = ["abc", "def"]
    storage_mod.save_store(store)

    # Read raw file to validate persisted structure
    data = json.loads(store_path.read_text(encoding="utf-8"))
    assert data["contactIds"] == ["abc", "def"]
    assert "lastUpdate" in data


def test_contact_messages_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    messages_dir = tmp_path / "messages"
    monkeypatch.setattr(storage_mod, "MESSAGES_DIR", messages_dir)

    contact_id = "c1"
    msg_store = storage_mod.load_contact_messages(contact_id)
    assert msg_store["messages"] == []
    assert msg_store.get("context") == ""

    msg_store["messages"] = [
        {"direction": "inbound", "body": "Olá"},
        {"direction": "outbound", "body": "Oi!"},
    ]
    storage_mod.save_contact_messages(contact_id, msg_store)

    path = messages_dir / f"{contact_id}.json"
    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert len(on_disk["messages"]) == 2
    assert on_disk.get("context") == ""


def test_location_token_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    loc_path = tmp_path / "location_token.json"
    monkeypatch.setattr(storage_mod, "LOCATION_TOKEN_PATH", loc_path)

    # no file -> None
    assert storage_mod.load_location_token() is None
    token, location = storage_mod.load_location_credentials()
    assert token is None and location is None

    # write file and read again
    loc_path.write_text(json.dumps({"access_token": "tok123", "location_id": "loc1"}), encoding="utf-8")
    assert storage_mod.load_location_token() == "tok123"
    token, location = storage_mod.load_location_credentials()
    assert token == "tok123" and location == "loc1"
