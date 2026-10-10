"""Tests de l'extraction de recettes depuis un PDF (source eFarmz) : python -m unittest discover -s tests

Nécessitent pdfplumber (ignorés s'il n'est pas installé). Le PDF de test, tests/fixtures/fiches.pdf,
contient 3 fiches synthétiques (page photo + page de détail) ; voir tests/fixtures/generer_pdf.py."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pdf_recettes as pdf  # noqa: E402
import serveur_recettes as s  # noqa: E402

FICHES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "fiches.pdf")


@unittest.skipUnless(pdf.disponible(), "pdfplumber non installé")
class Extraction(unittest.TestCase):
    def test_trois_recettes_avec_photo(self):
        recettes, rapport = pdf.convertir(FICHES, 2)
        self.assertEqual([r["nom"] for r in recettes],
                         ["Steak de bœuf et frites de patates douces", "Œufs cocotte", "Salade verte", "Filet de poisson"])
        steak = recettes[0]
        self.assertEqual((len(steak["ingredients"]), len(steak["etapes"])), (10, 6))
        self.assertEqual((steak["prep_min"], steak["cuisson_min"]), (20, 35))
        self.assertEqual(steak["portions"], "2 personnes")
        self.assertTrue(steak["image"].startswith("data:image/jpeg;base64,"))
        self.assertEqual([n for n, _, _ in rapport], [2, 4, 6, 8])             # pages de détail
        self.assertEqual([r["image_page"] for r in recettes], [1, 3, 5, 7])     # photo = page qui précède

    def test_planche_decoupee_zone_visible_seulement(self):
        """CropBox plus petite que la page : le double caché du texte et de la photo est ignoré."""
        poisson = pdf.convertir(FICHES, 2)[0][3]
        self.assertEqual(poisson["nom"], "Filet de poisson")                     # pas de titre doublé
        self.assertEqual(len(poisson["etapes"]), 2)                              # pas d'étapes doublées
        self.assertEqual((poisson["prep_min"], poisson["cuisson_min"]), (15, 30))
        self.assertEqual(poisson["ingredients"], ["2 poisson", "Sucre (non fourni)", "Sel et poivre (non fourni)"])
        # ni l'unité « (càc) » sans quantité, ni le texte du code QR, ne restent dans les ingrédients
        self.assertTrue(poisson["image"].startswith("data:image/jpeg;base64,"))

    def test_photo_jamais_noire(self):
        from io import BytesIO
        import base64
        from PIL import ImageStat, Image
        for r in pdf.convertir(FICHES, 2)[0]:
            im = Image.open(BytesIO(base64.b64decode(r["image"].split(",", 1)[1])))
            self.assertGreater(max(ImageStat.Stat(im).stddev), 2, f"photo vide pour {r['nom']}")

    def test_nombre_de_personnes(self):
        deux = pdf.convertir(FICHES, 2)[0][0]["ingredients"]
        quatre = pdf.convertir(FICHES, 4)[0][0]["ingredients"]
        self.assertNotEqual(deux, quatre)

    def test_sans_images(self):
        recettes, _ = pdf.convertir(FICHES, 2, avec_images=False)
        self.assertTrue(all("image" not in r for r in recettes))

    def test_pdf_illisible(self):
        with tempfile.TemporaryDirectory() as d:
            faux = os.path.join(d, "faux.pdf")
            with open(faux, "wb") as f:
                f.write(b"ce n'est pas un pdf")
            with self.assertRaises(ValueError):
                pdf.convertir(faux)


@unittest.skipUnless(pdf.disponible(), "pdfplumber non installé")
class SourceEfarmz(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = s.ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dossier = os.path.join(self.tmp.name, "eFarmz")
        os.makedirs(self.dossier)
        shutil.copy(FICHES, os.path.join(self.dossier, "v375.pdf"))
        for cible, valeur in (("DOSSIER_PDF", self.dossier), ("BASE_FILE", os.path.join(self.tmp.name, "recettes.json"))):
            p = mock.patch.object(s, cible, valeur)
            p.start()
            self.addCleanup(p.stop)
        s._cache_pdf.clear()

    def requete(self, chemin, post=False):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{chemin}", method="POST" if post else "GET",
                                     headers={"X-Recettes": "1"} if post else {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_source_declaree_comme_dossier(self):
        sources = {x["id"]: x for x in self.requete("/api/sources")[1]}
        self.assertTrue(sources["efarmz"]["dossier"])
        self.assertFalse(sources["marmiton"]["dossier"])

    def test_lecture_du_dossier_sans_mot_cle(self):
        code, res = self.requete("/api/search?source=efarmz")
        self.assertEqual(code, 200)
        self.assertIn("4 recette(s) lue(s)", res[0]["titre"])                    # ligne d'information sur le PDF
        recettes = [x for x in res if x["url"]]
        self.assertEqual([x["url"] for x in recettes], [f"efarmz:v375.pdf#{p}" for p in (2, 4, 6, 8)])
        self.assertIn("10 ingrédients, 6 étapes", recettes[0]["detail"])
        self.assertTrue(recettes[0]["image"].startswith("data:image/jpeg"))
        self.assertTrue(recettes[1]["alertes"])                                  # durées incomplètes signalées

    def test_filtre(self):
        res = self.requete("/api/search?source=efarmz&q=OEUFS")[1]               # sans accent ni majuscule
        self.assertEqual([x["titre"] for x in res if x["url"]], ["Œufs cocotte"])

    def test_dossier_vide_cree_et_explique(self):
        os.remove(os.path.join(self.dossier, "v375.pdf"))
        res = self.requete("/api/search?source=efarmz")[1]
        self.assertEqual(len(res), 1)
        self.assertIn("Aucun PDF", res[0]["titre"])

    def test_pdf_illisible_n_arrete_pas_les_autres(self):
        with open(os.path.join(self.dossier, "casse.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 tronque")
        res = self.requete("/api/search?source=efarmz")[1]
        self.assertEqual(len([x for x in res if x["url"]]), 4)
        self.assertTrue(any(x.get("erreur") and "casse.pdf" in x["titre"] for x in res))

    def test_import_ajoute_a_la_base_avec_la_photo(self):
        code, rec = self.requete("/api/recipe?url=efarmz%3Av375.pdf%234", post=True)
        self.assertEqual((code, rec["nom"], rec["url"]), (200, "Œufs cocotte", ""))
        self.assertEqual(rec["source"], "eFarmz · v375.pdf p.4")
        self.assertNotIn("image_page", rec)
        self.requete("/api/recipe?url=efarmz%3Av375.pdf%236", post=True)
        base = s.lire_base()
        self.assertEqual(sorted(r["nom"] for r in base), ["Salade verte", "Œufs cocotte"])   # deux recettes sans URL cohabitent
        self.assertTrue(all(r["image"].startswith("data:image/jpeg") for r in base))
        self.requete("/api/recipe?url=efarmz%3Av375.pdf%234", post=True)                    # ré-import : pas de doublon
        self.assertEqual(len(s.lire_base()), 2)

    def test_identifiants_invalides_ou_hors_dossier(self):
        for ident in ("efarmz:../serveur_recettes.py#1", "efarmz:/etc/passwd#1", "efarmz:v375.pdf", "efarmz:v375.pdf#x",
                      "efarmz:inconnu.pdf#2", "efarmz:v375.pdf#99", "efarmz:#1"):
            code, rep = self.requete("/api/recipe?url=" + urllib.request.quote(ident, safe=""), post=True)
            self.assertEqual(code, 500, ident)                                   # message écrit par le serveur
            self.assertIn("erreur", rep)
        self.assertEqual(s.lire_base(), [])

    def test_get_n_ecrit_jamais(self):
        self.assertEqual(self.requete("/api/recipe?url=efarmz%3Av375.pdf%234")[0], 405)
        self.assertEqual(s.lire_base(), [])

    def test_pdfplumber_absent_renvoie_503_et_le_reste_fonctionne(self):
        with mock.patch.object(pdf, "disponible", lambda: False):
            code, rep = self.requete("/api/search?source=efarmz")
            self.assertEqual(code, 503)
            self.assertIn("pdfplumber", rep["erreur"])
            self.assertEqual(self.requete("/api/recipe?url=efarmz%3Av375.pdf%234", post=True)[0], 503)
        self.assertEqual(self.requete("/api/ping")[0], 200)


if __name__ == "__main__":
    unittest.main()
