#!/usr/bin/env python3
"""
Prototype comparatif : prompt caching vs traduction, en coût réel ($).

Question : pour un contexte réutilisé (ex: un system prompt de N tokens
envoyé R fois), quelle stratégie minimise le coût ?

Stratégies comparées
--------------------
1. Baseline      : contexte FR renvoyé plein tarif à chaque requête.
2. Traduction    : contexte traduit UNE fois vers une langue plus compacte
                   (-s%), puis renvoyé plein tarif à chaque requête.
3. Prompt caching: contexte FR mis en cache (write 1.25x une fois,
                   read 0.1x ensuite).
4. Trad + cache  : le meilleur des deux (traduit puis caché).

Tarifs : Claude Opus 4.8 (input 5$/MTok, output 25$/MTok).
Cache write 5 min = 1.25x input ; cache read = 0.1x input.

Modes
-----
- Hors-ligne (défaut) : modèle de coût paramétrique, zéro réseau, zéro coût.
- --live (clé requise) : envoie 2 requêtes identiques avec cache_control et
  affiche usage.cache_creation_input_tokens / cache_read_input_tokens pour
  PROUVER le fonctionnement du cache sur de vrais chiffres.

Usage
-----
    python3 caching_vs_translation.py
    python3 caching_vs_translation.py --context-tokens 2000 --savings 0.13
    python3 caching_vs_translation.py --live      # nécessite ANTHROPIC_API_KEY
"""

from __future__ import annotations

import argparse
import os
import sys

# Tarifs Opus 4.8 ($/token)
PRICE_IN = 5.0 / 1_000_000
PRICE_OUT = 25.0 / 1_000_000
CACHE_WRITE = PRICE_IN * 1.25   # TTL 5 min
CACHE_READ = PRICE_IN * 0.10
MODEL_DEFAULT = "claude-opus-4-8"


def cost_model(n: int, savings: float, requests_list: list[int]) -> None:
    """Affiche un tableau de coût ($) par stratégie et par nb de requêtes."""
    m = round(n * (1 - savings))  # taille du contexte traduit
    # Traduction = lire le FR (input) + générer la version compacte (output)
    translate_once = n * PRICE_IN + m * PRICE_OUT

    print(f"Contexte : {n} tokens (FR) -> {m} tokens traduits "
          f"(-{savings*100:.0f}%).")
    print(f"Coût unique de traduction : ${translate_once:.4f}\n")

    cols = ["Baseline(FR)", "Traduction", "PromptCache", "Trad+Cache"]
    header = f"{'Requêtes':>9}" + "".join(f"{c:>14}" for c in cols) + f"{'  Gagnant':>16}"
    print(header)
    print("-" * len(header))

    for r in requests_list:
        baseline = r * n * PRICE_IN
        translation = translate_once + r * m * PRICE_IN
        caching = n * CACHE_WRITE + (r - 1) * n * CACHE_READ
        trad_cache = translate_once + m * CACHE_WRITE + (r - 1) * m * CACHE_READ

        vals = {"Baseline(FR)": baseline, "Traduction": translation,
                "PromptCache": caching, "Trad+Cache": trad_cache}
        winner = min(vals, key=vals.get)
        row = f"{r:>9}" + "".join(f"${vals[c]:>12.4f}" for c in cols) + f"{winner:>16}"
        print(row)

    print()
    print("Lecture : le prompt caching écrase la traduction dès quelques")
    print("requêtes (read = 0.1x vs traduction qui reste plein tarif).")
    print("La traduction ne gagne jamais seule ; 'Trad+Cache' n'apporte qu'un")
    print("gain marginal sur le cache pur, au prix d'une perte de fidélité.")


def live_demo(model: str) -> int:
    """Prouve le cache sur 2 requêtes identiques (nécessite une clé)."""
    try:
        import anthropic
    except ImportError:
        print("[!] SDK anthropic absent : pip install anthropic")
        return 1
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[!] ANTHROPIC_API_KEY non définie : impossible de lancer --live.")
        return 1

    client = anthropic.Anthropic()
    # Contexte assez gros pour dépasser le minimum cacheable (~1024-4096 tokens).
    big_context = ("Tu es un assistant expert. " * 400).strip()
    system = [{
        "type": "text",
        "text": big_context,
        "cache_control": {"type": "ephemeral"},
    }]

    def call(label: str):
        r = client.messages.create(
            model=model, max_tokens=16,
            system=system,
            messages=[{"role": "user", "content": "Dis OK."}],
        )
        u = r.usage
        print(f"  [{label}] input={u.input_tokens} "
              f"cache_write={u.cache_creation_input_tokens} "
              f"cache_read={u.cache_read_input_tokens}")
        return u

    print(f"== Démo cache réelle (modèle {model}) ==")
    print("Requête 1 (écrit le cache) :")
    call("1")
    print("Requête 2 (devrait lire le cache) :")
    u2 = call("2")
    if u2.cache_read_input_tokens > 0:
        print(f"\n✓ Cache confirmé : {u2.cache_read_input_tokens} tokens relus "
              f"à 0.1x au lieu du plein tarif.")
    else:
        print("\n[!] cache_read = 0 : invalidateur silencieux (préfixe non stable ?).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--context-tokens", type=int, default=2000,
                   help="Taille du contexte réutilisé en tokens (défaut 2000).")
    p.add_argument("--savings", type=float, default=0.13,
                   help="Gain de tokens de la langue cible (défaut 0.13 = 13%).")
    p.add_argument("--live", action="store_true",
                   help="Démo cache réelle via l'API (clé requise).")
    p.add_argument("--model", default=MODEL_DEFAULT)
    args = p.parse_args()

    if args.live:
        return live_demo(args.model)

    print("== Coût comparé : caching vs traduction (modèle de coût) ==\n")
    cost_model(args.context_tokens, args.savings, [1, 5, 10, 100, 1000])
    print()
    print("[i] Modèle de coût (tarifs Opus 4.8). Pour prouver le cache sur de")
    print("    vrais chiffres : ANTHROPIC_API_KEY=... python3 "
          "caching_vs_translation.py --live")
    return 0


if __name__ == "__main__":
    sys.exit(main())
