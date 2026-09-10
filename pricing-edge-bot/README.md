# Pricing-Edge Bot (δ / EV / Kelly)

Bot **autonome et indépendant** (ne réutilise ni ne dépend d'aucun autre bot
du repo) qui teste, sur des données réelles, la stratégie suivante :

1. **Correction d'erreur de prix (δ)** — mesure, sur des marchés Polymarket
   *déjà résolus*, l'écart entre le prix d'entrée et le taux de réussite réel,
   par tranche de prix (0-20¢, 20-50¢, 50-80¢, 80-95¢, 95-99¢).
2. **Espérance de gain (EV)** — `EV = P_gain × Gain − P_perte × Coût`, calculée
   à partir de la probabilité corrigée `p_hat = prix + δ`.
3. **Dimensionnement de Kelly** — `f* = (p·b − q) / b`, appliqué en **Kelly
   fractionné** (¼ Kelly par défaut) avec un plafond dur, pour limiter les
   dégâts si l'estimation de `p` est fausse.

## ⚠️ À lire avant toute chose

- **Aucune garantie de gain.** Ce bot ne "gagne pas de l'argent" par
  construction — il teste une hypothèse statistique. Un backtest positif
  prouve que le biais a existé *dans l'échantillon historique testé*, pas
  qu'il persistera. Traitez tout chiffre de performance (le vôtre ou celui
  d'une publicité) avec le même scepticisme.
- **Ne faites confiance à aucun taux de réussite annoncé** ("99,3%", "72
  millions de transactions", etc.) sans l'avoir vérifié vous-même sur des
  données vérifiables. `fetch_market_history.py` sert exactement à ça :
  construire votre propre jeu de données à partir de l'API publique de
  Polymarket, indépendamment de toute affirmation marketing.
- **Ne partagez jamais votre clé privée.** Utilisez un wallet dédié, financé
  uniquement du montant que vous êtes prêt à perdre.
- **Mode paper trading par défaut.** Aucune transaction réelle tant que vous
  n'avez pas explicitement mis `PAPER_TRADING=false` ET une clé privée.
- Ce bot n'est pas lié à un wallet de "copy trading" particulier — il ne
  copie aucun trader spécifique, il applique sa propre logique statistique.

## Installation

```bash
cd pricing-edge-bot
pip install -r requirements.txt
cp .env.example .env
```

## Étape 1 — Tests unitaires (obligatoire avant tout le reste)

```bash
python -m pytest -v
```

Ces tests vérifient les formules (EV, Kelly, δ) sur des valeurs connues, le
moteur de backtest (détecte un vrai biais injecté, reste à zéro quand il n'y
a aucun biais), et le risk manager (plafonds, cooldowns, pause après série de
pertes). **Si un test échoue, ne passez pas à l'étape suivante.**

## Étape 2 — Construire un jeu de données réel

```bash
python fetch_market_history.py --tag tennis --limit 500 --lookback-minutes 60 \
    --output data/markets_history.jsonl
```

Interroge l'API publique de Polymarket (Gamma + CLOB) pour les marchés tennis
déjà résolus et enregistre des paires (prix d'entrée, résultat) réelles — pas
de données inventées. Si le script ne renvoie rien, ne partez pas du principe
que la stratégie n'a aucun signal : vérifiez d'abord manuellement que les
endpoints/schémas d'API n'ont pas changé (l'API de Polymarket évolue).

## Étape 3 — Backtester la stratégie sur ces données

```python
import json
from pricing_edge import ResolvedMarket
from backtest import run_backtest, BacktestConfig

markets = []
with open("data/markets_history.jsonl") as f:
    for line in f:
        r = json.loads(line)
        markets.append(ResolvedMarket(r["entry_price"], r["outcome"], r["resolved_at"]))

result = run_backtest(markets, BacktestConfig())
print(result.summary())
```

Le moteur utilise une estimation **walk-forward** de δ : pour un trade pris à
l'instant T, seuls les marchés résolus *avant* T sont utilisés pour estimer
le biais. Un backtest qui calculerait un seul δ sur tout l'historique et
l'appliquerait à l'ensemble du même historique ferait fuiter de l'information
du futur dans son propre signal — un classique des backtests trompeurs.

Limites du backtest à garder en tête :
- Il ignore le slippage, l'impact de marché des grosses ordres, et le fait
  qu'un signal calculé sur un prix légèrement périmé peut ne plus être
  disponible au moment de l'exécution réelle.
- Un échantillon historique n'est pas un échantillon aléatoire du futur.

## Étape 4 — Paper trading en continu

```bash
python main.py
```

Scanne les marchés tennis actifs, applique le pipeline δ → EV → Kelly →
risk manager, et journalise chaque trade simulé dans
`logs/paper_trades.jsonl`. Aucun fonds réel n'est jamais déplacé.

## Étape 5 — Live (seulement après avoir lu tout ce qui précède)

1. `PAPER_TRADING=false` et `WALLET_PRIVATE_KEY=...` dans `.env` (wallet
   dédié, fonds limités).
2. `python main.py` et surveillez `logs/` de près.

## Structure

| Fichier | Rôle |
|---|---|
| `ev.py` | Formule d'espérance de gain |
| `kelly.py` | Dimensionnement de Kelly (fractionné + plafond) |
| `pricing_edge.py` | Calcul empirique de δ par tranche de prix, estimation walk-forward |
| `backtest.py` | Moteur de backtest (δ → EV → Kelly → P&L simulé) |
| `fetch_market_history.py` | Construit un jeu de données réel depuis l'API publique Polymarket |
| `risk_manager.py` | Plafonds quotidiens, cooldowns, pause après série de pertes |
| `trade_executor.py` | Exécution paper ou live (py-clob-client) |
| `main.py` | Scanner live, relie tous les modules |
| `tests/` | Tests unitaires (formules, backtest, risk manager) |

## État et logs

- `state/risk_state.json` — bankroll, dépenses du jour, cooldowns. Supprimez
  ce fichier pour repartir de zéro.
- `logs/paper_trades.jsonl` — un trade simulé par ligne.
- `data/markets_history.jsonl` — jeu de données historique (généré, non
  versionné).
