import pytest

from zoi_ia.services.context_service import update_context


@pytest.mark.asyncio
async def test_update_context_no_messages():
    store = {"messages": [], "context": "old"}
    await update_context(store)
    assert store == {"messages": [], "context": "old"}


@pytest.mark.asyncio
async def test_update_context_under_threshold(monkeypatch):
    async def fake_summarize(msgs, *_, **__):
        return "SUMMARY"

    # patch summarize used inside the service module
    monkeypatch.setattr("zoi_ia.services.context_service.summarize", fake_summarize)

    store = {"messages": [{"direction": "inbound", "body": "hi"}] * 10, "context": "ctx"}
    await update_context(store, flush_all=False)
    # below threshold: should not change
    assert store["context"] == "ctx"
    assert len(store["messages"]) == 10


@pytest.mark.asyncio
async def test_update_context_flush_all(monkeypatch):
    async def fake_summarize(msgs, *_, **__):
        # ensure previous context is included at the end when present
        assert any(m.get("direction") == "context" for m in msgs)
        return "SUMMARY"

    monkeypatch.setattr("zoi_ia.services.context_service.summarize", fake_summarize)

    store = {"messages": [{"direction": "inbound", "body": "1"}, {"direction": "outbound", "body": "2"}], "context": "prev"}
    await update_context(store, flush_all=True)
    assert store["context"] == "SUMMARY"
    assert store["messages"] == []
