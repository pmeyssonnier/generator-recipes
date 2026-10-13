"""Construit l'archive à distribuer : python outils/construire_archive.py [dossier_de_sortie]

Produit recettes-vMAJEUR.MINEUR.CORRECTIF.zip : le serveur, la page, l'extraction de PDF, les lanceurs
(Windows, macOS, Linux) et un mode d'emploi. Aucune dépendance (bibliothèque standard)."""
import os
import re
import sys
import zipfile

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DOSSIER_ARCHIVE = "recettes"
FICHIERS = [                                    # (source, nom dans l'archive, exécutable)
    ("serveur_recettes.py", "serveur_recettes.py", False),
    ("pdf_recettes.py", "pdf_recettes.py", False),
    ("generateur-recettes.html", "generateur-recettes.html", False),
    ("lancer-recettes.bat", "lancer-recettes.bat", False),
    ("pc/lancer-recettes.sh", "lancer-recettes.sh", True),
    ("pc/lancer-recettes.command", "lancer-recettes.command", True),
    ("pc/LISEZMOI-eFarmz.txt", "eFarmz/LISEZMOI.txt", False),
    ("LICENSE", "LICENSE", False),
]


def version():
    texte = open(os.path.join(RACINE, "serveur_recettes.py"), encoding="utf-8").read()
    return re.search(r'^VERSION = "([^"]+)"', texte, re.M).group(1)


def lire(chemin):
    with open(os.path.join(RACINE, chemin), "rb") as f:
        return f.read()


def ajouter(z, nom, contenu, executable=False):
    info = zipfile.ZipInfo(f"{DOSSIER_ARCHIVE}/{nom}", date_time=(2026, 1, 1, 0, 0, 0))   # date fixe : archive reproductible
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3                                                                # Unix : conserve les droits
    info.external_attr = (0o755 if executable else 0o644) << 16
    z.writestr(info, contenu)


def construire(sortie="."):
    v = version()
    chemin = os.path.join(sortie, f"recettes-v{v}.zip")
    with zipfile.ZipFile(chemin, "w") as z:
        for source, nom, executable in FICHIERS:
            contenu = lire(source)
            if nom.endswith((".sh", ".command")):
                contenu = contenu.replace(b"\r\n", b"\n")                                 # fins de ligne Unix
            if nom.endswith(".bat"):
                contenu = contenu.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")        # Windows : CRLF
            ajouter(z, nom, contenu, executable)
        ajouter(z, "LISEZMOI.txt", lire("pc/LISEZMOI.txt").decode("utf-8").replace("{VERSION}", v).encode("utf-8"))
    return chemin


if __name__ == "__main__":
    print(construire(sys.argv[1] if len(sys.argv) > 1 else "."))
