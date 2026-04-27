"""Module d'analyse de sentiment basé sur les news.

Implémentation volontairement simple : récupère les titres de news liés à un
actif via NewsAPI (clé optionnelle) et calcule un score basé sur un lexique
de mots-clés positifs/négatifs.

Si aucune clé API n'est fournie, retourne un sentiment neutre. Twitter/Reddit
ne sont pas inclus par défaut (rate-limits, complexité d'auth) - placeholders
prévus pour extension.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

from .logger import get_logger

log = get_logger(__name__)


_POSITIVE = {
    "surge", "rally", "gain", "bullish", "soar", "record", "beat", "upgrade",
    "growth", "profit", "boost", "strong", "buy", "outperform", "breakthrough",
    "approval", "partnership", "expand",
}
_NEGATIVE = {
    "plunge", "crash", "fall", "bearish", "drop", "loss", "miss", "downgrade",
    "decline", "weak", "sell", "underperform", "lawsuit", "ban", "fraud",
    "investigation", "warning", "cut",
}


@dataclass
class SentimentResult:
    score: float          # -1.0 (négatif) ... +1.0 (positif)
    confidence: float     # 0.0 ... 1.0  (basé sur volume de news)
    sample_size: int = 0
    reasons: list[str] = field(default_factory=list)


def _score_text(text: str) -> int:
    text = text.lower()
    pos = sum(1 for word in _POSITIVE if word in text)
    neg = sum(1 for word in _NEGATIVE if word in text)
    return pos - neg


def fetch_news_sentiment(query: str, api_key: str | None) -> SentimentResult:
    """Récupère et analyse les dernières news pour un actif via NewsAPI."""
    if not api_key:
        return SentimentResult(0.0, 0.0, 0, ["Sentiment désactivé (pas de clé NEWS_API_KEY)"])

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": 20,
        "apiKey": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
    except requests.RequestException as exc:
        log.warning("NewsAPI échec pour %s: %s", query, exc)
        return SentimentResult(0.0, 0.0, 0, [f"News indisponibles ({exc})"])

    if not articles:
        return SentimentResult(0.0, 0.0, 0, ["Aucune news récente"])

    deltas = []
    for art in articles:
        title = art.get("title") or ""
        desc = art.get("description") or ""
        deltas.append(_score_text(f"{title}. {desc}"))

    raw = sum(deltas)
    n = len(deltas)
    # Normalisation: chaque article peut contribuer ±2 environ avant clamp
    score = max(-1.0, min(1.0, raw / (n * 2)))
    confidence = min(n / 10, 1.0)  # plus de news → plus fiable, plafonné

    reasons = [f"{n} articles analysés, score net = {raw:+d}"]
    if score > 0.1:
        reasons.append("Tonalité globalement positive")
    elif score < -0.1:
        reasons.append("Tonalité globalement négative")
    else:
        reasons.append("Tonalité neutre")
    return SentimentResult(score, confidence, n, reasons)
