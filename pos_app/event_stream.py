from __future__ import annotations

import threading
from queue import Empty, Full, Queue
from typing import Any, List


class BroadcastChannel:
    """Simple in-memory pub/sub channel for server push events."""

    def __init__(self) -> None:
        self._listeners: List[Queue] = []
        self._lock = threading.Lock()

    def listen(self) -> Queue:
        queue: Queue = Queue(maxsize=10)
        with self._lock:
            self._listeners.append(queue)
        return queue

    def remove(self, queue: Queue) -> None:
        with self._lock:
            if queue in self._listeners:
                self._listeners.remove(queue)

    def publish(self, data: Any) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for queue in listeners:
            try:
                queue.put_nowait(data)
            except Full:
                try:
                    queue.get_nowait()
                except Empty:
                    pass
                try:
                    queue.put_nowait(data)
                except Full:
                    continue


noodle_board_channel = BroadcastChannel()
