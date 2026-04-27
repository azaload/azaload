"""Calcul des indicateurs techniques.

Wrapper léger autour de la bibliothèque `ta`. On garde les colonnes brutes
pour permettre aux stratégies de prendre leurs propres décisions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute toutes les colonnes d'indicateurs nécessaires aux stratégies."""
    if len(df) < 60:
        raise ValueError(f"Pas assez de bougies pour calculer les indicateurs ({len(df)} < 60)")

    out = df.copy()
    close, high, low, volume = out["close"], out["high"], out["low"], out["volume"]

    out["ema_20"] = EMAIndicator(close, window=20).ema_indicator()
    out["ema_50"] = EMAIndicator(close, window=50).ema_indicator()
    out["ema_200"] = EMAIndicator(close, window=200).ema_indicator()

    macd = MACD(close, window_fast=12, window_slow=26, window_sign=9)
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["macd_hist"] = macd.macd_diff()

    out["rsi"] = RSIIndicator(close, window=14).rsi()

    bb = BollingerBands(close, window=20, window_dev=2)
    out["bb_high"] = bb.bollinger_hband()
    out["bb_low"] = bb.bollinger_lband()
    out["bb_mid"] = bb.bollinger_mavg()
    out["bb_width"] = (out["bb_high"] - out["bb_low"]) / out["bb_mid"]

    out["atr"] = AverageTrueRange(high, low, close, window=14).average_true_range()

    out["obv"] = OnBalanceVolumeIndicator(close, volume).on_balance_volume()
    out["volume_sma_20"] = volume.rolling(20).mean()
    out["volume_ratio"] = volume / out["volume_sma_20"].replace(0, np.nan)

    return out
