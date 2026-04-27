"""Stratégies multi-facteurs.

Chaque stratégie analyse les indicateurs et retourne un `StrategyResult`
contenant un score signé entre -1 (forte vente) et +1 (fort achat), une
confiance interne entre 0 et 1, et la liste des raisons.

Les stratégies sont volontairement simples et lisibles : leur force vient
de la combinaison pondérée dans `signals.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class StrategyResult:
    name: str
    score: float           # -1.0 (sell) ... +1.0 (buy)
    confidence: float      # 0.0 ... 1.0  (force du signal)
    reasons: list[str] = field(default_factory=list)


def _last_two(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    return df.iloc[-2], df.iloc[-1]


def trend_following(df: pd.DataFrame) -> StrategyResult:
    """Suivi de tendance: alignement EMA 20/50/200 + confirmation MACD."""
    prev, last = _last_two(df)
    reasons: list[str] = []
    score = 0.0
    weights = 0.0

    # 1. Alignement des EMAs (force de la tendance)
    if last["ema_20"] > last["ema_50"] > last["ema_200"]:
        score += 0.5
        reasons.append("EMAs alignées haussières (20>50>200)")
    elif last["ema_20"] < last["ema_50"] < last["ema_200"]:
        score -= 0.5
        reasons.append("EMAs alignées baissières (20<50<200)")
    weights += 0.5

    # 2. Position du prix vs EMA 50
    diff_pct = (last["close"] - last["ema_50"]) / last["ema_50"]
    score += max(min(diff_pct * 5, 0.2), -0.2)
    weights += 0.2
    if abs(diff_pct) > 0.01:
        direction = "au-dessus" if diff_pct > 0 else "en-dessous"
        reasons.append(f"Prix {direction} de l'EMA50 ({diff_pct*100:+.2f}%)")

    # 3. MACD: histogramme et croisement
    if last["macd"] > last["macd_signal"] and prev["macd"] <= prev["macd_signal"]:
        score += 0.3
        reasons.append("Croisement MACD haussier")
    elif last["macd"] < last["macd_signal"] and prev["macd"] >= prev["macd_signal"]:
        score -= 0.3
        reasons.append("Croisement MACD baissier")
    elif last["macd_hist"] > 0 and last["macd_hist"] > prev["macd_hist"]:
        score += 0.15
        reasons.append("Momentum MACD haussier croissant")
    elif last["macd_hist"] < 0 and last["macd_hist"] < prev["macd_hist"]:
        score -= 0.15
        reasons.append("Momentum MACD baissier croissant")
    weights += 0.3

    score = max(-1.0, min(1.0, score / max(weights, 1e-9)))
    confidence = min(abs(score), 1.0)
    return StrategyResult("trend_following", score, confidence, reasons)


def breakout(df: pd.DataFrame) -> StrategyResult:
    """Breakout: cassure des bandes de Bollinger avec confirmation par le volume."""
    last = df.iloc[-1]
    prev = df.iloc[-2]
    reasons: list[str] = []
    score = 0.0

    width_pct = last["bb_width"]
    width_ma = df["bb_width"].rolling(20).mean().iloc[-1]
    squeeze = width_pct < width_ma * 0.8 if pd.notna(width_ma) else False

    above_high = last["close"] > last["bb_high"]
    below_low = last["close"] < last["bb_low"]
    prev_above = prev["close"] > prev["bb_high"]
    prev_below = prev["close"] < prev["bb_low"]

    vol_ratio = last["volume_ratio"] if pd.notna(last["volume_ratio"]) else 1.0
    volume_ok = vol_ratio >= 1.3

    if above_high and not prev_above:
        score += 0.6
        reasons.append("Cassure haussière de la bande de Bollinger sup.")
        if volume_ok:
            score += 0.3
            reasons.append(f"Volume confirmant ({vol_ratio:.2f}× moyenne)")
    elif below_low and not prev_below:
        score -= 0.6
        reasons.append("Cassure baissière de la bande de Bollinger inf.")
        if volume_ok:
            score -= 0.3
            reasons.append(f"Volume confirmant ({vol_ratio:.2f}× moyenne)")
    elif squeeze:
        reasons.append("Compression de volatilité (squeeze) - attente de cassure")
        score += 0.0  # signal neutre, on attend

    score = max(-1.0, min(1.0, score))
    confidence = min(abs(score), 1.0)
    return StrategyResult("breakout", score, confidence, reasons)


def mean_reversion(df: pd.DataFrame) -> StrategyResult:
    """Mean reversion: RSI extrême + position vs EMA50."""
    last = df.iloc[-1]
    reasons: list[str] = []
    score = 0.0

    rsi = last["rsi"]
    if rsi <= 25:
        score += 0.7
        reasons.append(f"RSI extrêmement survendu ({rsi:.1f})")
    elif rsi <= 35:
        score += 0.35
        reasons.append(f"RSI survendu ({rsi:.1f})")
    elif rsi >= 75:
        score -= 0.7
        reasons.append(f"RSI extrêmement suracheté ({rsi:.1f})")
    elif rsi >= 65:
        score -= 0.35
        reasons.append(f"RSI suracheté ({rsi:.1f})")

    # Distance vs EMA50: rebond probable si fort écart
    if pd.notna(last["ema_50"]):
        dev = (last["close"] - last["ema_50"]) / last["ema_50"]
        if dev < -0.05 and score > 0:
            score += 0.2
            reasons.append(f"Prix très en dessous de l'EMA50 ({dev*100:+.2f}%)")
        elif dev > 0.05 and score < 0:
            score -= 0.2
            reasons.append(f"Prix très au-dessus de l'EMA50 ({dev*100:+.2f}%)")

    # Filtre: ne pas contrer une tendance très forte
    if pd.notna(last["ema_200"]):
        strong_up = last["ema_50"] > last["ema_200"] * 1.05
        strong_down = last["ema_50"] < last["ema_200"] * 0.95
        if score < 0 and strong_up:
            score *= 0.5
            reasons.append("Atténué: tendance de fond haussière forte")
        elif score > 0 and strong_down:
            score *= 0.5
            reasons.append("Atténué: tendance de fond baissière forte")

    score = max(-1.0, min(1.0, score))
    confidence = min(abs(score), 1.0)
    return StrategyResult("mean_reversion", score, confidence, reasons)


def run_all(df: pd.DataFrame) -> list[StrategyResult]:
    """Exécute toutes les stratégies sur un DataFrame déjà enrichi d'indicateurs."""
    return [trend_following(df), breakout(df), mean_reversion(df)]
