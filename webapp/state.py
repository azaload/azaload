"""État en mémoire partagé entre le scanner et l'API web.

Tout est protégé par un RLock car le scanner tourne dans un thread pool
(pandas/yfinance étant bloquants) tandis que l'API FastAPI tourne dans
l'event loop asyncio.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from bot.logger import get_logger
from config import AssetConfig

log = get_logger(__name__)

WATCHLIST_FILE = Path("data/watchlist.json")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class AppState:
    """Store thread-safe pour la web app."""

    def __init__(self, *, max_alerts: int = 200, max_errors: int = 50) -> None:
        self._lock = RLock()
        self.signals: dict[str, dict] = {}     # key = f"{asset_type}:{symbol}"
        self.pumps: dict[str, dict] = {}
        self.alerts: deque[dict] = deque(maxlen=max_alerts)
        self.errors: deque[dict] = deque(maxlen=max_errors)

        self.watchlist: list[AssetConfig] = []
        self.last_scan_started: str | None = None
        self.last_scan_finished: str | None = None
        self.last_scan_duration_s: float | None = None
        self.scan_count: int = 0
        self.is_scanning: bool = False

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------

    @staticmethod
    def _key(asset_type: str, symbol: str) -> str:
        return f"{asset_type}:{symbol.upper()}"

    def add_to_watchlist(self, asset: AssetConfig) -> bool:
        with self._lock:
            for existing in self.watchlist:
                if existing.symbol == asset.symbol and existing.asset_type == asset.asset_type:
                    return False
            self.watchlist.append(asset)
            self._persist_watchlist_locked()
            return True

    def add_many_to_watchlist(self, assets: list[AssetConfig]) -> int:
        """Ajoute plusieurs actifs en une fois, en dédupliquant. Retourne le nombre ajouté."""
        with self._lock:
            existing_keys = {(a.symbol, a.asset_type) for a in self.watchlist}
            added = 0
            for a in assets:
                key = (a.symbol, a.asset_type)
                if key in existing_keys:
                    continue
                existing_keys.add(key)
                self.watchlist.append(a)
                added += 1
            if added:
                self._persist_watchlist_locked()
            return added

    def remove_from_watchlist(self, symbol: str, asset_type: str) -> bool:
        with self._lock:
            before = len(self.watchlist)
            self.watchlist = [
                a for a in self.watchlist
                if not (a.symbol == symbol and a.asset_type == asset_type)
            ]
            removed = len(self.watchlist) != before
            if removed:
                key = self._key(asset_type, symbol)
                self.signals.pop(key, None)
                self.pumps.pop(key, None)
                self._persist_watchlist_locked()
            return removed

    def remove_many_from_watchlist(self, items: list[tuple[str, str]]) -> int:
        """Retire plusieurs actifs (chaque item: (symbol, asset_type)). Retourne le nombre retiré."""
        targets = {(s.upper(), t) for s, t in items}
        with self._lock:
            before = len(self.watchlist)
            kept = []
            for a in self.watchlist:
                if (a.symbol.upper(), a.asset_type) in targets:
                    self.signals.pop(self._key(a.asset_type, a.symbol), None)
                    self.pumps.pop(self._key(a.asset_type, a.symbol), None)
                    continue
                kept.append(a)
            self.watchlist = kept
            removed = before - len(self.watchlist)
            if removed:
                self._persist_watchlist_locked()
            return removed

    def clear_watchlist(self) -> int:
        with self._lock:
            count = len(self.watchlist)
            self.watchlist = []
            self.signals.clear()
            self.pumps.clear()
            self._persist_watchlist_locked()
            return count

    def watchlist_snapshot(self) -> list[dict]:
        with self._lock:
            return [asdict(a) for a in self.watchlist]

    def load_watchlist(self, default: list[AssetConfig]) -> None:
        with self._lock:
            if WATCHLIST_FILE.exists():
                try:
                    data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
                    self.watchlist = [AssetConfig(**item) for item in data]
                    log.info("Watchlist chargée: %d actifs", len(self.watchlist))
                    return
                except Exception as exc:
                    log.warning("Watchlist illisible (%s), utilisation du défaut", exc)
            self.watchlist = list(default)
            self._persist_watchlist_locked()

    def _persist_watchlist_locked(self) -> None:
        WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        WATCHLIST_FILE.write_text(
            json.dumps([asdict(a) for a in self.watchlist], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Scan / signaux
    # ------------------------------------------------------------------

    def begin_scan(self) -> None:
        with self._lock:
            self.is_scanning = True
            self.last_scan_started = _now_iso()

    def end_scan(self, duration_s: float) -> None:
        with self._lock:
            self.is_scanning = False
            self.last_scan_finished = _now_iso()
            self.last_scan_duration_s = duration_s
            self.scan_count += 1

    def update_signal(self, asset: AssetConfig, signal_dict: dict) -> None:
        with self._lock:
            self.signals[self._key(asset.asset_type, asset.symbol)] = {
                **signal_dict,
                "asset_type": asset.asset_type,
                "interval": asset.interval,
            }

    def update_pump(self, asset: AssetConfig, pump_dict: dict) -> None:
        with self._lock:
            self.pumps[self._key(asset.asset_type, asset.symbol)] = {
                **pump_dict,
                "asset_type": asset.asset_type,
                "interval": asset.interval,
            }

    def add_alert(self, alert: dict) -> dict:
        """Ajoute une alerte horodatée et retourne l'objet complet."""
        with self._lock:
            payload = {**alert, "added_at": _now_iso()}
            self.alerts.appendleft(payload)
            return payload

    def add_error(self, message: str, *, symbol: str | None = None) -> None:
        with self._lock:
            self.errors.appendleft({
                "at": _now_iso(),
                "symbol": symbol,
                "message": message,
            })

    def signals_snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.signals.values())

    def pumps_snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.pumps.values())

    def alerts_snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.alerts)

    def errors_snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.errors)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "is_scanning": self.is_scanning,
                "scan_count": self.scan_count,
                "last_scan_started": self.last_scan_started,
                "last_scan_finished": self.last_scan_finished,
                "last_scan_duration_s": self.last_scan_duration_s,
                "watchlist_size": len(self.watchlist),
                "signals_count": len(self.signals),
                "alerts_count": len(self.alerts),
            }


STATE = AppState()
