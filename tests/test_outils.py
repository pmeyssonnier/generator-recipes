"""Tests de tester_sources.py : python -m unittest discover -s tests"""
import os
import sys
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
