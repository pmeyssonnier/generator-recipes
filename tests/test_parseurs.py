"""Tests hors ligne des parseurs (JSON-LD, listes de recettes, sources) : pages HTML figées."""
import json
import os
import sys
import unittest
from unittest import mock
from urllib.error import HTTPError

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import serveur_recettes as s  # noqa: E402


def page_ld(*blocs):
    """Page HTML contenant des blocs JSON-LD (dict → sérialisé, str → tel quel)."""
    scripts = "".join(
        f'<script type="application/ld+json">{b if isinstance(b, str) else json.dumps(b)}</script>'
        for b in blocs)
    return f"<html><head>{scripts}</head><body></body></html>"


RECETTE = {
    "@type": "Recipe", "name": "Blanquette de veau : la meilleure recette",
    "recipeCategory": "Plat principal", "recipeCuisine": "Française", "recipeYield": ["6 personnes", "6"],
    "prepTime": "PT30M", "cookTime": "PT1H30M", "totalTime": "PT2H",
    "aggregateRating": {"ratingValue": "4.7", "ratingCount": 812},
    "recipeIngredient": ["800 g de veau", "2 carottes &amp; 1 oignon"],
    "recipeInstructions": [
        {"@type": "HowToStep", "text": "Couper la viande."},
        {"@type": "HowToSection", "itemListElement": [{"@type": "HowToStep", "text": "Mijoter &amp; servir."}]},
    ],
    "keywords": "veau, mijoté", "image": [{"url": "https://img.example/a.jpg"}],
}


class Nettoyage(unittest.TestCase):
    def test_nettoyer_nom(self):
        self.assertEqual(s.nettoyer_nom("Poulet rôti : la meilleure recette"), "Poulet rôti")
        self.assertEqual(s.nettoyer_nom("Poulet rôti : La Meilleure Recette  "), "Poulet rôti")
        self.assertEqual(s.nettoyer_nom("Tarte &amp; crème"), "Tarte & crème")
        self.assertEqual(s.nettoyer_nom(None), "")

    def test_slugifier(self):
        self.assertEqual(s.slugifier("Poulet au curry"), "poulet-au-curry")
        self.assertEqual(s.slugifier("  Crème brûlée !  "), "creme-brulee")


class JsonLd(unittest.TestCase):
    def test_find_recipe_obj_formes(self):
        r = {"@type": "Recipe", "name": "x"}
        self.assertIs(s.find_recipe_obj(r), r)
        self.assertIs(s.find_recipe_obj([{"@type": "WebSite"}, r]), r)
        self.assertIs(s.find_recipe_obj({"@graph": [{"@type": "Person"}, r]}), r)
        multi = {"@type": ["Thing", "Recipe"]}
        self.assertIs(s.find_recipe_obj(multi), multi)
        self.assertIsNone(s.find_recipe_obj({"@type": "Article"}))
        self.assertIsNone(s.find_recipe_obj("texte"))

    def test_flatten_instructions(self):
        self.assertEqual(s.flatten_instructions("a\n\nb\n"), ["a", "b"])
        self.assertEqual(s.flatten_instructions(["a", " b "]), ["a", "b"])
        sections = [{"@type": "HowToSection", "itemListElement": [{"text": "1"}, {"name": "2"}]}, {"text": "3"}]
        self.assertEqual(s.flatten_instructions(sections), ["1", "2", "3"])
        self.assertEqual(s.flatten_instructions(None), [])
        self.assertEqual(s.flatten_instructions([{"@type": "HowToStep"}]), [])

    def test_first_image(self):
        self.assertEqual(s.first_image("u"), "u")
        self.assertEqual(s.first_image(["u", "v"]), "u")
        self.assertEqual(s.first_image({"url": "u"}), "u")
        self.assertEqual(s.first_image([{"url": "u"}]), "u")
        self.assertIsNone(s.first_image([]))
        self.assertIsNone(s.first_image(None))


