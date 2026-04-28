"""Configuration centralisée du bot.

Les clés d'API sensibles doivent être définies via variables d'environnement
(ou un fichier .env chargé avec python-dotenv).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from bot.pump_dump import PumpDumpConfig

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


AssetType = Literal["crypto", "futures", "stock", "etf", "commodity", "index", "forex"]


@dataclass
class AssetConfig:
    """Décrit un actif à surveiller."""

    symbol: str
    name: str
    asset_type: AssetType
    interval: str = "1h"
    lookback: int = 300


@dataclass
class StrategyWeights:
    """Pondération des stratégies dans le score final."""

    trend_following: float = 0.40
    breakout: float = 0.30
    mean_reversion: float = 0.20
    sentiment: float = 0.10


@dataclass
class RiskConfig:
    """Paramètres de gestion du risque."""

    atr_period: int = 14
    sl_atr_multiplier: float = 1.5
    tp_atr_multiplier: float = 3.0  # ratio risk/reward = 2
    min_confidence_to_alert: float = 60.0


@dataclass
class Config:
    """Configuration globale."""

    assets: list[AssetConfig] = field(
        default_factory=lambda: [
            AssetConfig("BTCUSDT", "Bitcoin", "crypto", interval="1h"),
            AssetConfig("ETHUSDT", "Ethereum", "crypto", interval="1h"),
            AssetConfig("AAPL", "Apple", "stock", interval="1h"),
            AssetConfig("MSFT", "Microsoft", "stock", interval="1h"),
            AssetConfig("GC=F", "Gold Futures", "commodity", interval="1h"),
            # Futures perpétuels Binance USDT-M (pump/dump = LONG/SHORT)
            AssetConfig("BTCUSDT", "BTC Perp", "futures", interval="15m"),
            AssetConfig("ETHUSDT", "ETH Perp", "futures", interval="15m"),
            AssetConfig("SOLUSDT", "SOL Perp", "futures", interval="15m"),
        ]
    )
    weights: StrategyWeights = field(default_factory=StrategyWeights)
    risk: RiskConfig = field(default_factory=RiskConfig)
    pump_dump: PumpDumpConfig = field(default_factory=PumpDumpConfig)

    poll_interval_seconds: int = 300

    alpha_vantage_api_key: str | None = os.environ.get("ALPHA_VANTAGE_API_KEY")
    news_api_key: str | None = os.environ.get("NEWS_API_KEY")

    telegram_bot_token: str | None = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = os.environ.get("TELEGRAM_CHAT_ID")
    discord_webhook_url: str | None = os.environ.get("DISCORD_WEBHOOK_URL")


CONFIG = Config()
