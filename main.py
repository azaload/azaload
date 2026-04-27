"""Point d'entrée du bot d'alerte trading.

Boucle de polling qui, pour chaque actif configuré :
  1. Récupère les données de marché
  2. Calcule les indicateurs techniques
  3. Exécute les stratégies (trend / breakout / mean-reversion)
  4. Récupère un sentiment news (si clé d'API présente)
  5. Combine le tout en un signal BUY/SELL/HOLD avec score de confiance
  6. Émet une alerte si la confiance dépasse le seuil

Usage:
    python main.py
    python main.py --once          # un seul cycle
    python main.py --symbols BTCUSDT,ETHUSDT
    python main.py --min-confidence 70

Disclaimer: cet outil est une AIDE À LA DÉCISION et n'est ni une garantie de
performance, ni un conseil financier. Aucune stratégie ne peut prédire le
marché avec certitude.
"""

from __future__ import annotations

import argparse
import time
from typing import Iterable

from config import CONFIG, AssetConfig, Config
from bot.alerts import (
    dispatch,
    dispatch_pump_dump,
    dump_json,
    format_pump_dump_terminal,
    format_terminal,
)
from bot.data_sources import DataSourceError, fetch_market_data
from bot.indicators import add_indicators
from bot.logger import get_logger
from bot.pump_dump import PumpDumpSignal, detect_pump_dump
from bot.sentiment import fetch_news_sentiment
from bot.signals import Signal, build_signal
from bot.strategies import run_all

log = get_logger("azaload.main")


def analyse_asset(
    asset: AssetConfig, cfg: Config
) -> tuple[Signal | None, PumpDumpSignal | None]:
    """Pipeline complet pour un seul actif.

    Retourne `(signal, pump_dump)` :
      - `signal` est le signal BUY/SELL/HOLD multi-stratégies (None si erreur).
      - `pump_dump` est le signal LONG/SHORT/NONE pour futures (None si erreur).

    Pour les actifs futures, le signal multi-stratégies est aussi calculé
    (utile comme contexte) mais l'attention principale doit aller sur le
    signal pump/dump qui est plus adapté à du trading directionnel rapide.
    """
    try:
        df = fetch_market_data(
            asset.symbol,
            asset.asset_type,
            interval=asset.interval,
            lookback=asset.lookback,
        )
    except DataSourceError as exc:
        log.error("Data fetch failed for %s: %s", asset.symbol, exc)
        return None, None

    try:
        df_ind = add_indicators(df)
    except ValueError as exc:
        log.error("Indicateurs KO pour %s: %s", asset.symbol, exc)
        return None, None

    strategy_results = run_all(df_ind)
    sentiment = fetch_news_sentiment(asset.name, cfg.news_api_key)

    signal = build_signal(
        symbol=asset.symbol,
        name=asset.name,
        df=df_ind,
        strategies=strategy_results,
        sentiment=sentiment,
        weights=cfg.weights,
        risk=cfg.risk,
    )

    pump = detect_pump_dump(
        df_ind,
        symbol=asset.symbol,
        name=asset.name,
        cfg=cfg.pump_dump,
        sl_atr_mult=cfg.risk.sl_atr_multiplier,
        tp_atr_mult=cfg.risk.tp_atr_multiplier,
    )
    return signal, pump


