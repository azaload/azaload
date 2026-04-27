"""Diffuseur d'événements en temps réel pour SSE.

Chaque connexion SSE s'inscrit avec une `asyncio.Queue` ; quand le scanner
émet une alerte, on broadcast sur toutes les queues des clients connectés.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class AlertBroadcaster:
    def __init__(self, max_queue_size: int = 100) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._max_queue_size = max_queue_size

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    def broadcast_threadsafe(self, event_type: str, payload: Any) -> None:
        """Appelable depuis un thread non-asyncio (le scanner)."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        loop.call_soon_threadsafe(self._dispatch, event_type, payload)

    def _dispatch(self, event_type: str, payload: Any) -> None:
        message = {"type": event_type, "data": payload}
        # Snapshot pour éviter de muter pendant l'itération
        for q in list(self._subscribers):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # Client trop lent → on le déconnecte silencieusement
                self._subscribers.discard(q)


BROADCASTER = AlertBroadcaster()


def format_sse(message: dict) -> str:
    return f"event: {message['type']}\ndata: {json.dumps(message['data'], ensure_ascii=False)}\n\n"
