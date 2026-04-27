# azaload — Bot d'alerte trading multi-stratégies

> Étudiant à l'EGS — @azaload

Outil **d'aide à la décision** qui surveille en continu plusieurs actifs
(actions, cryptos, or) et émet des alertes BUY / SELL / HOLD avec un score
de confiance et la liste des raisons. Conçu pour être lisible, modulaire et
extensible.

## ⚠️ Disclaimer

Ce bot **n'est pas un conseiller financier** et **ne garantit aucune
performance**. Aucun système ne peut prédire les marchés avec certitude.
Il combine plusieurs facteurs pour maximiser la probabilité d'un signal
pertinent, mais les décisions d'investissement restent de votre
responsabilité.

## Fonctionnalités

- **Sources multiples** : Binance Spot et **Binance USDT-M Futures**
  (perpétuels), Yahoo Finance (actions & matières premières), Alpha
  Vantage (optionnel).
- **Indicateurs techniques** : EMA(20/50/200), MACD, RSI, Bollinger Bands,
  ATR, OBV, ratio de volume.
- **3 stratégies indépendantes** (signaux BUY/SELL/HOLD spot) :
  - *Trend following* — alignement EMAs + confirmation MACD
  - *Breakout* — cassure des bandes de Bollinger + confirmation volume
  - *Mean reversion* — RSI extrême + écart à la moyenne mobile
- **Détecteur de pump/dump dédié futures** (signaux LONG/SHORT) — voir
  section dédiée plus bas.
- **Score de sentiment** (optionnel) basé sur les titres de news (NewsAPI).
- **Signal final** combiné, pondéré, avec :
  - action BUY/SELL/HOLD (spot) ou LONG/SHORT (futures)
  - prix d'entrée, stop loss et take profit (basés sur l'ATR)
  - ratio risk/reward
  - score de confiance / probabilité 0–100 %
  - raisons détaillées (audit complet de chaque trigger)
- **Alertes** : terminal coloré, Telegram, Discord (les deux derniers
  optionnels via variables d'environnement).
- **Logs** rotatifs dans `logs/bot.log`.

## Installation

```bash
git clone https://github.com/azaload/azaload.git
cd azaload
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # éditer si vous voulez activer news/Telegram/Discord
```

## Utilisation

Boucle continue (par défaut, 5 actifs, polling toutes les 5 minutes) :

```bash
python main.py
```

Un seul cycle d'analyse :

```bash
python main.py --once
```

Filtrer les actifs et baisser le seuil de confiance :

```bash
python main.py --symbols BTCUSDT,ETHUSDT --min-confidence 55 --once
```

Mode verbeux (affiche le détail de chaque signal, même HOLD/sous seuil — utile
pour voir ce que le bot perçoit du marché) :

```bash
python main.py --symbols BTCUSDT --verbose --once
```

> Sans `--once`, le bot tourne en continu : un cycle d'analyse, puis sleep
> pendant `poll_interval_seconds` (5 min par défaut). Pendant le sleep il
> n'affiche rien — c'est normal. Utilisez `--interval 60` pour tester plus
> rapidement.

Analyse ad hoc d'un seul symbole :

```bash
python examples/single_asset.py BTCUSDT crypto
python examples/single_asset.py AAPL stock
```

## Exemple de sortie

```
──────────────────────────────────────────────────────────────────────
  BUY    BTCUSDT (Bitcoin)  2026-04-27 14:30 UTC
  Confiance      :  72.4%
  Entrée         : 64210.500000
  Stop Loss      : 63520.150000
  Take Profit    : 65591.200000
  Risk/Reward    : 2.00
  Score par stratégie :
    - trend_following  +0.65
    - breakout         +0.45
    - mean_reversion   +0.10
    - sentiment        +0.20
  Raisons :
    • [trend_following] EMAs alignées haussières (20>50>200)
    • [trend_following] Croisement MACD haussier
    • [breakout] Cassure haussière de la bande de Bollinger sup.
    • [breakout] Volume confirmant (1.74× moyenne)
    • [sentiment] 12 articles analysés, score net = +5
──────────────────────────────────────────────────────────────────────
```

## Détection pump / dump (LONG / SHORT futures)

Le module `bot/pump_dump.py` est un **détecteur dédié aux mouvements
violents** sur futures. Il fonctionne en parallèle du pipeline classique
et a son propre seuil. Il ne s'allume que lorsque plusieurs critères
convergent simultanément, pour ne signaler que les configurations à
**très haute probabilité**.

### Critères évalués (poids par défaut)

| Critère                      | Poids | Conditions                                                |
|------------------------------|------:|-----------------------------------------------------------|
| Volume spike                 | 22    | `volume / SMA20 ≥ 2.5×`                                   |
| Accélération prix            | 22    | mouvement ≥ 1.5 × ATR%, dans la même direction sur 3 bougies |
| Range break / breakdown      | 18    | sortie au-dessus/en-dessous des 20 dernières bougies      |
| RSI thrust                   | 14    | ΔRSI ≥ 10 sur 3 bougies                                   |
| Expansion de volatilité      | 10    | largeur Bollinger × 1.30 vs 3 bougies plus tôt            |
| Confirmation OBV             | 6     | flux d'ordres aligné avec la direction                    |
| Bougie pleine                | 5     | corps ≥ 70 % du range, dans la bonne direction            |
| Squeeze préalable (bonus)    | 3     | compression de volatilité avant la cassure               |

Le score est ramené sur 100. Un signal **LONG** ou **SHORT** n'est émis
que si :

1. La probabilité totale dépasse `min_probability` (70 % par défaut).
2. Le volume spike est présent.
3. ET au moins l'un des deux critères clés (accélération prix ou range
   break) est présent.

