"""Tests de la mise à jour par release (python serveur_recettes.py --maj) : python -m unittest discover -s tests

Un faux GitHub local sert l'API des releases et les fichiers bruts ; la copie du serveur est essayée dans un dossier temporaire."""
import contextlib
import io
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
from unittest import mock

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
                               "/raw/v9.9.9/generateur-recettes.html": b"<html>nouvelle page</html>",
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
        self.assertEqual(self.lire("generateur-recettes.html"), b"<html>nouvelle page</html>")
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
        self.assertEqual(self.lire("generateur-recettes.html"), b"<html>nouvelle page</html>")

    def test_pas_de_retour_en_arriere_sans_demande(self):
        """La version installée (1.0.0) est plus récente que la dernière release publiée (0.9.0) : rien n'est téléchargé."""
        FauxGithub.tag = "v0.9.0"
        code, sortie = self.lancer()
        self.assertEqual(code, 0, sortie)
        self.assertIn("plus récente", sortie)
        self.assertEqual(self.lire("serveur_recettes.py"), self.ancien.encode())
        self.assertEqual(self.lire("generateur-recettes.html"), "ancienne page".encode())

    def test_version_plus_ancienne_acceptee_si_demandee(self):
        FauxGithub.fichiers = {k.replace("v9.9.9", "v0.9.0"): v.replace(b"9.9.9", b"0.9.0") for k, v in FauxGithub.fichiers.items()}
        code, sortie = self.lancer("v0.9.0")
        self.assertEqual(code, 0, sortie)
        self.assertIn("Mise à jour terminée : v0.9.0", sortie)
        self.assertEqual(self.lire("generateur-recettes.html"), b"<html>nouvelle page</html>")

    def test_fichier_telecharge_invalide_ne_modifie_rien(self):
        """Python invalide, mauvaise version ou page qui n'est pas du HTML : refusé avant de toucher aux fichiers."""
        for nom, contenu, motif in (("serveur_recettes.py", b"VERSION = 'x'\ndef (", "invalide"),
                                    ("serveur_recettes.py", self.ancien.encode(), "pas v9.9.9"),
                                    ("generateur-recettes.html", b"erreur 404 en texte brut", "pas une page HTML")):
            with self.subTest(motif=motif):
                FauxGithub.fichiers["/raw/v9.9.9/" + nom] = contenu
                code, sortie = self.lancer()
                self.assertEqual(code, 1, sortie)
                self.assertIn("Mise à jour refusée", sortie)
                self.assertEqual(self.lire("serveur_recettes.py"), self.ancien.encode())
                self.assertEqual(self.lire("generateur-recettes.html"), "ancienne page".encode())
                FauxGithub.fichiers["/raw/v9.9.9/serveur_recettes.py"] = self.nouveau
                FauxGithub.fichiers["/raw/v9.9.9/generateur-recettes.html"] = b"<html>nouvelle page</html>"

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


