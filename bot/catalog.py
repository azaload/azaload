"""Catalogue d'actifs disponibles pour la détection.

- Crypto Spot et Futures: récupéré dynamiquement depuis Binance
  (`/exchangeInfo` + `/ticker/24hr`), avec cache mémoire.
- Stocks / ETF / Commodities / Indices: liste curée tenue à jour ici
  (n'importe quel ticker Yahoo reste utilisable manuellement via la
  recherche libre).

Toutes les entrées exposent un `symbol`, un `name`, un `asset_type` et
un `interval` recommandé pour l'analyse.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Iterable

import requests

from .logger import get_logger

log = get_logger(__name__)


@dataclass
class CatalogEntry:
    symbol: str
    name: str
    asset_type: str        # "crypto" | "futures" | "stock" | "etf" | "commodity" | "index" | "forex"
    interval: str = "1h"
    quote_volume_24h: float | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Liste curée non-crypto (Yahoo Finance)
# --------------------------------------------------------------------------

_CURATED_NON_CRYPTO: list[CatalogEntry] = [
    # ---------- Indices boursiers ----------
    CatalogEntry("^GSPC", "S&P 500", "index", "1h", tags=["us"]),
    CatalogEntry("^DJI", "Dow Jones", "index", "1h", tags=["us"]),
    CatalogEntry("^IXIC", "NASDAQ Composite", "index", "1h", tags=["us"]),
    CatalogEntry("^RUT", "Russell 2000", "index", "1h", tags=["us"]),
    CatalogEntry("^VIX", "VIX (volatilité)", "index", "1h", tags=["us", "volatility"]),
    CatalogEntry("^FTSE", "FTSE 100", "index", "1h", tags=["uk"]),
    CatalogEntry("^GDAXI", "DAX", "index", "1h", tags=["de"]),
    CatalogEntry("^FCHI", "CAC 40", "index", "1h", tags=["fr"]),
    CatalogEntry("^N225", "Nikkei 225", "index", "1h", tags=["jp"]),

    # ---------- Commodities (futures Yahoo) ----------
    CatalogEntry("GC=F", "Gold", "commodity", "1h", tags=["metal", "safe-haven"]),
    CatalogEntry("SI=F", "Silver", "commodity", "1h", tags=["metal"]),
    CatalogEntry("PL=F", "Platinum", "commodity", "1h", tags=["metal"]),
    CatalogEntry("PA=F", "Palladium", "commodity", "1h", tags=["metal"]),
    CatalogEntry("HG=F", "Copper", "commodity", "1h", tags=["metal", "industrial"]),
    CatalogEntry("CL=F", "WTI Crude Oil", "commodity", "1h", tags=["energy"]),
    CatalogEntry("BZ=F", "Brent Crude", "commodity", "1h", tags=["energy"]),
    CatalogEntry("NG=F", "Natural Gas", "commodity", "1h", tags=["energy"]),
    CatalogEntry("ZC=F", "Corn", "commodity", "1h", tags=["agri"]),
    CatalogEntry("ZW=F", "Wheat", "commodity", "1h", tags=["agri"]),
    CatalogEntry("ZS=F", "Soybeans", "commodity", "1h", tags=["agri"]),
    CatalogEntry("KC=F", "Coffee", "commodity", "1h", tags=["agri"]),
    CatalogEntry("SB=F", "Sugar", "commodity", "1h", tags=["agri"]),

    # ---------- ETFs broad market ----------
    CatalogEntry("SPY", "S&P 500 ETF", "etf", "1h", tags=["us", "broad"]),
    CatalogEntry("QQQ", "NASDAQ 100 ETF", "etf", "1h", tags=["us", "tech"]),
    CatalogEntry("IWM", "Russell 2000 ETF", "etf", "1h", tags=["us", "small-cap"]),
    CatalogEntry("DIA", "Dow Jones ETF", "etf", "1h", tags=["us"]),
    CatalogEntry("VOO", "Vanguard S&P 500", "etf", "1h", tags=["us", "broad"]),
    CatalogEntry("VTI", "Vanguard Total US Market", "etf", "1h", tags=["us", "broad"]),
    CatalogEntry("VEA", "Vanguard Developed Markets", "etf", "1h", tags=["intl"]),
    CatalogEntry("VWO", "Vanguard Emerging Markets", "etf", "1h", tags=["em"]),
    CatalogEntry("EFA", "iShares MSCI EAFE", "etf", "1h", tags=["intl"]),
    CatalogEntry("EEM", "iShares MSCI Emerging", "etf", "1h", tags=["em"]),

    # ---------- ETFs sectoriels ----------
    CatalogEntry("XLF", "Financials Sector", "etf", "1h", tags=["sector", "finance"]),
    CatalogEntry("XLK", "Technology Sector", "etf", "1h", tags=["sector", "tech"]),
    CatalogEntry("XLE", "Energy Sector", "etf", "1h", tags=["sector", "energy"]),
    CatalogEntry("XLV", "Health Care Sector", "etf", "1h", tags=["sector", "health"]),
    CatalogEntry("XLY", "Consumer Discretionary", "etf", "1h", tags=["sector"]),
    CatalogEntry("XLP", "Consumer Staples", "etf", "1h", tags=["sector"]),
    CatalogEntry("XLI", "Industrials Sector", "etf", "1h", tags=["sector"]),
    CatalogEntry("XLU", "Utilities Sector", "etf", "1h", tags=["sector"]),
    CatalogEntry("XLB", "Materials Sector", "etf", "1h", tags=["sector"]),
    CatalogEntry("XLRE", "Real Estate Sector", "etf", "1h", tags=["sector", "reit"]),
    CatalogEntry("XLC", "Communication Services", "etf", "1h", tags=["sector"]),

    # ---------- ETFs commodities ----------
    CatalogEntry("GLD", "SPDR Gold Trust", "etf", "1h", tags=["commodity", "gold"]),
    CatalogEntry("IAU", "iShares Gold Trust", "etf", "1h", tags=["commodity", "gold"]),
    CatalogEntry("SLV", "iShares Silver Trust", "etf", "1h", tags=["commodity", "silver"]),
    CatalogEntry("USO", "United States Oil Fund", "etf", "1h", tags=["commodity", "oil"]),
    CatalogEntry("UNG", "United States Natural Gas", "etf", "1h", tags=["commodity", "natgas"]),
    CatalogEntry("DBC", "Invesco Commodity Index", "etf", "1h", tags=["commodity", "broad"]),

    # ---------- ETFs obligataires ----------
    CatalogEntry("TLT", "iShares 20+ Year Treasury", "etf", "1h", tags=["bond", "long-duration"]),
    CatalogEntry("AGG", "iShares Core US Aggregate", "etf", "1h", tags=["bond"]),
    CatalogEntry("BND", "Vanguard Total Bond", "etf", "1h", tags=["bond"]),
    CatalogEntry("HYG", "iShares High Yield", "etf", "1h", tags=["bond", "hy"]),
    CatalogEntry("LQD", "iShares Investment Grade", "etf", "1h", tags=["bond", "ig"]),

    # ---------- ETFs exposition crypto ----------
    CatalogEntry("BITO", "ProShares Bitcoin Strategy", "etf", "1h", tags=["crypto-equity"]),
    CatalogEntry("IBIT", "iShares Bitcoin Trust", "etf", "1h", tags=["crypto-equity"]),

    # ---------- Stocks: méga caps tech ----------
    CatalogEntry("AAPL", "Apple", "stock", "1h", tags=["tech", "us-large"]),
    CatalogEntry("MSFT", "Microsoft", "stock", "1h", tags=["tech", "us-large"]),
    CatalogEntry("GOOGL", "Alphabet (A)", "stock", "1h", tags=["tech", "us-large"]),
    CatalogEntry("AMZN", "Amazon", "stock", "1h", tags=["tech", "us-large"]),
    CatalogEntry("NVDA", "Nvidia", "stock", "1h", tags=["tech", "semiconductor"]),
    CatalogEntry("META", "Meta Platforms", "stock", "1h", tags=["tech", "us-large"]),
    CatalogEntry("TSLA", "Tesla", "stock", "1h", tags=["auto", "us-large"]),
    CatalogEntry("AVGO", "Broadcom", "stock", "1h", tags=["semiconductor"]),
    CatalogEntry("AMD", "AMD", "stock", "1h", tags=["semiconductor"]),
    CatalogEntry("ORCL", "Oracle", "stock", "1h", tags=["tech"]),
    CatalogEntry("ADBE", "Adobe", "stock", "1h", tags=["tech"]),
    CatalogEntry("CRM", "Salesforce", "stock", "1h", tags=["tech"]),
    CatalogEntry("NFLX", "Netflix", "stock", "1h", tags=["media", "tech"]),
    CatalogEntry("PLTR", "Palantir", "stock", "1h", tags=["tech"]),
    CatalogEntry("SHOP", "Shopify", "stock", "1h", tags=["tech", "ecommerce"]),
    CatalogEntry("COIN", "Coinbase", "stock", "1h", tags=["crypto-equity"]),
    CatalogEntry("INTC", "Intel", "stock", "1h", tags=["semiconductor"]),

    # ---------- Stocks: finance ----------
    CatalogEntry("BRK-B", "Berkshire Hathaway", "stock", "1h", tags=["finance"]),
    CatalogEntry("V", "Visa", "stock", "1h", tags=["finance", "payments"]),
    CatalogEntry("MA", "Mastercard", "stock", "1h", tags=["finance", "payments"]),
    CatalogEntry("JPM", "JPMorgan Chase", "stock", "1h", tags=["finance", "bank"]),
    CatalogEntry("BAC", "Bank of America", "stock", "1h", tags=["finance", "bank"]),
    CatalogEntry("GS", "Goldman Sachs", "stock", "1h", tags=["finance", "bank"]),
    CatalogEntry("MS", "Morgan Stanley", "stock", "1h", tags=["finance", "bank"]),
    CatalogEntry("WFC", "Wells Fargo", "stock", "1h", tags=["finance", "bank"]),

    # ---------- Stocks: santé / pharma ----------
    CatalogEntry("UNH", "UnitedHealth", "stock", "1h", tags=["health"]),
    CatalogEntry("JNJ", "Johnson & Johnson", "stock", "1h", tags=["health", "pharma"]),
    CatalogEntry("LLY", "Eli Lilly", "stock", "1h", tags=["health", "pharma"]),
    CatalogEntry("PFE", "Pfizer", "stock", "1h", tags=["health", "pharma"]),

    # ---------- Stocks: consumer ----------
    CatalogEntry("WMT", "Walmart", "stock", "1h", tags=["retail"]),
    CatalogEntry("COST", "Costco", "stock", "1h", tags=["retail"]),
    CatalogEntry("HD", "Home Depot", "stock", "1h", tags=["retail"]),
    CatalogEntry("MCD", "McDonald's", "stock", "1h", tags=["consumer"]),
    CatalogEntry("NKE", "Nike", "stock", "1h", tags=["consumer"]),
    CatalogEntry("KO", "Coca-Cola", "stock", "1h", tags=["consumer"]),
    CatalogEntry("PEP", "PepsiCo", "stock", "1h", tags=["consumer"]),
    CatalogEntry("PG", "Procter & Gamble", "stock", "1h", tags=["consumer"]),
    CatalogEntry("DIS", "Disney", "stock", "1h", tags=["media"]),

    # ---------- Stocks: industriels / énergie ----------
    CatalogEntry("XOM", "ExxonMobil", "stock", "1h", tags=["energy"]),
    CatalogEntry("CVX", "Chevron", "stock", "1h", tags=["energy"]),
    CatalogEntry("BA", "Boeing", "stock", "1h", tags=["industrial"]),
    CatalogEntry("CAT", "Caterpillar", "stock", "1h", tags=["industrial"]),
    CatalogEntry("GE", "General Electric", "stock", "1h", tags=["industrial"]),
    CatalogEntry("RTX", "Raytheon", "stock", "1h", tags=["industrial", "defense"]),

    # ---------- Forex (paires majeures) ----------
    CatalogEntry("EURUSD=X", "EUR/USD", "forex", "1h", tags=["fx", "major"]),
    CatalogEntry("GBPUSD=X", "GBP/USD", "forex", "1h", tags=["fx", "major"]),
    CatalogEntry("USDJPY=X", "USD/JPY", "forex", "1h", tags=["fx", "major"]),
    CatalogEntry("USDCHF=X", "USD/CHF", "forex", "1h", tags=["fx", "major"]),
    CatalogEntry("AUDUSD=X", "AUD/USD", "forex", "1h", tags=["fx", "major"]),
    CatalogEntry("USDCAD=X", "USD/CAD", "forex", "1h", tags=["fx", "major"]),
]


# --------------------------------------------------------------------------
# Catalogue Binance (rafraîchi périodiquement)
# --------------------------------------------------------------------------

_BINANCE_CACHE_TTL = 600.0  # 10 minutes
_QUOTE = "USDT"

_binance_spot_cache: tuple[float, list[CatalogEntry]] | None = None
_binance_futures_cache: tuple[float, list[CatalogEntry]] | None = None


def _http_json(url: str, timeout: float = 10.0):
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _fetch_binance_spot() -> list[CatalogEntry]:
    """Récupère toutes les paires USDT actives sur Binance Spot avec leur volume 24h."""
    info = _http_json("https://api.binance.com/api/v3/exchangeInfo")
    tickers = _http_json("https://api.binance.com/api/v3/ticker/24hr")
    vol_by_symbol = {
        t["symbol"]: float(t.get("quoteVolume") or 0.0)
        for t in tickers
    }

    entries: list[CatalogEntry] = []
    for s in info.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != _QUOTE:
            continue
        if not s.get("isSpotTradingAllowed", True):
            continue
        sym = s["symbol"]
        base = s.get("baseAsset", sym.replace(_QUOTE, ""))
        entries.append(CatalogEntry(
            symbol=sym,
            name=f"{base} / {_QUOTE}",
            asset_type="crypto",
            interval="1h",
            quote_volume_24h=vol_by_symbol.get(sym),
            tags=["binance-spot"],
        ))
    entries.sort(key=lambda e: -(e.quote_volume_24h or 0.0))
    return entries


def _fetch_binance_futures() -> list[CatalogEntry]:
    """Récupère toutes les paires perpétuelles USDT-M actives sur Binance Futures."""
    info = _http_json("https://fapi.binance.com/fapi/v1/exchangeInfo")
    tickers = _http_json("https://fapi.binance.com/fapi/v1/ticker/24hr")
    vol_by_symbol = {
        t["symbol"]: float(t.get("quoteVolume") or 0.0)
        for t in tickers
    }

    entries: list[CatalogEntry] = []
    for s in info.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if s.get("contractType") != "PERPETUAL":
            continue
        if s.get("quoteAsset") != _QUOTE:
            continue
        sym = s["symbol"]
        base = s.get("baseAsset", sym.replace(_QUOTE, ""))
        entries.append(CatalogEntry(
            symbol=sym,
            name=f"{base} Perp",
            asset_type="futures",
            interval="15m",
            quote_volume_24h=vol_by_symbol.get(sym),
            tags=["binance-futures", "perpetual"],
        ))
    entries.sort(key=lambda e: -(e.quote_volume_24h or 0.0))
    return entries


def get_binance_spot(force_refresh: bool = False) -> list[CatalogEntry]:
    global _binance_spot_cache
    now = time.time()
    if not force_refresh and _binance_spot_cache and now - _binance_spot_cache[0] < _BINANCE_CACHE_TTL:
        return _binance_spot_cache[1]
    try:
        entries = _fetch_binance_spot()
        _binance_spot_cache = (now, entries)
        log.info("Catalogue Binance Spot rafraîchi: %d paires USDT", len(entries))
        return entries
    except Exception as exc:
        log.warning("Catalogue Binance Spot KO (%s); cache=%s",
                    exc, "oui" if _binance_spot_cache else "non")
        return _binance_spot_cache[1] if _binance_spot_cache else []


def get_binance_futures(force_refresh: bool = False) -> list[CatalogEntry]:
    global _binance_futures_cache
    now = time.time()
    if not force_refresh and _binance_futures_cache and now - _binance_futures_cache[0] < _BINANCE_CACHE_TTL:
        return _binance_futures_cache[1]
    try:
        entries = _fetch_binance_futures()
        _binance_futures_cache = (now, entries)
        log.info("Catalogue Binance Futures rafraîchi: %d perpétuels USDT", len(entries))
        return entries
    except Exception as exc:
        log.warning("Catalogue Binance Futures KO (%s); cache=%s",
                    exc, "oui" if _binance_futures_cache else "non")
        return _binance_futures_cache[1] if _binance_futures_cache else []


def get_curated_non_crypto() -> list[CatalogEntry]:
    return list(_CURATED_NON_CRYPTO)


# --------------------------------------------------------------------------
# Recherche / filtre
# --------------------------------------------------------------------------

def all_entries(*, refresh: bool = False) -> list[CatalogEntry]:
    return [
        *get_curated_non_crypto(),
        *get_binance_spot(force_refresh=refresh),
        *get_binance_futures(force_refresh=refresh),
    ]


def search(
    *,
    query: str | None = None,
    asset_type: str | None = None,
    tag: str | None = None,
    min_volume: float | None = None,
    limit: int = 200,
) -> list[CatalogEntry]:
    """Recherche dans le catalogue. Tous les filtres sont optionnels."""
    pool = all_entries()
    q = (query or "").strip().lower()

    def keep(e: CatalogEntry) -> bool:
        if asset_type and e.asset_type != asset_type:
            return False
        if tag and tag not in e.tags:
            return False
        if min_volume and (e.quote_volume_24h or 0.0) < min_volume:
            return False
        if q:
            haystack = f"{e.symbol} {e.name} {' '.join(e.tags)}".lower()
            if q not in haystack:
                return False
        return True

    matched = [e for e in pool if keep(e)]
    return matched[:limit]


def find(symbol: str, asset_type: str | None = None) -> CatalogEntry | None:
    """Cherche une entrée exacte. Si non trouvée et asset_type fourni, en
    crée une à la volée (utile pour ajouter un ticker Yahoo arbitraire)."""
    sym_up = symbol.upper().strip()
    for e in all_entries():
        if e.symbol.upper() == sym_up and (not asset_type or e.asset_type == asset_type):
            return e
    if asset_type:
        return CatalogEntry(symbol=sym_up, name=sym_up, asset_type=asset_type)
    return None


def stats() -> dict:
    """Statistiques du catalogue (utile pour le header de l'UI)."""
    return {
        "crypto_spot": len(get_binance_spot()),
        "crypto_futures": len(get_binance_futures()),
        "stocks": sum(1 for e in _CURATED_NON_CRYPTO if e.asset_type == "stock"),
        "etfs": sum(1 for e in _CURATED_NON_CRYPTO if e.asset_type == "etf"),
        "commodities": sum(1 for e in _CURATED_NON_CRYPTO if e.asset_type == "commodity"),
        "indices": sum(1 for e in _CURATED_NON_CRYPTO if e.asset_type == "index"),
        "forex": sum(1 for e in _CURATED_NON_CRYPTO if e.asset_type == "forex"),
    }
