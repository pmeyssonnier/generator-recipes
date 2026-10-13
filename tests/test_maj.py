"""Tests de la mise à jour par release (python serveur_recettes.py --maj) : python -m unittest discover -s tests

Un faux GitHub local sert l'API des releases et les fichiers bruts ; la copie du serveur est essayée dans un dossier temporaire."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
VERSION_ACTUELLE = "1.0.0"


class FauxGithub(BaseHTTPRequestHandler):
    fichiers = {}            # chemin -> contenu (octets)
    tag = "v9.9.9"

    def do_GET(self):
        if self.path == "/api/releases/latest":
            corps = json.dumps({"tag_name": self.tag}).encode()
        elif self.path in self.fichiers:
            corps = self.fichiers[self.path]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *a):
        pass


class MiseAJour(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        with open(os.path.join(RACINE, "serveur_recettes.py"), encoding="utf-8") as f:
            source = f.read()
        self.ancien = re.sub(r'^VERSION = "[^"]+"', f'VERSION = "{VERSION_ACTUELLE}"', source, count=1, flags=re.M)
        with open(os.path.join(self.dossier, "serveur_recettes.py"), "w", encoding="utf-8") as f:
            f.write(self.ancien)
        for nom, texte in (("generateur-recettes.html", "ancienne page"), ("recettes.json", "[]")):
            with open(os.path.join(self.dossier, nom), "w", encoding="utf-8") as f:
                f.write(texte)
        self.nouveau = self.ancien.replace(f'VERSION = "{VERSION_ACTUELLE}"', 'VERSION = "9.9.9"').encode()
        FauxGithub.tag = "v9.9.9"
        FauxGithub.fichiers = {"/raw/v9.9.9/serveur_recettes.py": self.nouveau,
                               "/raw/v9.9.9/generateur-recettes.html": b"nouvelle page",
                               "/raw/v9.9.9/pdf_recettes.py": b"# module pdf"}
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FauxGithub)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.env = dict(os.environ, RECETTES_API=f"http://127.0.0.1:{self.srv.server_port}/api",
                        RECETTES_RAW=f"http://127.0.0.1:{self.srv.server_port}/raw")
        self.env.pop("RECETTES_VERSION", None)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.dossier, ignore_errors=True)

    def lancer(self, *args):
        r = subprocess.run([sys.executable, "-I", "serveur_recettes.py", "--maj", *args], cwd=self.dossier, env=self.env,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout

    def lire(self, nom):
        with open(os.path.join(self.dossier, nom), "rb") as f:
            return f.read()

    def test_derniere_release_installee(self):
        code, sortie = self.lancer()
        self.assertEqual(code, 0, sortie)
        self.assertIn("Mise à jour terminée : v9.9.9", sortie)
        self.assertEqual(self.lire("serveur_recettes.py"), self.nouveau)
        self.assertEqual(self.lire("generateur-recettes.html"), b"nouvelle page")
        self.assertEqual(self.lire("pdf_recettes.py"), b"# module pdf")
        self.assertEqual(self.lire("recettes.json"), b"[]", "la base n'est pas touchée")
        self.assertFalse([n for n in os.listdir(self.dossier) if n.endswith(".tmp")])

    def test_deja_a_jour(self):
        FauxGithub.tag = f"v{VERSION_ACTUELLE}"
        code, sortie = self.lancer()
        self.assertEqual(code, 0)
        self.assertIn("Déjà à jour", sortie)
        self.assertEqual(self.lire("generateur-recettes.html"), "ancienne page".encode())

    def test_echec_d_un_fichier_ne_modifie_rien(self):
        del FauxGithub.fichiers["/raw/v9.9.9/generateur-recettes.html"]
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn("Rien n'a été modifié", sortie)
        self.assertEqual(self.lire("serveur_recettes.py"), self.ancien.encode())
        self.assertEqual(self.lire("generateur-recettes.html"), "ancienne page".encode())

    def test_module_pdf_facultatif(self):
        del FauxGithub.fichiers["/raw/v9.9.9/pdf_recettes.py"]
        code, sortie = self.lancer()
        self.assertEqual(code, 0, sortie)
        self.assertIn("pdf_recettes.py absent", sortie)
        self.assertEqual(self.lire("generateur-recettes.html"), b"nouvelle page")

    def test_version_imposee_et_version_invalide(self):
        FauxGithub.fichiers = {k.replace("v9.9.9", "main"): v for k, v in FauxGithub.fichiers.items()}
        code, sortie = self.lancer("main")
        self.assertEqual(code, 0, sortie)
        self.assertIn("Mise à jour terminée : main", sortie)
        code, sortie = self.lancer("../etc")
        self.assertEqual(code, 1)
        self.assertIn("invalide", sortie)

    def test_reseau_indisponible(self):
        self.env["RECETTES_API"] = "http://127.0.0.1:9/api"
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn("Rien n'a été modifié", sortie)
        self.assertEqual(self.lire("generateur-recettes.html"), "ancienne page".encode())


if __name__ == "__main__":
    unittest.main()