class RetourArriere(unittest.TestCase):
    """Un échec au milieu des remplacements restaure les fichiers d'origine (test en processus, os.replace simulé en panne)."""

    def setUp(self):
        sys.path.insert(0, RACINE)
        import serveur_recettes
        self.s = serveur_recettes
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        for nom in ("serveur_recettes.py", "generateur-recettes.html", "pdf_recettes.py"):
            with open(os.path.join(self.dossier, nom), "w", encoding="utf-8") as f:
                f.write(f"ancien {nom}")
        FauxGithub.tag = "v9.9.9"
        FauxGithub.fichiers = {"/raw/v9.9.9/serveur_recettes.py": b'VERSION = "9.9.9"\n',
                               "/raw/v9.9.9/generateur-recettes.html": b"<html></html>",
                               "/raw/v9.9.9/pdf_recettes.py": b"x = 1\n"}
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FauxGithub)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        env = {"RECETTES_API": f"http://127.0.0.1:{self.srv.server_port}/api",
               "RECETTES_RAW": f"http://127.0.0.1:{self.srv.server_port}/raw"}
        for patcher in (mock.patch.dict(os.environ, env), mock.patch.object(serveur_recettes, "DIR", self.dossier),
                        mock.patch.object(serveur_recettes, "VERSION", "1.0.0"),
                        mock.patch.object(serveur_recettes, "EXECUTABLE", False)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def lire(self, nom):
        with open(os.path.join(self.dossier, nom), encoding="utf-8") as f:
            return f.read()

    def test_succes_remplace_les_trois_fichiers_sans_reste(self):
        self.assertEqual(self.s.mettre_a_jour(), 0)
        self.assertEqual(self.lire("serveur_recettes.py"), 'VERSION = "9.9.9"\n')
        self.assertEqual(self.lire("pdf_recettes.py"), "x = 1\n")
        self.assertEqual(sorted(os.listdir(self.dossier)), ["generateur-recettes.html", "pdf_recettes.py", "serveur_recettes.py"])

    def test_panne_au_deuxieme_remplacement_restaure_tout(self):
        vrai = os.replace
        appels = []

        def en_panne(source, cible):
            appels.append(cible)
            if len(appels) == 2:                          # le 1er fichier est déjà remplacé, le 2e échoue
                raise PermissionError("fichier verrouillé")
            return vrai(source, cible)

        with mock.patch.object(self.s.os, "replace", side_effect=en_panne):
            self.assertEqual(self.s.mettre_a_jour(), 1)
        for nom in ("serveur_recettes.py", "generateur-recettes.html", "pdf_recettes.py"):
            self.assertEqual(self.lire(nom), f"ancien {nom}", nom)
        self.assertEqual(sorted(os.listdir(self.dossier)), ["generateur-recettes.html", "pdf_recettes.py", "serveur_recettes.py"])

    def test_restauration_impossible_signalee_et_sauvegarde_gardee(self):
        """Si le retour en arrière échoue lui aussi, on ne prétend pas avoir tout restauré et la copie d'origine reste."""
        vrai = os.replace

        def en_panne(source, cible):
            if cible.endswith("generateur-recettes.html") and source.endswith(".tmp"):
                raise PermissionError("fichier verrouillé")          # le 2e remplacement échoue
            if source.endswith("serveur_recettes.py.bak"):
                raise PermissionError("verrouillé aussi pendant la restauration")
            return vrai(source, cible)

        sortie = io.StringIO()
        with mock.patch.object(self.s.os, "replace", side_effect=en_panne), contextlib.redirect_stdout(sortie):
            self.assertEqual(self.s.mettre_a_jour(), 1)
        texte = sortie.getvalue()
        self.assertIn("restauration incomplète", texte)
        self.assertIn("serveur_recettes.py n'a pas pu être restauré", texte)
        self.assertNotIn("ont été restaurés", texte)
        self.assertEqual(self.lire("serveur_recettes.py.bak"), "ancien serveur_recettes.py")     # seule copie gardée
        self.assertFalse(os.path.exists(os.path.join(self.dossier, "generateur-recettes.html.bak")))
        self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(self.dossier)))

    def test_fichier_facultatif_nouveau_supprime_au_retour_arriere(self):
        os.remove(os.path.join(self.dossier, "pdf_recettes.py"))          # absent avant la mise à jour
        vrai = os.replace
        appels = []

        def en_panne(source, cible):
            appels.append(cible)
            if len(appels) == 3:                          # le dernier (pdf_recettes.py) échoue après les deux autres
                raise PermissionError("verrouillé")
            return vrai(source, cible)

        with mock.patch.object(self.s.os, "replace", side_effect=en_panne):
            self.assertEqual(self.s.mettre_a_jour(), 1)
        self.assertEqual(self.lire("serveur_recettes.py"), "ancien serveur_recettes.py")
        self.assertFalse(os.path.exists(os.path.join(self.dossier, "pdf_recettes.py")))


if __name__ == "__main__":
    unittest.main()
