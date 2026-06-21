#!/usr/bin/env python3
"""
Micro-test de faisabilité : économie de tokens par traduction du français
vers une langue plus "optimisée" (au sens du tokenizer de Claude).

Principe
--------
On compare, à contenu sémantique équivalent, le nombre de tokens consommés
par plusieurs langues. La référence est le français. La langue la plus
économe est candidate pour un futur pipeline "FR -> langue optimisée -> FR".

Coût du test
------------
- Mode exact (clé ANTHROPIC_API_KEY présente) : utilise l'endpoint
  `count_tokens`. Il NE génère AUCUN token de sortie -> coût quasi nul.
  Nombre d'appels = nb_échantillons x nb_langues (ici 3 x 9 = 27 appels).
- Mode approximatif (sans clé) : heuristique locale, zéro réseau, zéro coût.
  Donne un ordre de grandeur, PAS une mesure officielle.

Usage
-----
    python3 feasibility_tokens.py            # exact si clé, sinon approx
    python3 feasibility_tokens.py --approx   # force le mode hors-ligne
    python3 feasibility_tokens.py --model claude-opus-4-8
"""

from __future__ import annotations

import argparse
import os
import sys

MODEL_DEFAULT = "claude-opus-4-8"

# Échantillons FR + traductions équivalentes baked-in.
# On NE traduit PAS via l'API ici : on mesure seulement le coût en tokens
# de textes déjà traduits. La traduction réelle (génération) est l'étape
# coûteuse, scriptée séparément une fois la langue optimale identifiée.
SAMPLES: dict[str, dict[str, str]] = {
    "instruction": {
        "fr": "Résume le texte suivant en trois points clés, puis propose une amélioration concrète.",
        "en": "Summarize the following text in three key points, then propose a concrete improvement.",
        "es": "Resume el siguiente texto en tres puntos clave, luego propón una mejora concreta.",
        "de": "Fasse den folgenden Text in drei Kernpunkten zusammen und schlage dann eine konkrete Verbesserung vor.",
        "it": "Riassumi il testo seguente in tre punti chiave, poi proponi un miglioramento concreto.",
        "pt": "Resuma o texto a seguir em três pontos-chave e proponha uma melhoria concreta.",
        "id": "Ringkas teks berikut dalam tiga poin utama, lalu usulkan satu perbaikan konkret.",
        "eo": "Resumu la sekvan tekston en tri ĉefaj punktoj, poste proponu konkretan plibonigon.",
        "zh": "用三个要点总结以下文本，然后提出一个具体的改进建议。",
    },
    "prose": {
        "fr": "Le soleil se couchait lentement derrière les collines, teintant le ciel d'orange et de pourpre.",
        "en": "The sun was setting slowly behind the hills, tinting the sky orange and purple.",
        "es": "El sol se ponía lentamente tras las colinas, tiñendo el cielo de naranja y púrpura.",
        "de": "Die Sonne ging langsam hinter den Hügeln unter und färbte den Himmel orange und purpurn.",
        "it": "Il sole tramontava lentamente dietro le colline, tingendo il cielo di arancione e porpora.",
        "pt": "O sol se punha lentamente atrás das colinas, tingindo o céu de laranja e púrpura.",
        "id": "Matahari perlahan terbenam di balik bukit, mewarnai langit dengan jingga dan ungu.",
        "eo": "La suno malrapide subiris malantaŭ la montetoj, kolorigante la ĉielon oranĝa kaj purpura.",
        "zh": "太阳缓缓落在山丘后面，把天空染成橙色和紫色。",
    },
    "technique": {
        "fr": "Pour optimiser la requête, ajoute un index sur la colonne date et évite les jointures inutiles.",
        "en": "To optimize the query, add an index on the date column and avoid unnecessary joins.",
        "es": "Para optimizar la consulta, añade un índice en la columna de fecha y evita uniones innecesarias.",
        "de": "Um die Abfrage zu optimieren, füge einen Index auf der Datumsspalte hinzu und vermeide unnötige Joins.",
        "it": "Per ottimizzare la query, aggiungi un indice sulla colonna data ed evita join inutili.",
        "pt": "Para otimizar a consulta, adicione um índice na coluna de data e evite junções desnecessárias.",
        "id": "Untuk mengoptimalkan kueri, tambahkan indeks pada kolom tanggal dan hindari join yang tidak perlu.",
        "eo": "Por optimumigi la informmendon, aldonu indekson al la dato-kolumno kaj evitu nenecesajn kunigojn.",
        "zh": "为优化查询，请在日期列上添加索引，并避免不必要的连接。",
    },
}

LANG_NAMES = {
    "fr": "Français", "en": "Anglais", "es": "Espagnol", "de": "Allemand",
    "it": "Italien", "pt": "Portugais", "id": "Indonésien", "eo": "Espéranto",
    "zh": "Chinois",
}

LANGS = ["fr", "en", "es", "de", "it", "pt", "id", "eo", "zh"]


