"""La version est unique et cohérente : serveur, page, journal des changements (python -m unittest)."""
import json
import os
import re
import sys
import threading
import unittest
import urllib.request

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, RACINE)
import serveur_recettes as s  # noqa: E402

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def lire(nom):
    with open(os.path.join(RACINE, nom), encoding="utf-8") as f:
        return f.read()


class Version(unittest.TestCase):
    def test_version_semver(self):
        self.assertRegex(s.VERSION, SEMVER)

    def test_la_page_annonce_la_meme_version(self):
        html = lire("generateur-recettes.html")
        self.assertIn(f'const VERSION = "{s.VERSION}";', html, "constante VERSION de la page")
        self.assertIn(f">v{s.VERSION}</small>", html, "numéro affiché dans l'en-tête")

    def test_le_journal_contient_la_version(self):
        journal = lire("CHANGELOG.md")
        self.assertRegex(journal, rf"(?m)^## \[{re.escape(s.VERSION)}\] - \d{{4}}-\d{{2}}-\d{{2}}$",
                         f"CHANGELOG.md n'a pas de section « ## [{s.VERSION}] - AAAA-MM-JJ »")
        self.assertIn("## [Non publié]", journal)
        self.assertIn(f"[{s.VERSION}]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v{s.VERSION}", journal)

    def test_le_journal_est_dans_l_ordre(self):
        versions = re.findall(r"(?m)^## \[(\d+\.\d+\.\d+)\]", lire("CHANGELOG.md"))
        triees = sorted(versions, key=lambda v: tuple(map(int, v.split("."))), reverse=True)
        self.assertEqual(versions, triees, "les versions doivent aller de la plus récente à la plus ancienne")
        self.assertEqual(versions[0], s.VERSION, "la section la plus récente est la version courante")

    def test_user_agent_porte_la_version(self):
        self.assertIn(f"RecettesPerso/{s.VERSION}", s.HEADERS["User-Agent"])

    def test_ping_annonce_la_version(self):
        srv = s.ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/ping") as r:
            corps = json.load(r)
        self.assertEqual(corps["version"], s.VERSION)
        self.assertIsInstance(corps["api"], int)

    def test_option_version(self):
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(RACINE, "serveur_recettes.py"), "--version"],
                           capture_output=True, text=True, timeout=20)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, f"serveur_recettes {s.VERSION}"))


if __name__ == "__main__":
    unittest.main()