class ScrapeRecipe(unittest.TestCase):
    URL = "https://www.marmiton.org/recettes/recette_blanquette_1.aspx"

    def scrape(self, html, url=None):
        with mock.patch.object(s, "fetch", return_value=html):
            return s.scrape_recipe(url or self.URL)

    def test_recette_complete(self):
        r = self.scrape(page_ld(RECETTE))
        self.assertEqual(r["nom"], "Blanquette de veau")
        self.assertEqual(r["source"], "marmiton.org")
        self.assertEqual((r["prep_min"], r["cuisson_min"], r["total_min"]), (30, 90, 120))
        self.assertEqual(r["portions"], "6 personnes")
        self.assertEqual((r["note"], r["nb_avis"]), ("4.7", 812))
        self.assertEqual(r["ingredients"], ["800 g de veau", "2 carottes & 1 oignon"])
        self.assertEqual(r["etapes"], ["Couper la viande.", "Mijoter & servir."])
        self.assertEqual(r["image"], "https://img.example/a.jpg")
        self.assertEqual(r["url"], self.URL)

    def test_champs_absents(self):
        r = self.scrape(page_ld({"@type": "Recipe", "name": "Minimal"}))
        self.assertEqual(r["nom"], "Minimal")
        self.assertEqual(r["ingredients"], [])
        self.assertEqual(r["etapes"], [])
        self.assertIsNone(r["note"])
        self.assertIsNone(r["total_min"])
        self.assertIsNone(r["image"])

    def test_bloc_invalide_ignore_puis_graph(self):
        html = page_ld("{pas du json", {"@graph": [{"@type": "WebPage"}, RECETTE]})
        self.assertEqual(self.scrape(html)["nom"], "Blanquette de veau")

    def test_json_ld_html_echappe(self):
        bloc = json.dumps({"@type": "Recipe", "name": "Tarte"}).replace('"', "&quot;")
        self.assertEqual(self.scrape(page_ld(bloc))["nom"], "Tarte")

    def test_pas_de_recette(self):
        with self.assertRaisesRegex(ValueError, "Pas de données Recipe"):
            self.scrape(page_ld({"@type": "Article"}))
        with self.assertRaisesRegex(ValueError, "Pas de données Recipe"):
            self.scrape("<html>rien</html>")


class Sites(unittest.TestCase):
    def test_url_autorisee(self):
        for u in ("https://www.marmiton.org/x", "http://marmiton.org/", "https://fr.allrecipes.com/a"):
            self.assertTrue(s.url_autorisee(u), u)
        for u in ("https://marmiton.org.evil.com/", "https://evilmarmiton.org/", "ftp://marmiton.org/",
                  "javascript:alert(1)", "http://127.0.0.1/", ""):
            self.assertFalse(s.url_autorisee(u), u)

    def test_source_de(self):
        self.assertEqual(s.source_de("https://www.ricardocuisine.com/recettes/1-x"), "ricardocuisine.com")


class Titres(unittest.TestCase):
    def test_titre_depuis_slug(self):
        self.assertEqual(s.titre_depuis_slug("https://www.marmiton.org/recettes/recette_blanquette-de-veau_12345.aspx"),
                         "Blanquette de veau")

    def test_titre_generique(self):
        cas = {
            "https://www.ricardocuisine.com/recettes/6972-dinde-farcie": "Dinde farcie",
            "https://www.marmiton.org/recettes/recette_tarte-au-citron_999.aspx": "Tarte au citron",
            "https://www.ptitchef.com/recettes/plat/lasagnes-fid-1234": "Lasagnes",
            "https://www.750g.com/gratin-dauphinois-r12345.htm": "Gratin dauphinois",
            "https://www.cuisineaz.com/recettes/quiche-lorraine-5678.aspx": "Quiche lorraine",
        }
        for url, attendu in cas.items():
            self.assertEqual(s.titre_generique(url), attendu, url)

    def test_extraire_liens_dedoublonne_et_limite(self):
        page = '<a href="/r/a-1">x</a><a href="/r/a-1">x</a><a href="/r/b-2">y</a><a href="/r/c-3">z</a>'
        res = s.extraire_liens(page, "https://site.test", r'href="(/r/[a-z]-\d)"', s.titre_generique, 2)
        self.assertEqual([r["url"] for r in res], ["https://site.test/r/a-1", "https://site.test/r/b-2"])


