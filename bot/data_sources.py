"""Collecte de données de marché depuis plusieurs sources fiables.

Sources supportées :
- Binance (REST publique, sans clé) pour les cryptos
- Yahoo Finance via yfinance pour actions et matières premières
- Alpha Vantage en option (clé d'API requise)

Toutes les fonctions retournent un DataFrame pandas avec colonnes normalisées :
['open', 'high', 'low', 'close', 'volume'] indexé par timestamp UTC.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import requests

from .logger import get_logger

log = get_logger(__name__)


_BINANCE_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d",
}

_YF_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "60m", "4h": "60m", "1d": "1d",
}

_REQUIRED_COLS = ["open", "high", "low", "close", "volume"]


class DataSourceError(RuntimeError):
    """Erreur générique remontée par cette couche."""


def _validate(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    missing = [c for c in _REQUIRED_COLS if c not in df.columns]
    if missing:
        raise DataSourceError(f"{symbol}: colonnes manquantes {missing}")
    df = df.dropna(subset=_REQUIRED_COLS)
    if df.empty:
        raise DataSourceError(f"{symbol}: dataframe vide après nettoyage")
    return df[_REQUIRED_COLS].astype(float)


def _fetch_binance_klines(base_url: str, symbol: str, interval: str, limit: int) -> pd.DataFrame:
    if interval not in _BINANCE_INTERVAL_MAP:
        raise DataSourceError(f"Intervalle Binance non supporté: {interval}")

    params = {"symbol": symbol.upper(), "interval": interval, "limit": min(limit, 1000)}
    try:
        resp = requests.get(base_url, params=params, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise DataSourceError(f"Binance HTTP error pour {symbol}: {exc}") from exc

    data = resp.json()
    if not isinstance(data, list) or not data:
        raise DataSourceError(f"Binance réponse inattendue pour {symbol}: {data!r}")

    df = pd.DataFrame(
        data,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ],
    )
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    return _validate(df, symbol)


def fetch_binance(symbol: str, interval: str = "1h", limit: int = 300) -> pd.DataFrame:
    """Récupère les klines depuis Binance Spot (endpoint public, pas de clé)."""
    return _fetch_binance_klines(
        "https://api.binance.com/api/v3/klines", symbol, interval, limit
    )


def fetch_binance_futures(symbol: str, interval: str = "1h", limit: int = 300) -> pd.DataFrame:
    """Récupère les klines depuis Binance USDT-M Futures (perpetuals)."""
    return _fetch_binance_klines(
        "https://fapi.binance.com/fapi/v1/klines", symbol, interval, limit
    )


def fetch_yfinance(symbol: str, interval: str = "1h", lookback: int = 300) -> pd.DataFrame:
    """Récupère les données via yfinance (actions, ETF, matières premières)."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise DataSourceError("yfinance non installé. `pip install yfinance`.") from exc

    if interval not in _YF_INTERVAL_MAP:
        raise DataSourceError(f"Intervalle Yahoo non supporté: {interval}")

    yf_interval = _YF_INTERVAL_MAP[interval]
    period = _yf_period_for_lookback(yf_interval, lookback)

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=yf_interval, auto_adjust=False)
    except Exception as exc:  # yfinance lève divers types
        raise DataSourceError(f"Yahoo Finance error pour {symbol}: {exc}") from exc

    if df.empty:
        raise DataSourceError(f"Yahoo Finance: pas de données pour {symbol}")

    df = df.rename(
        columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    )
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.tail(lookback)
    return _validate(df, symbol)


def _yf_period_for_lookback(interval: str, lookback: int) -> str:
    """Choisit une période compatible avec les limites de Yahoo intraday."""
    if interval in ("1m",):
        return "7d"
    if interval in ("5m", "15m", "30m", "60m", "90m"):
        return "60d"
    return "2y"


def fetch_alpha_vantage(
    symbol: str, interval: str = "60min", api_key: str | None = None
) -> pd.DataFrame:
    """Récupère les données depuis Alpha Vantage (fallback ou validation croisée)."""
    if not api_key:
        raise DataSourceError("Alpha Vantage: clé API manquante")

    url = "https://www.alphavantage.co/query"
    params: dict[str, Any] = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": symbol,
        "interval": interval,
        "apikey": api_key,
        "outputsize": "compact",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise DataSourceError(f"Alpha Vantage HTTP error: {exc}") from exc

    data = resp.json()
    key = f"Time Series ({interval})"
    if key not in data:
        raise DataSourceError(f"Alpha Vantage: payload inattendu {data}")

    df = pd.DataFrame.from_dict(data[key], orient="index").rename(
        columns={
            "1. open": "open", "2. high": "high", "3. low": "low",
            "4. close": "close", "5. volume": "volume",
        }
    )
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    return _validate(df, symbol)


def fetch_market_data(
    symbol: str,
    asset_type: str,
    interval: str = "1h",
    lookback: int = 300,
    *,
    retries: int = 2,
    backoff: float = 1.5,
) -> pd.DataFrame:
    """Point d'entrée unifié pour récupérer les données d'un actif.

    Route automatiquement vers la bonne source selon le type d'actif et applique
    une logique simple de retry avec backoff exponentiel.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if asset_type == "crypto":
                return fetch_binance(symbol, interval=interval, limit=lookback)
            if asset_type == "futures":
                return fetch_binance_futures(symbol, interval=interval, limit=lookback)
            if asset_type in ("stock", "commodity"):
                return fetch_yfinance(symbol, interval=interval, lookback=lookback)
            raise DataSourceError(f"Type d'actif non supporté: {asset_type}")
        except DataSourceError as exc:
            last_exc = exc
            if attempt >= retries:
                break
            wait = backoff ** attempt
            log.warning("Tentative %s/%s échouée pour %s (%s). Retry dans %.1fs",
                        attempt + 1, retries + 1, symbol, exc, wait)
            time.sleep(wait)

    assert last_exc is not None
    raise last_exc
