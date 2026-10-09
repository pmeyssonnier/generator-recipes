"""Tests hors ligne du script Colab (réutilise serveur_recettes.py) : python -m unittest discover -s tests"""
import json
import os
import runpy
import tempfile
import unittest
from unittest import mock

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
import sys  # noqa: E402
sys.path.insert(0, RACINE)
import serveur_recettes as srv  # noqa: E402


def page(recette):
    return f'<script type="application/ld+json">{json.dumps(recette)}</script>'


def charger_script():
    """Exécute le script Colab (hors bloc __main__). Le module serveur est déjà présent : aucun téléchargement."""
    ancien = os.getcwd()
    os.chdir(RACINE)
    try:
        return runpy.run_path(os.path.join(RACINE, "colab", "import_recettes_colab.py"), run_name="colab_test")
    finally:
        os.chdir(ancien)


class Colab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = charger_script()

    def test_meme_extraction_que_le_serveur(self):
        self.assertIs(self.g["scrape_recipe"], srv.scrape_recipe)

    def test_generer_notes_avec_virgule_et_accents(self):
        recettes = [
            {"nom": "A", "ingredients": ["500 g de veau", "crème fraîche"], "note": "4,5", "total_min": 60},
            {"nom": "B", "ingredients": ["500 g de VEAU", "carottes"], "note": "4.2", "total_min": 90},
            {"nom": "C", "ingredients": ["veau"], "note": None, "total_min": None},
            {"nom": "D", "ingredients": ["poulet"], "note": "5", "total_min": 10},
        ]
        gen = self.g["generer"]
        self.assertEqual([r["nom"] for r in gen(recettes, avec=["VEAU"], n=5)], ["A", "B", "C"])
        self.assertEqual([r["nom"] for r in gen(recettes, avec=["veau"], sans=["creme"], n=5)], ["B", "C"])
        self.assertEqual([r["nom"] for r in gen(recettes, avec=["veau"], max_min=75, n=5)], ["A"])

    def test_import_ajoute_a_la_base_sans_doublon(self):
        recette = {"@type": "Recipe", "name": "Tarte &amp; crème : la meilleure recette",
                   "recipeIngredient": ["2 oeufs &amp; du sucre"]}
        url = "https://www.marmiton.org/recettes/recette_tarte_1.aspx"
        recherche = [{"url": url, "titre": "Tarte"}]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(srv, "BASE_FILE", os.path.join(d, "recettes.json")), \
                mock.patch.object(srv, "fetch", return_value=page(recette)), \
                mock.patch.object(srv, "search_recipes", return_value=recherche):
            r1 = self.g["import_recipes"]("tarte", 5)
            self.g["import_recipes"]("tarte", 5)                  # 2e import : fusion par URL
            base = self.g["charger_base"]()
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(base), 1)
        self.assertEqual(base[0]["nom"], "Tarte & crème")
        self.assertEqual(base[0]["ingredients"], ["2 oeufs & du sucre"])

    def test_echecs_ignores(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(srv, "BASE_FILE", os.path.join(d, "recettes.json")), \
                mock.patch.object(srv, "fetch", side_effect=[ValueError("Pas de données Recipe"), OSError("délai")]):
            res = self.g["_importer"](["https://www.marmiton.org/a", "https://www.marmiton.org/b"])
        self.assertEqual(res, [])

    def test_site_non_autorise(self):
        with self.assertRaises(ValueError):
            self.g["import_url"]("https://evil.example/recette")
        with self.assertRaises(ValueError):
            self.g["import_page"]("http://127.0.0.1/")


if __name__ == "__main__":
    unittest.main()