def run_cycle(
    cfg: Config,
    assets: Iterable[AssetConfig],
    *,
    verbose: bool = False,
) -> tuple[list[Signal], list[PumpDumpSignal]]:
    """Un cycle d'analyse sur tous les actifs.

    Pour chaque actif :
      1. Pipeline classique → signal BUY/SELL/HOLD
      2. Détecteur pump/dump → signal LONG/SHORT/NONE (alertes futures)

    Les deux types d'alertes sont indépendants et ont leurs propres seuils.
    """
    signals: list[Signal] = []
    pumps: list[PumpDumpSignal] = []

    for asset in assets:
        log.info("Analyse de %s (%s, %s, %s)",
                 asset.symbol, asset.name, asset.asset_type, asset.interval)
        sig, pump = analyse_asset(asset, cfg)
        if sig is None:
            continue
        signals.append(sig)

        # 1) Pipeline classique
        alert_worthy = (
            sig.action != "HOLD"
            and sig.confidence >= cfg.risk.min_confidence_to_alert
        )
        if alert_worthy:
            dispatch(
                sig,
                telegram_token=cfg.telegram_bot_token,
                telegram_chat=cfg.telegram_chat_id,
                discord_webhook=cfg.discord_webhook_url,
            )
        else:
            log.info(
                "%s: %s @ %.1f%% (sous seuil %.0f%% ou HOLD) — pas d'alerte envoyée",
                sig.symbol, sig.action, sig.confidence, cfg.risk.min_confidence_to_alert,
            )
            if verbose:
                print(format_terminal(sig))

        # 2) Détecteur pump/dump (LONG/SHORT futures)
        if pump is None:
            continue
        pumps.append(pump)
        if pump.direction != "NONE":
            log.warning(
                "⚡ %s pump/dump détecté: %s @ %.1f%% — alerte futures",
                asset.symbol, pump.direction, pump.probability,
            )
            dispatch_pump_dump(
                pump,
                telegram_token=cfg.telegram_bot_token,
                telegram_chat=cfg.telegram_chat_id,
                discord_webhook=cfg.discord_webhook_url,
            )
        else:
            log.info(
                "%s: pump/dump NONE (long=%.0f / short=%.0f, seuil=%.0f%%)",
                asset.symbol,
                pump.metrics.get("long_score", 0.0),
                pump.metrics.get("short_score", 0.0),
                cfg.pump_dump.min_probability,
            )
            if verbose:
                print(format_pump_dump_terminal(pump))

    return signals, pumps


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bot d'alerte trading multi-stratégies")
    p.add_argument("--once", action="store_true", help="Un seul cycle puis sortie")
    p.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Filtre actifs par symboles (séparés par des virgules), ex: BTCUSDT,AAPL",
    )
    p.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Seuil de confiance minimal pour alerter (0-100)",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Intervalle de polling en secondes (override de la config)",
    )
    p.add_argument("--json", action="store_true", help="Affiche aussi le JSON brut des signaux")
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Affiche le détail (raisons, scores) de chaque signal, même HOLD/sous seuil",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = CONFIG

    if args.min_confidence is not None:
        cfg.risk.min_confidence_to_alert = args.min_confidence
    if args.interval is not None:
        cfg.poll_interval_seconds = args.interval

    assets = cfg.assets
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",")}
        assets = [a for a in assets if a.symbol.upper() in wanted]
        if not assets:
            log.error("Aucun actif ne correspond à %s", args.symbols)
            return

    log.info(
        "Démarrage azaload: %d actifs, seuil confiance=%.0f%%, intervalle=%ds",
        len(assets), cfg.risk.min_confidence_to_alert, cfg.poll_interval_seconds,
    )
    log.warning(
        "DISCLAIMER: outil d'aide à la décision. Aucune garantie de précision. "
        "Ne constitue pas un conseil financier."
    )

    cycle = 0
    while True:
        try:
            cycle += 1
            log.info("=== Cycle #%d ===", cycle)
            signals, pumps = run_cycle(cfg, assets, verbose=args.verbose)
            if args.json:
                for s in signals:
                    print(dump_json(s))
                for p in pumps:
                    print(dump_json(p))
            if args.once:
                log.info("Mode --once: sortie après un seul cycle.")
                return
            log.info(
                "Cycle #%d terminé. Prochain cycle dans %ds (Ctrl+C pour arrêter).",
                cycle, cfg.poll_interval_seconds,
            )
            time.sleep(cfg.poll_interval_seconds)
        except KeyboardInterrupt:
            log.info("Arrêt demandé par l'utilisateur.")
            return
        except Exception as exc:  # surveillance globale
            log.exception("Erreur inattendue dans la boucle principale: %s", exc)
            if args.once:
                return
            time.sleep(min(cfg.poll_interval_seconds, 30))


if __name__ == "__main__":
    main()
