"""Tests de tester_sources.py : python -m unittest discover -s tests"""
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import serveur_recettes as s  # noqa: E402
import tester_sources as t  # noqa: E402
from unittest import mock  # noqa: E402


class TesterSources(unittest.TestCase):
    def lancer(self, sources):
        lignes = []
        with mock.patch.object(s, "scrape_recipe", return_value={"nom": "Quiche", "ingredients": ["a"], "etapes": ["b"]}):
            ok = t.tester("quiche", sources, sortie=lignes.append)
        return ok, "\n".join(lignes)

    def test_source_dossier_ignoree_et_source_web_testee(self):
        ok, sortie = self.lancer({"efarmz": {"nom": "eFarmz", "dossier": True,
                                              "chercher": lambda q, n: 1 / 0},          # ne doit jamais être appelée
                                  "web": {"nom": "Web", "chercher": lambda q, n: [{"url": "https://exemple.org/r"}]}})
        self.assertTrue(ok, sortie)
        self.assertIn("ignorée", sortie)
        self.assertIn("✓ Web", sortie)

    def test_source_web_en_echec_fait_echouer(self):
        ok, sortie = self.lancer({"web": {"nom": "Web", "chercher": lambda q, n: []}})
        self.assertFalse(ok)
        self.assertIn("aucun résultat", sortie)

    def test_les_vraies_sources_declarent_leur_nature(self):
        self.assertTrue(s.SOURCES["efarmz"]["dossier"])
        self.assertFalse(any(src.get("dossier") for sid, src in s.SOURCES.items() if sid != "efarmz"))


if __name__ == "__main__":
    unittest.main()


class ChangerVersion(unittest.TestCase):
    """outils/changer_version.py : un seul endroit à modifier, tout reste cohérent."""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outils"))
        import changer_version
        self.cv = changer_version
        racine = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for nom in ("serveur_recettes.py", "generateur-recettes.html", "CHANGELOG.md"):
            shutil.copy(os.path.join(racine, nom), self.tmp)

    def lire(self, nom):
        with open(os.path.join(self.tmp, nom), encoding="utf-8", newline="") as f:
            return f.read()

    def test_change_les_trois_fichiers(self):
        ancienne = self.cv.changer(self.tmp, "9.8.7", "2030-01-02")
        self.assertEqual(ancienne, s.VERSION)
        self.assertIn('VERSION = "9.8.7"', self.lire("serveur_recettes.py"))
        page = self.lire("generateur-recettes.html")
        self.assertIn('const VERSION = "9.8.7";', page)
        self.assertIn(">v9.8.7</small>", page)
        journal = self.lire("CHANGELOG.md")
        self.assertRegex(journal, r"(?m)^## \[Non publié\]\n\n## \[9\.8\.7\] - 2030-01-02\n")
        self.assertIn("releases/tag/v9.8.7", journal)
        self.assertIn("compare/v9.8.7...HEAD", journal)
        self.assertEqual(len(re.findall(r"(?m)^\[Non publié\]:", journal)), 1)

    def test_refus_sans_rien_modifier(self):
        avant = {n: self.lire(n) for n in ("serveur_recettes.py", "generateur-recettes.html", "CHANGELOG.md")}
        for mauvaise in ("1.7", "v1.7.0", "01.2.3", s.VERSION, "0.0.1"):
            with self.assertRaises(SystemExit):
                self.cv.changer(self.tmp, mauvaise, "2030-01-02")
        with self.assertRaises(SystemExit):
            self.cv.changer(self.tmp, "99.0.0", "demain")
        self.assertEqual(avant, {n: self.lire(n) for n in avant})