Cette double garde-fou élimine les faux positifs dus à un seul indicateur
extrême.

### Activer le détecteur sur les futures Binance

Trois paires perpétuelles USDT-M (BTCUSDT, ETHUSDT, SOLUSDT) en 15 min
sont préchargées dans `config.py`. Pour lancer une analyse pump/dump
ciblée :

```bash
# Mode continu (cycle toutes les minutes par exemple)
python main.py --interval 60 --symbols BTCUSDT,ETHUSDT,SOLUSDT --verbose

# One-shot ciblé sur SOL avec affichage détaillé
python examples/single_asset.py SOLUSDT futures
```

### Tuning

Tous les paramètres sont dans `PumpDumpConfig` (`bot/pump_dump.py`) :

```python
from bot.pump_dump import PumpDumpConfig
from config import CONFIG

CONFIG.pump_dump = PumpDumpConfig(
    volume_spike_ratio=3.0,     # plus strict → moins de signaux
    price_accel_atr_mult=2.0,   # exige un mouvement ≥ 2 × ATR
    min_probability=80.0,       # filtre seulement les très hautes proba
)
```

### Exemple de sortie pump

```
══════════════════════════════════════════════════════════════════════
  ⚡ PUMP DETECTED — LONG   BTCUSDT (BTC Perp)  2026-04-27 22:17 UTC
  Probabilité    :  92.0%
  Entrée         : 64210.500000
  Stop Loss      : 63520.150000
  Take Profit    : 65800.300000
  Risk/Reward    : 2.30
  Triggers actifs :
    ✓ volume_spike
    ✓ price_acceleration
    ✓ range_break
    ✓ rsi_thrust
    ✓ volatility_expansion
    ✓ obv_confirmation
    ✓ full_body
    · prior_squeeze
  Raisons :
    • Volume spike 4.17× (seuil 2.5×)
    • Accélération prix ↑ ret_1=+1.85%, ret_3=+3.20% vs ATR%=0.62%
    • Breakout au-dessus du range des 20 dernières bougies
    • RSI thrust ↑ ΔRSI(3)=+18.4 (RSI=72.1)
    • ...
══════════════════════════════════════════════════════════════════════
```

## Configuration

Tout passe par `config.py` (édité directement) ou par variables
d'environnement / `.env` pour les secrets.

- Liste des actifs surveillés : `Config.assets`
- Pondération des stratégies : `StrategyWeights`
- Stop loss / take profit (multiples d'ATR) et seuil d'alerte :
  `RiskConfig`

## Architecture

```
azaload/
├── main.py                # Boucle de polling + dispatch des alertes
├── config.py              # Config typée (actifs, poids, risque, secrets)
├── requirements.txt
├── .env.example
└── bot/
    ├── data_sources.py    # Binance Spot+Futures / Yahoo / Alpha Vantage + retries
    ├── indicators.py      # EMA, MACD, RSI, BB, ATR, OBV via `ta`
    ├── strategies.py      # Trend / Breakout / Mean reversion (BUY/SELL/HOLD)
    ├── pump_dump.py       # Détecteur LONG/SHORT futures multi-trigger
    ├── sentiment.py       # Lexique + NewsAPI (optionnel)
    ├── signals.py         # Combinaison pondérée + SL/TP via ATR
    ├── alerts.py          # Terminal coloré + Telegram + Discord
    └── logger.py          # Logger rotatif (console + fichier)
```

Le découplage permet d'ajouter facilement :

- une nouvelle stratégie : implémentez une fonction
  `(df) -> StrategyResult` et ajoutez-la à `run_all()` ;
- une nouvelle source de données : suivez l'interface des fonctions
  `fetch_*` (entrée: symbole, sortie: DataFrame OHLCV indexé par
  timestamp UTC) ;
- un nouveau canal d'alerte : appelez `dispatch(..., extra_sinks=[fn])`.

## Limites connues

- Le sentiment basé sur un lexique anglais est volontairement simple et ne
  remplace pas un vrai modèle NLP.
- Le bot émet des **suggestions**, jamais des ordres : aucune intégration
  d'exécution n'est fournie volontairement.
- Sur les actions intraday, Yahoo Finance limite l'historique disponible
  (~60 jours pour les bougies < 1 jour).
- Le détecteur pump/dump détecte le **début** d'un mouvement, pas son
  ampleur finale. Les SL/TP sont basés sur l'ATR ; le R/R par défaut est
  ~2.5 mais aucun setup ne garantit l'aboutissement de la cible.
- Aucun système ne peut prédire les pumps "informationnels" qui n'ont pas
  encore laissé d'empreinte sur le volume ou le prix. Le détecteur réagit
  à la convergence d'indicateurs déjà visibles, pas à de la prescience.
