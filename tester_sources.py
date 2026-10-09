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

terme = " ".join(sys.argv[1:]) or "lasagnes"
print(f"Test des sources avec « {terme} »\n")
ok = True
for sid, src in s.SOURCES.items():
    try:
        res = src["chercher"](terme, 3)
        if not res:
            print(f"✗ {src['nom']:<10} aucun résultat")
            ok = False
            continue
        r = s.scrape_recipe(res[0]["url"])
        print(f"✓ {src['nom']:<10} {len(res)} résultat(s) — « {r['nom']} », "
              f"{len(r['ingredients'])} ingrédients, {len(r['etapes'])} étapes")
    except s.AccesInterdit as e:
        print(f"⛔ {src['nom']:<10} {e}")
        ok = False
    except Exception as e:
        print(f"✗ {src['nom']:<10} {type(e).__name__} : {e}")
        ok = False

print("\nToutes les sources fonctionnent." if ok else "\nAu moins une source pose problème.")
sys.exit(0 if ok else 1)
