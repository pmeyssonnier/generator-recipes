#!/usr/bin/env python3
"""
tester_sources.py — Vérifie que chaque source de recherche fonctionne encore.

  python tester_sources.py            → teste avec « lasagnes »
  python tester_sources.py quiche     → teste avec un autre terme

Pour chaque source : recherche, puis import de la première recette trouvée.
Respecte les mêmes règles que le serveur (robots.txt, pause entre requêtes).
Code de sortie 0 si toutes les sources répondent, 1 sinon.
"""
import sys

import serveur_recettes as s


def tester(terme, sources=None, sortie=print):
    """Teste chaque source web ; les sources « dossier » (eFarmz : PDF locaux) n'ont pas de site à interroger.
    Renvoie True si toutes les sources testées répondent."""
    ok = True
    for sid, src in (sources if sources is not None else s.SOURCES).items():
        if src.get("dossier"):
            sortie(f"- {src['nom']:<10} source locale (PDF du dossier) : ignorée")
            continue
        try:
            res = src["chercher"](terme, 3)
            if not res:
                sortie(f"✗ {src['nom']:<10} aucun résultat")
                ok = False
                continue
            r = s.scrape_recipe(res[0]["url"])
            sortie(f"✓ {src['nom']:<10} {len(res)} résultat(s) — « {r['nom']} », "
                   f"{len(r['ingredients'])} ingrédients, {len(r['etapes'])} étapes")
        except s.AccesInterdit as e:
            sortie(f"⛔ {src['nom']:<10} {e}")
            ok = False
        except Exception as e:
            sortie(f"✗ {src['nom']:<10} {type(e).__name__} : {e}")
            ok = False
    return ok


if __name__ == "__main__":
    terme = " ".join(sys.argv[1:]) or "lasagnes"
    print(f"Test des sources avec « {terme} »\n")
    ok = tester(terme)
    print("\nToutes les sources fonctionnent." if ok else "\nAu moins une source pose problème.")
    sys.exit(0 if ok else 1)
