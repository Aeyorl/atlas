"""Unit tests for Real-Time Protocol Event Streamer and API endpoints."""
from __future__ import annotations

import json
from urllib.request import Request, urlopen

import pytest

from api.server import create_server
from api.streamer import EventStreamer


def test_event_streamer_pubsub():
    streamer = EventStreamer(max_history=5)
    sub = streamer.subscribe()

    evt = streamer.publish(
        event_type="TaskCreated",
        data={"task_id": "0x1234", "budget": 10**18},
        chain_id=4663,
    )

    assert evt.event_type == "TaskCreated"
    assert evt.chain_id == 4663
    assert not sub.empty()
    queued = sub.get_nowait()
    assert queued.data["task_id"] == "0x1234"

    sse_str = EventStreamer.format_sse(evt)
    assert "event: TaskCreated" in sse_str
    assert "data: " in sse_str

    recent = streamer.get_recent()
    assert len(recent) == 1
    assert recent[0]["event_type"] == "TaskCreated"

    streamer.unsubscribe(sub)


@pytest.fixture(scope="module")
def api_test_server():
    server = create_server(host="127.0.0.1", port=0, client=None)
    port = server.server_address[1]
    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.shutdown()
    server.server_close()


def test_http_event_endpoints(api_test_server: str):
    # 1. Publish event via POST
    payload = json.dumps({
        "event_type": "BidAccepted",
        "data": {"task_id": "0xabcd", "agent": "0x1111"},
        "chain_id": 4663,
    }).encode("utf-8")

    req = Request(
        f"{api_test_server}/api/v1/events/publish",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req) as res:
        assert res.status == 201
        data = json.loads(res.read().decode("utf-8"))
        assert data["status"] == "published"
        assert data["event"]["event_type"] == "BidAccepted"

    # 2. Get recent events via GET
    with urlopen(f"{api_test_server}/api/v1/events/recent") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert "events" in data
        assert any(e["event_type"] == "BidAccepted" for e in data["events"])

    # 3. Connect to stream endpoint via GET
    with urlopen(f"{api_test_server}/api/v1/events/stream") as res:
        assert res.status == 200
        assert "text/event-stream" in res.headers.get("Content-Type")
        initial = res.read(40).decode("utf-8")
        assert "connected to nive event stream" in initial
