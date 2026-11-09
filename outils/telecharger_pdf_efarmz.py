"""Télécharge les PDF de fiches recettes eFarmz (v###.pdf, l###.pdf, p###.pdf) pour les déposer dans eFarmz/.

Prévu pour Google Colab (un zip est proposé en téléchargement) ; fonctionne aussi en ligne de commande :
    python outils/telecharger_pdf_efarmz.py [--prefixes vlp] [--de 0] [--a 999] [--dossier pdf_efarmz]
Seul le téléchargement est fait : l'extraction des recettes reste dans le carnet (source « eFarmz (PDF) »).
Les PDF déjà présents ne sont pas retéléchargés (reprise après interruption). Réservé à un usage personnel."""
import argparse
import os
import shutil
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://cdn.efarmz.be/recipes/FR/{}.pdf"


def telecharger(code, dossier, pause):
    """(code, chemin) du PDF, ou (code, None) s'il n'existe pas ou n'est pas lisible."""
    chemin = os.path.join(dossier, f"{code}.pdf")
    if os.path.exists(chemin):
        return code, chemin
    time.sleep(pause)
    req = urllib.request.Request(BASE.format(code), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            donnees = r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (403, 404):
            print(f"⚠ {code} : HTTP {e.code}")
        return code, None
    except Exception as e:
        print(f"⚠ {code} : {type(e).__name__}")
        return code, None
    if not donnees.startswith(b"%PDF"):
        return code, None
    with open(chemin, "wb") as f:
        f.write(donnees)
    return code, chemin


def telecharger_tout(prefixes="vlp", de=0, a=999, dossier="pdf_efarmz", fils=4, pause=0.3):
    os.makedirs(dossier, exist_ok=True)
    codes = [f"{p}{n:03d}" for p in prefixes for n in range(de, a + 1)]
    print(f"{len(codes)} adresses à essayer…")
    with ThreadPoolExecutor(fils) as ex:
        trouves = [c for c, ch in ex.map(lambda c: telecharger(c, dossier, pause), codes) if ch]
    print(f"{len(trouves)} PDF trouvés : {trouves}")
    return trouves


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefixes", default="vlp")
    ap.add_argument("--de", type=int, default=0)
    ap.add_argument("--a", type=int, default=999)
    ap.add_argument("--dossier", default="pdf_efarmz")
    ap.add_argument("--fils", type=int, default=4, help="1 ou 2 si le site refuse (429)")
    ap.add_argument("--pause", type=float, default=0.3)
    a = ap.parse_args()
    trouves = telecharger_tout(a.prefixes, a.de, a.a, a.dossier, a.fils, a.pause)
    if trouves:
        shutil.make_archive(a.dossier, "zip", a.dossier)
        print(f"Archive : {a.dossier}.zip")
        try:                                              # sous Colab : téléchargement direct
            from google.colab import files
            files.download(f"{a.dossier}.zip")
        except ImportError:
            pass