class Recherches(unittest.TestCase):
    def test_marmiton(self):
        page = ('<a href="/recettes/recette_blanquette_1.aspx?x=1">a</a>'
                '<a href="https://www.marmiton.org/recettes/recette_curry_2.aspx#top">b</a>'
                '<a href="/recettes/recette_blanquette_1.aspx">doublon</a><a href="/autre">c</a>')
        with mock.patch.object(s, "fetch", return_value=page) as f:
            res = s.recherche_marmiton("blanquette de veau", 10)
        self.assertIn("aqt=blanquette+de+veau", f.call_args[0][0])
        self.assertEqual([r["url"] for r in res], [
            "https://www.marmiton.org/recettes/recette_blanquette_1.aspx",
            "https://www.marmiton.org/recettes/recette_curry_2.aspx"])
        self.assertEqual(res[0]["titre"], "Blanquette")

    def test_ptitchef(self):
        page = ('<a href="/recettes/plat/lasagnes-bolognaise-fid-11">a</a>'
                '<a href="https://www.ptitchef.com/recettes/dessert/tiramisu-fid-22">b</a>')
        with mock.patch.object(s, "fetch", return_value=page) as f:
            res = s.recherche_ptitchef("Lasagnes", 5)
        self.assertTrue(f.call_args[0][0].endswith("/recettes/recettes-de-lasagnes"))
        self.assertEqual([r["titre"] for r in res], ["Lasagnes bolognaise", "Tiramisu"])

    def test_ptitchef_404_sans_resultat(self):
        err = HTTPError("u", 404, "nf", None, None)
        with mock.patch.object(s, "fetch", side_effect=err):
            self.assertEqual(s.recherche_ptitchef("zzz"), [])
        err = HTTPError("u", 500, "ko", None, None)
        with mock.patch.object(s, "fetch", side_effect=err):
            with self.assertRaises(HTTPError):
                s.recherche_ptitchef("zzz")

    def test_source_inconnue(self):
        with self.assertRaises(ValueError):
            s.search_recipes("x", 5, "inconnue")


class ListerPage(unittest.TestCase):
    def test_chronique_ricardo(self):
        url = "https://www.ricardocuisine.com/recettes/chroniques/1-semaine"
        page = ('<a href="/recettes/6972-dinde-farcie">a</a>'
                '<a href="https://www.ricardocuisine.com/en/recipes/777-stuffed-turkey">b</a>'
                '<a href="/recettes/6972-dinde-farcie">doublon</a>'
                '<a href="/recettes/chroniques/1-semaine">la page elle-même</a>')
        with mock.patch.object(s, "fetch", return_value=page):
            res = s.lister_page(url)
        self.assertEqual([r["url"] for r in res], [
            "https://www.ricardocuisine.com/recettes/6972-dinde-farcie",
            "https://www.ricardocuisine.com/en/recipes/777-stuffed-turkey"])
        self.assertEqual(res[0]["titre"], "Dinde farcie")

    def test_marmiton_et_limite(self):
        page = "".join(f'<a href="/recettes/recette_plat-{i}_{i}.aspx">x</a>' for i in range(1, 6))
        with mock.patch.object(s, "fetch", return_value=page):
            self.assertEqual(len(s.lister_page("https://www.marmiton.org/recettes/index.aspx", 3)), 3)

    def test_site_sans_motif(self):
        with self.assertRaisesRegex(ValueError, "non prise en charge"):
            s.lister_page("https://www.allrecipes.com/recipes/")


class Base(unittest.TestCase):
    def test_ajouter_base_fusionne_par_url_et_nettoie(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, mock.patch.object(s, "BASE_FILE", os.path.join(d, "b.json")):
            s.ajouter_base({"url": "u1", "nom": "A : la meilleure recette"})
            s.ajouter_base({"url": "u2", "nom": "B"})
            s.ajouter_base({"url": "u1", "nom": "A bis"})
            noms = sorted(r["nom"] for r in s.lire_base())
            self.assertEqual(noms, ["A bis", "B"])
            self.assertFalse(os.path.exists(s.BASE_FILE + ".tmp"))

    def test_lire_base_absente_ou_corrompue(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "b.json")
            with mock.patch.object(s, "BASE_FILE", f):
                self.assertEqual(s.lire_base(), [])
                with open(f, "w") as h:
                    h.write("{pas du json")
                self.assertEqual(s.lire_base(), [])
                with open(f, "w") as h:
                    json.dump({"recettes": [{"nom": "x"}]}, h)
                self.assertEqual(s.lire_base(), [{"nom": "x"}])


if __name__ == "__main__":
    unittest.main()
