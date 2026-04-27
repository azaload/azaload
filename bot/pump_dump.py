"""Détecteur de pump/dump pour trading futures (long/short).

Distinct du pipeline classique BUY/SELL/HOLD : ce module ne s'allume que
lorsque PLUSIEURS conditions convergent simultanément, pour ne signaler
que des configurations à très haute probabilité de mouvement violent
directionnel.

Critères évalués (chaque critère apporte un nombre de points pondéré) :

  - Volume spike       : volume courant >> moyenne mobile (ratio configurable)
  - Accélération prix  : variation rapide normalisée par l'ATR
  - Breakout / Breakdown : sortie du range des N dernières bougies
  - RSI thrust         : variation rapide du RSI sur quelques bougies
  - Expansion volatilité : largeur Bollinger en forte expansion
  - Confirmation OBV   : flux d'ordres aligné avec la direction
  - Bougie pleine      : corps dominant (pas de mèches contraires)
  - Squeeze préalable  : compression de volatilité avant la cassure (bonus)

Le score total (0-100) doit dépasser un seuil pour qu'un signal LONG ou
SHORT soit émis. Plus on demande de critères, moins on a de signaux mais
plus la probabilité est élevée.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

Direction = Literal["LONG", "SHORT", "NONE"]


@dataclass
class PumpDumpConfig:
    """Paramètres du détecteur."""

    # Pondération de chaque critère (somme libre — ramenée sur 100 dans le score)
    w_volume_spike: float = 22.0
    w_price_acceleration: float = 22.0
    w_range_break: float = 18.0
    w_rsi_thrust: float = 14.0
    w_volatility_expansion: float = 10.0
    w_obv_confirmation: float = 6.0
    w_full_body: float = 5.0
    w_prior_squeeze: float = 3.0

    # Seuils
    volume_spike_ratio: float = 2.5         # volume / SMA20
    price_accel_atr_mult: float = 1.5       # |ret_1| ≥ k × atr/close
    range_lookback: int = 20                # bougies pour breakout/breakdown
    rsi_thrust_delta: float = 10.0          # delta RSI sur 3 bougies
    volatility_expansion: float = 1.30      # bb_width / bb_width_n−3
    full_body_ratio: float = 0.7            # |close-open| / (high-low)
    squeeze_ratio: float = 0.85             # mean(bb_width récent) / mean(bb_width plus ancien)

    # Seuil minimal pour émettre un signal (0-100)
    min_probability: float = 70.0


@dataclass
class PumpDumpSignal:
    symbol: str
    name: str
    direction: Direction
    probability: float                 # 0-100
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    timestamp: datetime
    triggers: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "direction": self.direction,
            "probability": round(self.probability, 1),
            "entry_price": round(self.entry_price, 6),
            "stop_loss": round(self.stop_loss, 6),
            "take_profit": round(self.take_profit, 6),
            "risk_reward": round(self.risk_reward, 2),
            "timestamp": self.timestamp.isoformat(),
            "triggers": self.triggers,
            "metrics": {k: round(v, 6) for k, v in self.metrics.items()},
            "reasons": self.reasons,
        }


def _safe(value: float, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    fvalue = float(value)
    if math.isinf(fvalue):
        return default
    return fvalue


def _candle_body_ratio(row: pd.Series) -> float:
    rng = max(row["high"] - row["low"], 1e-12)
    return abs(row["close"] - row["open"]) / rng


def detect_pump_dump(
    df: pd.DataFrame,
    *,
    symbol: str,
    name: str,
    cfg: PumpDumpConfig | None = None,
    sl_atr_mult: float = 1.0,
    tp_atr_mult: float = 2.5,
) -> PumpDumpSignal:
    """Évalue le DataFrame (déjà enrichi d'indicateurs) et retourne un signal.

    Le DataFrame doit contenir les colonnes ajoutées par
    `bot.indicators.add_indicators` : ema_*, rsi, bb_width, atr, obv,
    volume_sma_20, volume_ratio.
    """
    cfg = cfg or PumpDumpConfig()

    if len(df) < max(cfg.range_lookback + 5, 35):
        return PumpDumpSignal(
            symbol=symbol, name=name, direction="NONE", probability=0.0,
            entry_price=float(df["close"].iloc[-1]), stop_loss=0.0, take_profit=0.0,
            risk_reward=0.0, timestamp=datetime.now(tz=timezone.utc),
            reasons=["Pas assez de bougies pour pump/dump"],
        )

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = _safe(last["close"])
    atr = _safe(last["atr"], close * 0.01)
    atr_pct = atr / close if close > 0 else 0.0

    # Métriques
    ret_1 = (last["close"] - prev["close"]) / prev["close"] if prev["close"] else 0.0
    base_3 = df["close"].iloc[-4] if len(df) >= 4 else prev["close"]
    ret_3 = (last["close"] - base_3) / base_3 if base_3 else 0.0

    high_n = df["high"].iloc[-(cfg.range_lookback + 1):-1].max()
    low_n = df["low"].iloc[-(cfg.range_lookback + 1):-1].min()

    vol_ratio = _safe(last["volume_ratio"], 1.0)

    rsi_now = _safe(last["rsi"], 50.0)
    rsi_then = _safe(df["rsi"].iloc[-4] if len(df) >= 4 else rsi_now, 50.0)
    rsi_delta = rsi_now - rsi_then

    bb_width_now = _safe(last["bb_width"], 0.0)
    bb_width_ref = _safe(df["bb_width"].iloc[-4] if len(df) >= 4 else bb_width_now, bb_width_now)
    bb_expansion = (bb_width_now / bb_width_ref) if bb_width_ref > 1e-9 else 1.0

    body_ratio = _candle_body_ratio(last)

    obv_now = _safe(last["obv"], 0.0)
    obv_then = _safe(df["obv"].iloc[-5] if len(df) >= 5 else obv_now, obv_now)
    obv_delta = obv_now - obv_then

    # Squeeze préalable: la volatilité juste avant a-t-elle été compressée ?
    if len(df) >= 30:
        recent_w = df["bb_width"].iloc[-10:-2].mean()
        older_w = df["bb_width"].iloc[-30:-10].mean()
        prior_squeeze = pd.notna(recent_w) and pd.notna(older_w) and \
            older_w > 0 and (recent_w / older_w) < cfg.squeeze_ratio
    else:
        prior_squeeze = False

    # Critères LONG (pump)
    long_triggers = {
        "volume_spike":         vol_ratio >= cfg.volume_spike_ratio,
        "price_acceleration":   ret_1 >= cfg.price_accel_atr_mult * atr_pct and ret_3 > 0,
        "range_break":          last["close"] > high_n,
        "rsi_thrust":           rsi_delta >= cfg.rsi_thrust_delta,
        "volatility_expansion": bb_expansion >= cfg.volatility_expansion,
        "obv_confirmation":     obv_delta > 0,
        "full_body":            body_ratio >= cfg.full_body_ratio and last["close"] > last["open"],
        "prior_squeeze":        prior_squeeze,
    }

    # Critères SHORT (dump): miroir
    short_triggers = {
        "volume_spike":         vol_ratio >= cfg.volume_spike_ratio,
        "price_acceleration":   ret_1 <= -cfg.price_accel_atr_mult * atr_pct and ret_3 < 0,
        "range_break":          last["close"] < low_n,
        "rsi_thrust":           rsi_delta <= -cfg.rsi_thrust_delta,
        "volatility_expansion": bb_expansion >= cfg.volatility_expansion,
        "obv_confirmation":     obv_delta < 0,
        "full_body":            body_ratio >= cfg.full_body_ratio and last["close"] < last["open"],
        "prior_squeeze":        prior_squeeze,
    }

    weights = {
        "volume_spike":         cfg.w_volume_spike,
        "price_acceleration":   cfg.w_price_acceleration,
        "range_break":          cfg.w_range_break,
        "rsi_thrust":           cfg.w_rsi_thrust,
        "volatility_expansion": cfg.w_volatility_expansion,
        "obv_confirmation":     cfg.w_obv_confirmation,
        "full_body":            cfg.w_full_body,
        "prior_squeeze":        cfg.w_prior_squeeze,
    }
    total_weight = sum(weights.values())

    long_score = sum(weights[k] for k, v in long_triggers.items() if v) / total_weight * 100
    short_score = sum(weights[k] for k, v in short_triggers.items() if v) / total_weight * 100

    # Garde-fous: certains critères sont obligatoires pour pouvoir émettre.
    # Sans volume spike + (price_acceleration OU range_break), on bloque.
    long_eligible = long_triggers["volume_spike"] and (
        long_triggers["price_acceleration"] or long_triggers["range_break"]
    )
    short_eligible = short_triggers["volume_spike"] and (
        short_triggers["price_acceleration"] or short_triggers["range_break"]
    )

    metrics = {
        "ret_1": ret_1,
        "ret_3": ret_3,
        "vol_ratio": vol_ratio,
        "rsi": rsi_now,
        "rsi_delta_3": rsi_delta,
        "bb_expansion": bb_expansion,
        "body_ratio": body_ratio,
        "atr_pct": atr_pct,
        "long_score": long_score,
        "short_score": short_score,
    }

    # Sélection direction
    if long_eligible and long_score >= cfg.min_probability and long_score >= short_score:
        direction: Direction = "LONG"
        triggers = long_triggers
        probability = long_score
    elif short_eligible and short_score >= cfg.min_probability and short_score > long_score:
        direction = "SHORT"
        triggers = short_triggers
        probability = short_score
    else:
        return PumpDumpSignal(
            symbol=symbol, name=name, direction="NONE",
            probability=max(long_score, short_score),
            entry_price=close, stop_loss=0.0, take_profit=0.0, risk_reward=0.0,
            timestamp=datetime.now(tz=timezone.utc),
            triggers={"long": long_triggers, "short": short_triggers},  # type: ignore[dict-item]
            metrics=metrics,
            reasons=[
                f"Pas de convergence suffisante (long={long_score:.0f} / "
                f"short={short_score:.0f}, seuil={cfg.min_probability:.0f})",
            ],
        )

    # Construction du signal final
    if direction == "LONG":
        sl = close - atr * sl_atr_mult
        tp = close + atr * tp_atr_mult
    else:
        sl = close + atr * sl_atr_mult
        tp = close - atr * tp_atr_mult
    risk = abs(close - sl)
    reward = abs(tp - close)
    rr = reward / risk if risk > 0 else 0.0

    reasons = _build_reasons(direction, triggers, metrics, cfg)

    return PumpDumpSignal(
        symbol=symbol, name=name, direction=direction, probability=probability,
        entry_price=close, stop_loss=sl, take_profit=tp, risk_reward=rr,
        timestamp=datetime.now(tz=timezone.utc),
        triggers=triggers, metrics=metrics, reasons=reasons,
    )


def _build_reasons(
    direction: Direction,
    triggers: dict[str, bool],
    metrics: dict[str, float],
    cfg: PumpDumpConfig,
) -> list[str]:
    reasons: list[str] = []
    arrow = "↑" if direction == "LONG" else "↓"
    if triggers.get("volume_spike"):
        reasons.append(f"Volume spike {metrics['vol_ratio']:.2f}× (seuil {cfg.volume_spike_ratio:.1f}×)")
    if triggers.get("price_acceleration"):
        reasons.append(
            f"Accélération prix {arrow} ret_1={metrics['ret_1']*100:+.2f}%, "
            f"ret_3={metrics['ret_3']*100:+.2f}% vs ATR%={metrics['atr_pct']*100:.2f}%"
        )
    if triggers.get("range_break"):
        kind = "Breakout au-dessus" if direction == "LONG" else "Breakdown en-dessous"
        reasons.append(f"{kind} du range des {cfg.range_lookback} dernières bougies")
    if triggers.get("rsi_thrust"):
        reasons.append(f"RSI thrust {arrow} ΔRSI(3)={metrics['rsi_delta_3']:+.1f} (RSI={metrics['rsi']:.1f})")
    if triggers.get("volatility_expansion"):
        reasons.append(f"Expansion de volatilité (BB width ×{metrics['bb_expansion']:.2f})")
    if triggers.get("obv_confirmation"):
        reasons.append(f"Flux OBV aligné {arrow}")
    if triggers.get("full_body"):
        reasons.append(f"Bougie pleine (corps={metrics['body_ratio']*100:.0f}% du range)")
    if triggers.get("prior_squeeze"):
        reasons.append("Compression de volatilité préalable (squeeze)")
    return reasons
