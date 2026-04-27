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
from bot.alerts import dispatch, dump_json
from bot.data_sources import DataSourceError, fetch_market_data
from bot.indicators import add_indicators
from bot.logger import get_logger
from bot.sentiment import fetch_news_sentiment
from bot.signals import Signal, build_signal
from bot.strategies import run_all

log = get_logger("azaload.main")


def analyse_asset(asset: AssetConfig, cfg: Config) -> Signal | None:
    """Pipeline complet pour un seul actif. Retourne None si erreur."""
    try:
        df = fetch_market_data(
            asset.symbol,
            asset.asset_type,
            interval=asset.interval,
            lookback=asset.lookback,
        )
    except DataSourceError as exc:
        log.error("Data fetch failed for %s: %s", asset.symbol, exc)
        return None

    try:
        df_ind = add_indicators(df)
    except ValueError as exc:
        log.error("Indicateurs KO pour %s: %s", asset.symbol, exc)
        return None

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
    return signal


def run_cycle(cfg: Config, assets: Iterable[AssetConfig]) -> list[Signal]:
    """Un cycle d'analyse sur tous les actifs."""
    signals: list[Signal] = []
    for asset in assets:
        log.info("Analyse de %s (%s, %s)", asset.symbol, asset.name, asset.interval)
        sig = analyse_asset(asset, cfg)
        if sig is None:
            continue
        signals.append(sig)

        if (
            sig.action != "HOLD"
            and sig.confidence >= cfg.risk.min_confidence_to_alert
        ):
            dispatch(
                sig,
                telegram_token=cfg.telegram_bot_token,
                telegram_chat=cfg.telegram_chat_id,
                discord_webhook=cfg.discord_webhook_url,
            )
        else:
            log.info(
                "%s: %s @ %.1f%% (sous seuil ou HOLD)",
                sig.symbol, sig.action, sig.confidence,
            )
    return signals


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

    while True:
        try:
            signals = run_cycle(cfg, assets)
            if args.json:
                for s in signals:
                    print(dump_json(s))
            if args.once:
                return
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
