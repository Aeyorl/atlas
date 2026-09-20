"""Nive Bridge — Cross-ecosystem message passing."""
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class BridgeMessage:
    message_id: str; source: str; target: str; payload: bytes
    sender: str; delivered: bool = False; created_at: float = field(default_factory=time.time)

class NiveBridge:
    ECOSYSTEMS: frozenset[str] = frozenset({"robinhood-chain", "evm", "virtuals"})
    def __init__(self):
        self._messages: dict[str, BridgeMessage] = {}
    def send_message(self, source: str, target: str, payload: bytes, sender: str) -> BridgeMessage:
        assert source in self.ECOSYSTEMS and target in self.ECOSYSTEMS
        msg = BridgeMessage(message_id=f"bridge-{uuid.uuid4().hex[:16]}", source=source, target=target, payload=payload, sender=sender)
        self._messages[msg.message_id] = msg
        return msg
    def deliver_message(self, message_id: str) -> bool:
        msg = self._messages.get(message_id)
        if not msg or msg.delivered: return False
        msg.delivered = True
        return True
    def get_message(self, message_id: str) -> BridgeMessage | None:
        return self._messages.get(message_id)