def approx_tokens(text: str) -> int:
    """Proxy local grossier (PAS le tokenizer de Claude).

    - Scripts latins : ~mots * 1.3 + ponctuation (proche du comportement BPE).
    - Caractères CJK : ~1.1 token / caractère (souvent 1-2).
    Sert uniquement à donner un ordre de grandeur sans clé API.
    """
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    rest = "".join(" " if ("一" <= ch <= "鿿") else ch for ch in text)
    words = len(rest.split())
    punct = sum(1 for ch in rest if ch in ".,;:!?'\"()-")
    return round(cjk * 1.1 + words * 1.3 + punct * 0.5)


def count_with_api(client, model: str, text: str) -> int:
    resp = client.messages.count_tokens(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    return resp.input_tokens


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approx", action="store_true",
                        help="Force le mode hors-ligne (heuristique).")
    parser.add_argument("--model", default=MODEL_DEFAULT,
                        help=f"Modèle pour count_tokens (défaut: {MODEL_DEFAULT}).")
    args = parser.parse_args()

    use_api = not args.approx and bool(os.environ.get("ANTHROPIC_API_KEY"))
    client = None
    if use_api:
        try:
            import anthropic
            client = anthropic.Anthropic()
        except Exception as e:  # pragma: no cover
            print(f"[!] SDK/clé indisponible ({e}); bascule en mode approximatif.\n")
            use_api = False

    mode = "EXACT (count_tokens)" if use_api else "APPROXIMATIF (heuristique locale)"
    print(f"== Micro-test économie de tokens — mode {mode} ==")
    if use_api:
        print(f"   Modèle: {args.model}")
    print()

    def measure(text: str) -> int:
        return count_with_api(client, args.model, text) if use_api else approx_tokens(text)

    # Tableau détaillé + agrégation
    totals: dict[str, int] = {lang: 0 for lang in LANGS}
    header = f"{'Échantillon':<14}" + "".join(f"{LANG_NAMES[l][:6]:>9}" for l in LANGS)
    print(header)
    print("-" * len(header))
    for sample_name, variants in SAMPLES.items():
        counts = {lang: measure(variants[lang]) for lang in LANGS}
        for lang in LANGS:
            totals[lang] += counts[lang]
        row = f"{sample_name:<14}" + "".join(f"{counts[l]:>9}" for l in LANGS)
        print(row)
    print("-" * len(header))
    print(f"{'TOTAL':<14}" + "".join(f"{totals[l]:>9}" for l in LANGS))
    print()

    # Classement par économie vs français
    base = totals["fr"]
    print(f"Référence française : {base} tokens (cumul des 3 échantillons)\n")
    ranking = sorted(LANGS, key=lambda l: totals[l])
    print(f"{'Rang':<5}{'Langue':<14}{'Tokens':>8}{'Écart vs FR':>14}")
    print("-" * 41)
    for i, lang in enumerate(ranking, 1):
        diff = totals[lang] - base
        pct = (diff / base * 100) if base else 0
        sign = "+" if diff > 0 else ""
        flag = "  <- baseline" if lang == "fr" else ""
        print(f"{i:<5}{LANG_NAMES[lang]:<14}{totals[lang]:>8}{sign}{pct:>11.1f}%{flag}")
    print()

    best = ranking[0]
    if best != "fr":
        saving = (base - totals[best]) / base * 100
        print(f"Langue la plus économe : {LANG_NAMES[best]} "
              f"({saving:.1f}% de tokens en moins que le français).")
    else:
        print("Le français est déjà la plus économe sur cet échantillon.")
        return 0

    # --- Analyse économique : la traduction n'est pas gratuite ---
    tgt = totals[best]
    save_per_reuse = base - tgt  # tokens économisés à chaque envoi
    print()
    print("=== Faisabilité économique (le vrai juge) ===")
    print(f"Économie par envoi : {save_per_reuse} tokens d'entrée "
          f"({saving:.1f}%).")
    print()

    # Scénario A : contexte statique traduit UNE fois puis réutilisé/caché.
    # Coût unique ~= lire le FR + générer la trad (base + tgt tokens).
    overhead = base + tgt
    breakeven = overhead / save_per_reuse if save_per_reuse > 0 else float("inf")
    print("A) Contexte STATIQUE (ex: system prompt traduit 1 fois, réutilisé) :")
    print(f"   Coût unique de traduction ~= {overhead} tokens.")
    print(f"   Rentable à partir d'environ {breakeven:.0f} réutilisations.")
    print("   -> Faisable. MAIS le prompt caching économise ~90% sans rien")
    print("      traduire ni perdre en fidélité : presque toujours supérieur.")
    print()

    # Scénario B : aller-retour à CHAQUE message (FR->opti, réponse opti->FR).
    # Chaque message ajoute 2 traductions (entrée + sortie).
    print("B) ALLER-RETOUR par message (FR->langue, puis réponse->FR) :")
    print(f"   Chaque message ajoute 2 traductions (~{overhead}+ tokens) pour")
    print(f"   gagner {save_per_reuse} tokens. Verdict : JAMAIS rentable.")

    if not use_api:
        print()
        print("[i] Chiffres APPROXIMATIFS. Pour les valeurs exactes du tokenizer")
        print("    Claude, définis ANTHROPIC_API_KEY puis relance ce script.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
