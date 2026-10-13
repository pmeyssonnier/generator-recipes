"""Essai de fumée d'un exécutable construit par construire_exe.py :

    python outils/essai_exe.py recettes-vX.Y.Z.exe

Le lance dans un dossier vide (avec un PDF de test dans eFarmz/), puis vérifie : version, page servie,
lecture du PDF avec photo (pdfplumber embarqué), import dans recettes.json créé à côté de l'exécutable."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PDF = os.path.join(RACINE, "tests", "fixtures", "fiches.pdf")
PORT = 8791


def appeler(chemin, post=False):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{chemin}", method="POST" if post else "GET",
                                 headers={"X-Recettes": "1"} if post else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def verifier(condition, message):
    if not condition:
        raise SystemExit(f"✗ {message}")
    print(f"✓ {message}")


def main(exe):
    dossier = tempfile.mkdtemp()
    serveur = None
    try:
        copie = os.path.join(dossier, os.path.basename(exe))
        shutil.copyfile(exe, copie)
        os.chmod(copie, 0o755)
        os.makedirs(os.path.join(dossier, "eFarmz"))
        shutil.copyfile(PDF, os.path.join(dossier, "eFarmz", "v375.pdf"))
        env = dict(os.environ, RECETTES_PORT=str(PORT))
        sortie = subprocess.run([copie, "--version"], cwd=dossier, env=env, capture_output=True, text=True, timeout=120).stdout
        verifier("serveur_recettes " in sortie, f"--version : {sortie.strip()}")

        journal = open(os.path.join(dossier, "journal.txt"), "w", encoding="utf-8")
        serveur = subprocess.Popen([copie, "--no-browser"], cwd=dossier, env=env, stdout=journal, stderr=subprocess.STDOUT)
        for _ in range(120):
            try:
                ping = json.loads(appeler("/api/ping"))
                break
            except (urllib.error.URLError, ConnectionError, OSError):
                if serveur.poll() is not None:
                    journal.flush()
                    raise SystemExit(f"✗ le serveur s'est arrêté (code {serveur.returncode}) :\n" + open(journal.name, encoding="utf-8").read())
                time.sleep(1)
        else:
            raise SystemExit("✗ le serveur ne répond pas")
        verifier(ping.get("ok"), f"/api/ping répond (version {ping.get('version')})")
        page = appeler("/").decode("utf-8")
        verifier("Générateur de recettes" in page, "la page embarquée est servie")
        res = json.loads(appeler("/api/search?source=efarmz"))
        recettes = [x for x in res if x.get("url")]
        verifier(len(recettes) == 4, f"{len(recettes)} recettes lues dans le PDF (pdfplumber embarqué)")
        verifier(recettes[0]["image"].startswith("data:image/jpeg"), "la photo est extraite")
        appeler("/api/recipe?" + urllib.parse.urlencode({"url": recettes[0]["url"]}), post=True)
        base = os.path.join(dossier, "recettes.json")
        verifier(os.path.exists(base) and len(json.load(open(base, encoding="utf-8"))) == 1,
                 "recettes.json créé à côté de l'exécutable avec la recette importée")
    finally:
        if serveur and serveur.poll() is None:
            serveur.terminate()
            try:
                serveur.wait(10)
            except subprocess.TimeoutExpired:
                serveur.kill()
        shutil.rmtree(dossier, ignore_errors=True)
    print("Exécutable OK")


if __name__ == "__main__":
    for flux in (sys.stdout, sys.stderr):                    # console Windows (cp1252) : jamais d'erreur d'encodage
        flux.reconfigure(errors="replace")
    main(os.path.abspath(sys.argv[1]))
