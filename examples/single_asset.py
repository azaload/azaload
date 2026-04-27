"""Exemple: analyse ponctuelle d'un seul actif.

Usage:
    python examples/single_asset.py BTCUSDT crypto
    python examples/single_asset.py AAPL stock
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permet l'exécution depuis la racine ou depuis examples/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CONFIG, AssetConfig  # noqa: E402
from bot.alerts import format_terminal  # noqa: E402
from bot.data_sources import fetch_market_data  # noqa: E402
from bot.indicators import add_indicators  # noqa: E402
from bot.sentiment import fetch_news_sentiment  # noqa: E402
from bot.signals import build_signal  # noqa: E402
from bot.strategies import run_all  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python examples/single_asset.py <SYMBOL> <stock|crypto|commodity>")
        sys.exit(1)

    symbol, asset_type = sys.argv[1], sys.argv[2]
    asset = AssetConfig(symbol=symbol, name=symbol, asset_type=asset_type)

    df = fetch_market_data(asset.symbol, asset.asset_type, asset.interval, asset.lookback)
    df_ind = add_indicators(df)
    strategies = run_all(df_ind)
    sentiment = fetch_news_sentiment(asset.name, CONFIG.news_api_key)

    signal = build_signal(
        symbol=asset.symbol,
        name=asset.name,
        df=df_ind,
        strategies=strategies,
        sentiment=sentiment,
        weights=CONFIG.weights,
        risk=CONFIG.risk,
    )
    print(format_terminal(signal))


if __name__ == "__main__":
    main()
