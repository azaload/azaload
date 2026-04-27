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

- **Sources multiples** : Binance (crypto, public), Yahoo Finance (actions
  & matières premières), Alpha Vantage (optionnel).
- **Indicateurs techniques** : EMA(20/50/200), MACD, RSI, Bollinger Bands,
  ATR, OBV, ratio de volume.
- **3 stratégies indépendantes** :
  - *Trend following* — alignement EMAs + confirmation MACD
  - *Breakout* — cassure des bandes de Bollinger + confirmation volume
  - *Mean reversion* — RSI extrême + écart à la moyenne mobile
- **Score de sentiment** (optionnel) basé sur les titres de news (NewsAPI).
- **Signal final** combiné, pondéré, avec :
  - action BUY/SELL/HOLD
  - prix d'entrée, stop loss et take profit (basés sur l'ATR)
  - ratio risk/reward
  - score de confiance 0–100 %
  - raisons détaillées
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
    ├── data_sources.py    # Binance / Yahoo / Alpha Vantage + retries
    ├── indicators.py      # EMA, MACD, RSI, BB, ATR, OBV via `ta`
    ├── strategies.py      # Trend / Breakout / Mean reversion
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
