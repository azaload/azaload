"""Scanner asynchrone qui analyse la watchlist en parallèle.

Chaque actif est analysé via `analyse_asset()` (CPU/IO bloquant) sur un
thread pool ; un sémaphore limite la concurrence pour respecter les rate
limits Binance/Yahoo.
"""

from __future__ import annotations

import asyncio
import time

from bot.logger import get_logger
from config import AssetConfig, Config
from main import analyse_asset

from .broadcaster import BROADCASTER
from .state import AppState

log = get_logger(__name__)


async def _scan_one(asset: AssetConfig, cfg: Config, state: AppState) -> None:
    try:
        signal, pump = await asyncio.to_thread(analyse_asset, asset, cfg)
    except Exception as exc:  # défense en profondeur
        log.exception("Scan KO pour %s", asset.symbol)
        state.add_error(str(exc), symbol=asset.symbol)
        BROADCASTER.broadcast_threadsafe("scan_error", {
            "symbol": asset.symbol,
            "asset_type": asset.asset_type,
            "message": str(exc),
        })
        return

    if signal is None:
        return

    sig_dict = signal.to_dict()
    state.update_signal(asset, sig_dict)
    BROADCASTER.broadcast_threadsafe("signal", {
        **sig_dict,
        "asset_type": asset.asset_type,
        "interval": asset.interval,
    })

    if (
        signal.action != "HOLD"
        and signal.confidence >= cfg.risk.min_confidence_to_alert
    ):
        alert = state.add_alert({
            "kind": "spot",
            "symbol": signal.symbol,
            "name": signal.name,
            "asset_type": asset.asset_type,
            "action": signal.action,
            "confidence": signal.confidence,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "risk_reward": signal.risk_reward,
            "reasons": signal.reasons,
            "timestamp": signal.timestamp.isoformat(),
        })
        BROADCASTER.broadcast_threadsafe("alert", alert)

    if pump is not None:
        pump_dict = pump.to_dict()
        state.update_pump(asset, pump_dict)
        BROADCASTER.broadcast_threadsafe("pump", {
            **pump_dict,
            "asset_type": asset.asset_type,
            "interval": asset.interval,
        })
        if pump.direction != "NONE":
            alert = state.add_alert({
                "kind": "pump_dump",
                "symbol": pump.symbol,
                "name": pump.name,
                "asset_type": asset.asset_type,
                "direction": pump.direction,
                "probability": pump.probability,
                "entry_price": pump.entry_price,
                "stop_loss": pump.stop_loss,
                "take_profit": pump.take_profit,
                "risk_reward": pump.risk_reward,
                "reasons": pump.reasons,
                "timestamp": pump.timestamp.isoformat(),
            })
            BROADCASTER.broadcast_threadsafe("alert", alert)


async def scan_once(cfg: Config, state: AppState, *, concurrency: int = 8) -> None:
    """Lance un cycle d'analyse complet sur la watchlist actuelle."""
    assets = list(state.watchlist)
    if not assets:
        log.info("Watchlist vide, rien à scanner.")
        return

    state.begin_scan()
    started = time.monotonic()
    log.info("Cycle de scan: %d actifs (concurrency=%d)", len(assets), concurrency)

    sem = asyncio.Semaphore(concurrency)

    async def bounded(a: AssetConfig) -> None:
        async with sem:
            await _scan_one(a, cfg, state)

    await asyncio.gather(*(bounded(a) for a in assets), return_exceptions=False)
    duration = time.monotonic() - started
    state.end_scan(duration)
    log.info("Cycle terminé en %.1fs (%d signaux)", duration, len(state.signals_snapshot()))
    BROADCASTER.broadcast_threadsafe("status", state.status())


async def scanner_loop(cfg: Config, state: AppState, *, concurrency: int = 8) -> None:
    """Boucle infinie : scan → sleep → scan → ... ."""
    log.info("Scanner démarré (intervalle=%ds)", cfg.poll_interval_seconds)
    while True:
        try:
            await scan_once(cfg, state, concurrency=concurrency)
        except asyncio.CancelledError:
            log.info("Scanner arrêté.")
            raise
        except Exception as exc:
            log.exception("Scanner: erreur globale: %s", exc)
            state.add_error(f"Scanner global error: {exc}")
        try:
            await asyncio.sleep(cfg.poll_interval_seconds)
        except asyncio.CancelledError:
            raise
