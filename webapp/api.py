"""API web (FastAPI) + frontend statique.

Endpoints REST :
  GET  /                       -> SPA (index.html)
  GET  /api/status             -> état global du scanner
  GET  /api/catalog            -> catalogue d'actifs (search + filtres)
  GET  /api/catalog/stats      -> compteurs par type
  GET  /api/watchlist          -> watchlist active
  POST /api/watchlist          -> ajouter un actif
  DELETE /api/watchlist/{type}/{symbol} -> retirer un actif
  GET  /api/signals            -> tous les signaux courants
  GET  /api/pumps              -> tous les signaux pump/dump courants
  GET  /api/alerts             -> historique des alertes
  POST /api/scan               -> déclenche un cycle immédiat
  GET  /api/config             -> config actuelle (seuils)
  POST /api/config             -> modifier les seuils
  GET  /api/stream             -> SSE (alerts, signals, status)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from bot import catalog
from bot.logger import get_logger
from config import CONFIG, AssetConfig

from .broadcaster import BROADCASTER, format_sse
from .scanner import scan_once, scanner_loop
from .state import STATE

log = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Charge la watchlist persistée (ou défaut depuis config.assets)
    STATE.load_watchlist(CONFIG.assets)
    log.info("Lifespan startup: watchlist=%d, config interval=%ds",
             len(STATE.watchlist), CONFIG.poll_interval_seconds)

    # Lance le scanner en tâche de fond
    task = asyncio.create_task(scanner_loop(CONFIG, STATE))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="azaload trading dashboard", lifespan=lifespan)


# --------------------------------------------------------------------------
# Frontend statique
# --------------------------------------------------------------------------

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------

@app.get("/api/catalog")
async def get_catalog(
    q: str | None = Query(default=None, description="Recherche libre (symbole/nom)"),
    asset_type: str | None = Query(default=None, alias="type"),
    tag: str | None = None,
    min_volume: float | None = Query(default=None, alias="minVolume"),
    limit: int = Query(default=200, le=1000),
):
    entries = await asyncio.to_thread(
        catalog.search,
        query=q, asset_type=asset_type, tag=tag, min_volume=min_volume, limit=limit,
    )
    return {"entries": [e.to_dict() for e in entries], "count": len(entries)}


@app.get("/api/catalog/stats")
async def get_catalog_stats():
    return await asyncio.to_thread(catalog.stats)


# --------------------------------------------------------------------------
# Watchlist
# --------------------------------------------------------------------------

@app.get("/api/watchlist")
async def get_watchlist():
    return {"watchlist": STATE.watchlist_snapshot()}


@app.post("/api/watchlist")
async def add_watchlist(asset: dict = Body(...)):
    required = {"symbol", "name", "asset_type"}
    missing = required - asset.keys()
    if missing:
        raise HTTPException(400, f"Champs manquants: {sorted(missing)}")

    cfg = AssetConfig(
        symbol=asset["symbol"].strip().upper(),
        name=asset.get("name") or asset["symbol"],
        asset_type=asset["asset_type"],
        interval=asset.get("interval", "1h"),
        lookback=int(asset.get("lookback", 300)),
    )
    added = STATE.add_to_watchlist(cfg)
    BROADCASTER.broadcast_threadsafe("watchlist", STATE.watchlist_snapshot())
    return {"added": added, "watchlist": STATE.watchlist_snapshot()}


@app.delete("/api/watchlist/{asset_type}/{symbol}")
async def remove_watchlist(asset_type: str, symbol: str):
    removed = STATE.remove_from_watchlist(symbol.upper(), asset_type)
    BROADCASTER.broadcast_threadsafe("watchlist", STATE.watchlist_snapshot())
    return {"removed": removed, "watchlist": STATE.watchlist_snapshot()}


# --------------------------------------------------------------------------
# Signaux / pumps / alertes
# --------------------------------------------------------------------------

@app.get("/api/signals")
async def get_signals():
    return {"signals": STATE.signals_snapshot()}


@app.get("/api/pumps")
async def get_pumps():
    return {"pumps": STATE.pumps_snapshot()}


@app.get("/api/alerts")
async def get_alerts(limit: int = Query(default=100, le=500)):
    return {"alerts": STATE.alerts_snapshot()[:limit]}


@app.get("/api/status")
async def get_status():
    return {
        **STATE.status(),
        "config": {
            "poll_interval_seconds": CONFIG.poll_interval_seconds,
            "min_confidence_to_alert": CONFIG.risk.min_confidence_to_alert,
            "pump_min_probability": CONFIG.pump_dump.min_probability,
            "volume_spike_ratio": CONFIG.pump_dump.volume_spike_ratio,
            "price_accel_atr_mult": CONFIG.pump_dump.price_accel_atr_mult,
        },
    }


# --------------------------------------------------------------------------
# Config (seuils éditables à chaud)
# --------------------------------------------------------------------------

@app.get("/api/config")
async def get_config():
    return {
        "poll_interval_seconds": CONFIG.poll_interval_seconds,
        "risk": {
            "min_confidence_to_alert": CONFIG.risk.min_confidence_to_alert,
            "sl_atr_multiplier": CONFIG.risk.sl_atr_multiplier,
            "tp_atr_multiplier": CONFIG.risk.tp_atr_multiplier,
        },
        "pump_dump": {
            "min_probability": CONFIG.pump_dump.min_probability,
            "volume_spike_ratio": CONFIG.pump_dump.volume_spike_ratio,
            "price_accel_atr_mult": CONFIG.pump_dump.price_accel_atr_mult,
            "rsi_thrust_delta": CONFIG.pump_dump.rsi_thrust_delta,
            "volatility_expansion": CONFIG.pump_dump.volatility_expansion,
        },
    }


@app.post("/api/config")
async def update_config(payload: dict = Body(...)):
    if "poll_interval_seconds" in payload:
        CONFIG.poll_interval_seconds = max(15, int(payload["poll_interval_seconds"]))
    risk = payload.get("risk") or {}
    if "min_confidence_to_alert" in risk:
        CONFIG.risk.min_confidence_to_alert = float(risk["min_confidence_to_alert"])
    if "sl_atr_multiplier" in risk:
        CONFIG.risk.sl_atr_multiplier = float(risk["sl_atr_multiplier"])
    if "tp_atr_multiplier" in risk:
        CONFIG.risk.tp_atr_multiplier = float(risk["tp_atr_multiplier"])
    pd_cfg = payload.get("pump_dump") or {}
    for key in (
        "min_probability", "volume_spike_ratio", "price_accel_atr_mult",
        "rsi_thrust_delta", "volatility_expansion",
    ):
        if key in pd_cfg:
            setattr(CONFIG.pump_dump, key, float(pd_cfg[key]))
    BROADCASTER.broadcast_threadsafe("config", await get_config())
    return await get_config()


# --------------------------------------------------------------------------
# Scan immédiat
# --------------------------------------------------------------------------

@app.post("/api/scan")
async def trigger_scan():
    if STATE.is_scanning:
        return JSONResponse({"started": False, "reason": "déjà en cours"}, status_code=409)
    asyncio.create_task(scan_once(CONFIG, STATE))
    return {"started": True}


# --------------------------------------------------------------------------
# Stream SSE (alerts + signals + status)
# --------------------------------------------------------------------------

@app.get("/api/stream")
async def stream(request: Request):
    queue = await BROADCASTER.subscribe()

    async def event_gen():
        # Initial snapshot pour synchroniser le client
        yield format_sse({"type": "status", "data": STATE.status()})
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield format_sse(msg)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # commentaire SSE pour keepalive
        finally:
            await BROADCASTER.unsubscribe(queue)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)
