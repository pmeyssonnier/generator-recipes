"""Change le numéro de version partout, en une commande : python outils/changer_version.py 1.7.0 [AAAA-MM-JJ]

Met à jour serveur_recettes.py (VERSION), generateur-recettes.html (constante et en-tête) et CHANGELOG.md
(la section « [Non publié] » devient « [1.7.0] - date », une section « [Non publié] » vide est recréée et les
liens du bas sont mis à jour). Les tests (tests/test_version.py) vérifient ensuite la cohérence."""
import datetime
import os
import re
import sys

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
DEPOT = "https://github.com/pmeyssonnier/generator-recipes"


def _lire(racine, nom):
    with open(os.path.join(racine, nom), encoding="utf-8", newline="") as f:
        return f.read()


def _ecrire(racine, nom, texte):
    with open(os.path.join(racine, nom), "w", encoding="utf-8", newline="") as f:
        f.write(texte)


def _une_fois(motif, remplacement, texte, nom, flags=0):
    resultat, n = re.subn(motif, remplacement, texte, flags=flags)
    if n != 1:
        raise SystemExit(f"✗ {nom} : motif {motif!r} trouvé {n} fois (une seule attendue). Rien n'a été modifié.")
    return resultat


def changer(racine, nouvelle, date=None):
    """Applique la nouvelle version ; tout est calculé avant la première écriture. Renvoie l'ancienne version."""
    if not SEMVER.match(nouvelle):
        raise SystemExit(f"✗ Version invalide : {nouvelle!r} (attendu MAJEUR.MINEUR.CORRECTIF, ex. 1.7.0)")
    date = date or datetime.date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise SystemExit(f"✗ Date invalide : {date!r} (attendu AAAA-MM-JJ)")
    serveur = _lire(racine, "serveur_recettes.py")
    ancienne = re.search(r'^VERSION = "([^"]+)"', serveur, re.M).group(1)
    cle = lambda v: tuple(map(int, v.split(".")))                                   # noqa: E731
    if cle(nouvelle) <= cle(ancienne):
        raise SystemExit(f"✗ {nouvelle} n'est pas postérieure à la version actuelle ({ancienne}).")

    serveur = _une_fois(r'^VERSION = "[^"]+"', f'VERSION = "{nouvelle}"', serveur, "serveur_recettes.py", re.M)
    page = _lire(racine, "generateur-recettes.html")
    page = _une_fois(r'const VERSION = "[^"]+";', f'const VERSION = "{nouvelle}";', page, "generateur-recettes.html")
    page = _une_fois(r'(<small class="version"[^>]*>)v[^<]+(</small>)', rf"\g<1>v{nouvelle}\g<2>", page,
                     "generateur-recettes.html")
    journal = _lire(racine, "CHANGELOG.md")
    journal = _une_fois(r"^## \[Non publié\]\n", f"## [Non publié]\n\n## [{nouvelle}] - {date}\n", journal,
                        "CHANGELOG.md", re.M)
    journal = _une_fois(r"^\[Non publié\]: .*$",
                        f"[Non publié]: {DEPOT}/compare/v{nouvelle}...HEAD\n"
                        f"[{nouvelle}]: {DEPOT}/releases/tag/v{nouvelle}", journal, "CHANGELOG.md", re.M)
    _ecrire(racine, "serveur_recettes.py", serveur)
    _ecrire(racine, "generateur-recettes.html", page)
    _ecrire(racine, "CHANGELOG.md", journal)
    return ancienne


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    avant = changer(RACINE, sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None)
    print(f"✓ {avant} → {sys.argv[1]} : serveur_recettes.py, generateur-recettes.html, CHANGELOG.md")
    print("  Reste à : compléter la section du CHANGELOG, lancer les tests, ouvrir la PR.")
