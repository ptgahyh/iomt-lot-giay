"""Theo dõi trạng thái từng node: ONLINE / WARNING / DISCONNECTED."""
from __future__ import annotations

import threading
import time
from typing import Callable

from .config import Config

NEVER, ONLINE, WARNING, DISCONNECTED = "NEVER_SEEN", "ONLINE", "WARNING", "DISCONNECTED"


class NodeMonitor:
    def __init__(self, cfg: Config, on_change: Callable[[int, str, str], None],
                 clock: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self.on_change = on_change
        self.clock = clock
        self._last_seen: dict[int, float] = {}
        self._status: dict[int, str] = {n.id: NEVER for n in cfg.nodes}
        self._lock = threading.Lock()

    def seen(self, node_id: int) -> None:
        with self._lock:
            self._last_seen[node_id] = self.clock()
        self._set(node_id, ONLINE)

    def status(self, node_id: int) -> str:
        return self._status.get(node_id, NEVER)

    def snapshot(self) -> dict[int, str]:
        return dict(self._status)

    def tick(self) -> None:
        """Gọi đều đặn (mỗi giây)."""
        now = self.clock()
        for n in self.cfg.nodes:
            with self._lock:
                last = self._last_seen.get(n.id)
            if last is None:
                continue
            age = now - last
            if age > n.period_s * self.cfg.lost_after:
                self._set(n.id, DISCONNECTED)
            elif age > n.period_s * self.cfg.warn_after:
                self._set(n.id, WARNING)

    def _set(self, node_id: int, new: str) -> None:
        with self._lock:
            old = self._status.get(node_id, NEVER)
            if old == new:
                return
            self._status[node_id] = new
        self.on_change(node_id, old, new)
