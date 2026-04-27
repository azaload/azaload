"""Génération de signaux finaux à partir des stratégies et du sentiment.

Le signal final est BUY/SELL/HOLD avec :
- prix d'entrée recommandé (close courant)
- stop loss et take profit calculés via ATR
- score de confiance 0-100 combinant les sous-scores pondérés
- raisons agrégées pour audit
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

from config import RiskConfig, StrategyWeights
from .sentiment import SentimentResult
from .strategies import StrategyResult

Action = Literal["BUY", "SELL", "HOLD"]


@dataclass
class Signal:
    symbol: str
    name: str
    action: Action
    confidence: float            # 0 ... 100
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    timestamp: datetime
    reasons: list[str] = field(default_factory=list)
    strategy_breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "action": self.action,
            "confidence": round(self.confidence, 1),
            "entry_price": round(self.entry_price, 6),
            "stop_loss": round(self.stop_loss, 6),
            "take_profit": round(self.take_profit, 6),
            "risk_reward": round(self.risk_reward, 2),
            "timestamp": self.timestamp.isoformat(),
            "reasons": self.reasons,
            "strategy_breakdown": {k: round(v, 3) for k, v in self.strategy_breakdown.items()},
        }


def _action_from_score(score: float, hold_threshold: float = 0.15) -> Action:
    if score >= hold_threshold:
        return "BUY"
    if score <= -hold_threshold:
        return "SELL"
    return "HOLD"


def _compute_levels(
    action: Action,
    entry: float,
    atr: float,
    risk_cfg: RiskConfig,
) -> tuple[float, float, float]:
    """Retourne (stop_loss, take_profit, ratio risk/reward)."""
    if action == "BUY":
        sl = entry - atr * risk_cfg.sl_atr_multiplier
        tp = entry + atr * risk_cfg.tp_atr_multiplier
    elif action == "SELL":
        sl = entry + atr * risk_cfg.sl_atr_multiplier
        tp = entry - atr * risk_cfg.tp_atr_multiplier
    else:
        return entry, entry, 0.0

    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0.0
    return sl, tp, rr


def build_signal(
    *,
    symbol: str,
    name: str,
    df: pd.DataFrame,
    strategies: list[StrategyResult],
    sentiment: SentimentResult,
    weights: StrategyWeights,
    risk: RiskConfig,
) -> Signal:
    """Combine les sorties des stratégies et du sentiment en un signal final."""
    last = df.iloc[-1]
    entry = float(last["close"])
    atr = float(last["atr"]) if pd.notna(last["atr"]) else entry * 0.01

    by_name = {s.name: s for s in strategies}
    weighted_score = 0.0
    weighted_conf = 0.0
    breakdown: dict[str, float] = {}

    pairs = [
        ("trend_following", weights.trend_following),
        ("breakout", weights.breakout),
        ("mean_reversion", weights.mean_reversion),
    ]
    for sname, w in pairs:
        s = by_name.get(sname)
        if s is None:
            continue
        weighted_score += s.score * w
        weighted_conf += s.confidence * w
        breakdown[sname] = s.score

    weighted_score += sentiment.score * weights.sentiment
    weighted_conf += sentiment.confidence * weights.sentiment
    breakdown["sentiment"] = sentiment.score

    action = _action_from_score(weighted_score)

    # Confiance: moyenne pondérée des forces, modulée par la concordance
    # entre stratégies (plus elles "votent" dans le même sens, plus on est sûr).
    same_dir = [s for s in strategies if (s.score > 0) == (weighted_score > 0) and abs(s.score) > 0.1]
    agreement = len(same_dir) / max(len(strategies), 1)
    confidence_pct = min(100.0, max(0.0, weighted_conf * 70 + agreement * 30))

    reasons: list[str] = []
    for s in strategies:
        if s.reasons:
            reasons.extend(f"[{s.name}] {r}" for r in s.reasons)
    if sentiment.reasons:
        reasons.extend(f"[sentiment] {r}" for r in sentiment.reasons)

    sl, tp, rr = _compute_levels(action, entry, atr, risk)

    return Signal(
        symbol=symbol,
        name=name,
        action=action,
        confidence=confidence_pct,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        risk_reward=rr,
        timestamp=datetime.now(tz=timezone.utc),
        reasons=reasons,
        strategy_breakdown=breakdown,
    )
