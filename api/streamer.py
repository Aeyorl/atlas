"""Real-time Protocol Event Streamer for Nive Protocol.

Provides a pub/sub event bus and Server-Sent Events (SSE) formatting for
streaming on-chain lifecycle events (TaskCreated, BidAccepted, TaskCompleted,
Settled, BridgeMessageSent) directly to connected frontends on Robinhood Chain Mainnet.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ProtocolEvent:
    event_type: str
    data: dict[str, Any]
    timestamp: float
    chain_id: int = 4663  # Robinhood Chain Mainnet default

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventStreamer:
    """Thread-safe in-memory event broadcaster for protocol lifecycle events."""

    def __init__(self, max_history: int = 50) -> None:
        self.max_history = max_history
        self._history: list[ProtocolEvent] = []
        self._subscribers: set[queue.Queue[ProtocolEvent]] = set()
        self._lock = threading.Lock()

    def publish(self, event_type: str, data: dict[str, Any], chain_id: int = 4663) -> ProtocolEvent:
        event = ProtocolEvent(
            event_type=event_type,
            data=data,
            timestamp=time.time(),
            chain_id=chain_id,
        )
        with self._lock:
            self._history.append(event)
            if len(self._history) > self.max_history:
                self._history.pop(0)

            # Broadcast to all active subscriber queues
            for q in list(self._subscribers):
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass

        return event

    def subscribe(self, maxsize: int = 100) -> queue.Queue[ProtocolEvent]:
        q: queue.Queue[ProtocolEvent] = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[ProtocolEvent]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            events = self._history[-limit:]
            return [e.to_dict() for e in events]

    @staticmethod
    def format_sse(event: ProtocolEvent) -> str:
        """Format event according to W3C Server-Sent Events spec."""
        payload = json.dumps(event.to_dict())
        return f"event: {event.event_type}\ndata: {payload}\n\n"


# Global singleton instance
global_streamer = EventStreamer()
