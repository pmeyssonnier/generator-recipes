"""Construit recettes-vX.Y.Z.exe (un seul fichier, Python et pdfplumber embarqués) avec PyInstaller.

    python -m pip install pyinstaller pdfplumber
    python outils/construire_exe.py [dossier_de_sortie]

À lancer sous Windows pour obtenir un .exe Windows (la CI le fait ; voir release.yml). La base recettes.json et le dossier
eFarmz/ sont créés à côté du .exe ; la page HTML est embarquée."""
import os
import shutil
import sys
import tempfile

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(RACINE, "outils"))
from construire_archive import version  # noqa: E402


def construire(sortie="."):
    import PyInstaller.__main__ as pyinstaller
    v = version()
    travail = tempfile.mkdtemp()
    try:
        pyinstaller.run([
            os.path.join(RACINE, "serveur_recettes.py"),
            "--onefile", "--name", "recettes", "--noconfirm", "--clean",
            "--distpath", os.path.join(travail, "dist"), "--workpath", os.path.join(travail, "build"),
            "--specpath", travail,
            "--paths", RACINE,
            "--add-data", os.path.join(RACINE, "generateur-recettes.html") + os.pathsep + ".",
            "--hidden-import", "pdf_recettes",
            "--collect-all", "pdfplumber", "--collect-all", "pdfminer", "--collect-all", "pypdfium2",
        ])
        fichier = "recettes.exe" if sys.platform == "win32" else "recettes"
        cible = os.path.join(sortie, f"recettes-v{v}.exe" if sys.platform == "win32" else f"recettes-v{v}-{sys.platform}")
        shutil.copyfile(os.path.join(travail, "dist", fichier), cible)
        return cible
    finally:
        shutil.rmtree(travail, ignore_errors=True)


if __name__ == "__main__":
    print(construire(sys.argv[1] if len(sys.argv) > 1 else "."))
