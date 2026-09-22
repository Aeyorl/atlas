"""Nive Oracle — Guardian data feed network."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DataFeed:
    name: str; value: Any; timestamp: float = field(default_factory=time.time)
    source: str = ""; ecosystem: str = ""

class NiveOracle:
    def __init__(self):
        self._feeds: dict[str, DataFeed] = {}
    def publish_feed(self, name: str, value: Any, source: str, ecosystem: str) -> DataFeed:
        feed = DataFeed(name=name, value=value, source=source, ecosystem=ecosystem)
        self._feeds[name] = feed
        return feed
    def get_feed(self, name: str) -> DataFeed | None:
        return self._feeds.get(name)
    def get_all_feeds(self) -> list[DataFeed]:
        return list(self._feeds.values())
