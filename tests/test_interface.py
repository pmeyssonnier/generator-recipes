"""Tests de l'interface dans un vrai navigateur (Chromium, Firefox ou WebKit), contre le vrai serveur.

Nécessitent Playwright (ignorés s'il n'est pas installé) :
    pip install playwright && playwright install chromium firefox webkit
    python -m unittest tests.test_interface -v
RECETTES_NAVIGATEUR=chromium|firefox|webkit : navigateur utilisé (défaut : chromium ; WebKit = moteur de Safari).
RECETTES_CHROMIUM=/chemin/chromium : utilise un Chromium existant au lieu de celui de Playwright.

Le serveur tourne dans ce processus ; seules l'extraction d'une recette (scrape_recipe) et la lecture
d'une page de sélection (lister_page) sont simulées : aucun accès réseau externe.
"""
import json
import os
import pathlib
import socket
import re
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pdf_recettes  # noqa: E402
import serveur_recettes as s  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                   # pragma: no cover
    sync_playwright = None

KEY = "gen_recettes_v1"


def recette(i, nom=None, **extra):
    r = {"nom": nom or f"Recette {i}", "url": f"https://www.marmiton.org/recettes/recette_r{i}_{i}.aspx",
         "categorie": "Plat" if i % 2 else "Dessert", "note": round(5 - i / 10, 1), "nb_avis": 10,
         "ingredients": ["poulet", "sel"], "etapes": ["Cuire."], "total_min": 30, "source": "marmiton.org"}
    r.update(extra)
    return r


class Ancien(s.Handler):
    """Serveur d'avant l'import en POST : 501 sur POST, import par GET, ping sans numéro d'API."""

    def do_POST(self):
        self.send_error(501, "Unsupported method ('POST')")

    def send_json(self, obj, code=200):
        if isinstance(obj, dict):
            obj.pop("api", None)
        super().send_json(obj, code)

    def api(self, methode, u):
        if methode == "GET" and u.path == "/api/recipe":
            rec = s.scrape_recipe(parse_qs(u.query)["url"][0])
            s.ajouter_base(rec)
            return self.send_json(rec)
        return super().api(methode, u)


def demarrer(handler):
    srv = s.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


@unittest.skipIf(sync_playwright is None, "Playwright non installé")
class Interface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.url = demarrer(s.Handler)
        cls.srv_ancien, cls.url_ancien = demarrer(Ancien)
        cls.pw = sync_playwright().start()
        cls.moteur = (os.environ.get("RECETTES_NAVIGATEUR") or "chromium").lower()
        if cls.moteur == "chromium":
            cls.nav = cls.pw.chromium.launch(executable_path=os.environ.get("RECETTES_CHROMIUM") or None,
                                             args=["--host-resolver-rules=MAP monpc.local 127.0.0.1"])
        elif cls.moteur == "firefox":
            cls.nav = cls.pw.firefox.launch(firefox_user_prefs={"network.dns.localDomains": "monpc.local"})
        elif cls.moteur == "webkit":
            cls.nav = cls.pw.webkit.launch()
        else:
            raise ValueError(f"RECETTES_NAVIGATEUR inconnu : {cls.moteur} (chromium, firefox ou webkit)")

    @classmethod
    def tearDownClass(cls):
        cls.nav.close()
        cls.pw.stop()
        for srv in (cls.srv, cls.srv_ancien):
            srv.shutdown()
            srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.echecs = set()          # numéros de recettes dont l'import échoue
        self.noms = {}               # numéro -> nom renvoyé par le « site »
        self.liste = []              # URL renvoyées pour une page de sélection
        self.recherche = []          # résultats d'une recherche par mot-clé
        self.appels_recherche = []

        def faux_scrape(url):
            m = re.search(r"_(\d+)\.aspx", url)
            if not m:
                raise ValueError("Pas de données Recipe sur cette page")
            i = int(m.group(1))
            if i in self.echecs:
                raise HTTPError(url, 404, "introuvable", None, None)
            return recette(i, self.noms.get(i))

        for cible, valeur in (("BASE_FILE", os.path.join(self.tmp.name, "recettes.json")), ("PAUSE", 0)):
            p = mock.patch.object(s, cible, valeur)
            p.start()
            self.addCleanup(p.stop)
        def fausse_recherche(q, n=10, source="marmiton"):
            self.appels_recherche.append((q, n, source))
            return self.recherche

        for nom, valeur in (("scrape_recipe", faux_scrape), ("lister_page", lambda url, n=100: self.liste),
                            ("search_recipes", fausse_recherche)):
            p = mock.patch.object(s, nom, valeur)
            p.start()
            self.addCleanup(p.stop)

        self.erreurs = []
        # l'octroi des permissions du presse-papiers n'existe que dans Chromium
        self.ctx = self.nav.new_context(
            permissions=["clipboard-read", "clipboard-write"] if self.moteur == "chromium" else [])
        self.addCleanup(self.ctx.close)
        self.ctx.add_init_script(f"""
            window.__ecritures = 0;
            const set = Storage.prototype.setItem;
            Storage.prototype.setItem = function (k, v) {{ if (k === "{KEY}") window.__ecritures++; return set.call(this, k, v); }};
        """)
        self.page = self.ctx.new_page()
        self.requetes = []
        self.page.on("response", lambda r: self.requetes.append(f"{r.status} {r.request.method} {r.url[-50:]}"))
        self.page.on("pageerror", lambda e: self.erreurs.append(f"pageerror : {e}"))
        self.page.on("console", lambda m: self.erreurs.append(f"console : {m.text}")
                     if m.type == "error" and "Failed to load resource" not in m.text else None)
        self.addCleanup(lambda: self.assertEqual(self.erreurs, [], "erreurs JS / CSP dans la page"))

    # ---------- utilitaires ----------
    def ouvrir(self, url=None):
        self.page.goto(url or self.url)
        return self.page

    def charger(self, recettes):
        self.page.set_input_files("#file", {"name": "base.json", "mimeType": "application/json",
                                            "buffer": json.dumps(recettes).encode()})
        self.page.wait_for_selector(".card")

    def actif(self):
        return self.page.evaluate("document.activeElement.className + '|' + "
                                  "(document.activeElement.getAttribute('aria-label') || document.activeElement.textContent.trim())")

    def noms_affiches(self):
        return sorted(self.page.locator(".card h3").all_text_contents())

    def attendre_journal(self, motif):
        """Attend `motif` (regex JS) dans le journal d'import ; en cas d'échec, affiche le journal."""
        try:
            self.page.wait_for_function(
                "(motif) => new RegExp(motif).test(document.getElementById('impLog').textContent)",
                arg=motif, polling=100, timeout=15000)
        except Exception:
            self.fail(f"« {motif} » absent du journal d'import : {self.page.inner_text('#impLog')!r}\n"
                      f"requêtes : {self.requetes}")

    def ouvrir_import(self):
        """Ouvre la fenêtre d'import et attend qu'elle soit complète (sources chargées) : cliquer
        pendant qu'elle se réorganise faisait atterrir le clic à côté et fermer la fenêtre."""
        self.page.click("#btnImport")
        self.page.wait_for_function("() => document.getElementById('impSrcAide').textContent.length > 0", polling=100)

    def importer_url(self, url):
        self.ouvrir_import()
        self.page.fill("#impUrl", url)
        self.page.click("#impUrlGo")

    # ---------- sécurité ----------
    def test_csp_et_donnees_importees_hostiles(self):
        self.ouvrir()
        self.assertEqual(self.page.locator('meta[http-equiv="Content-Security-Policy"]').count(), 1)
        self.charger([
            {"nom": "Piégée", "url": "javascript:alert(1)", "image": "x') ,url(//e.example/y", "ingredients": ["a"]},
            {"nom": "Sans url B", "ingredients": ["b"], "note": 4},
            recette(1, image="https://img.example/a.jpg"),
        ])
        stock = self.page.evaluate(f"JSON.parse(localStorage.getItem('{KEY}')).recettes.map(r => [r.nom, r.url, r.image])")
        self.assertEqual(sorted(stock)[0], ["Piégée", "", ""])             # URL et image neutralisées
        self.assertEqual(self.page.eval_on_selector_all(".card img", "els => els.map(e => e.getAttribute('src'))"),
                         ["https://img.example/a.jpg"])
        self.page.locator(".card", has_text="Piégée").click()
        self.assertEqual(self.page.get_attribute("#dLink", "href"), "#")
        self.assertEqual(self.page.eval_on_selector("#dLink", "e => e.style.display"), "none")

    def test_image_integree_d_un_pdf(self):
        """Une image « data:image/png;base64 » (import depuis un PDF) s'affiche ; un data: dangereux est refusé."""
        png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
        self.ouvrir()
        self.charger([{"nom": "Avec photo", "image": png, "ingredients": ["a"]},
                      {"nom": "Piège svg", "image": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=", "ingredients": ["b"]},
                      {"nom": "Piège html", "image": "data:text/html;base64,PGI+", "ingredients": ["c"]}])
        self.assertEqual(self.page.eval_on_selector_all(".card img", "els => els.map(e => e.getAttribute('src'))"), [png])
        self.page.wait_for_function("() => [...document.querySelectorAll('.card img')].every(i => i.complete && i.naturalWidth === 1)")

    def test_reimport_d_une_page_de_pdf_remplace_l_ancienne_version(self):
        """Même page de PDF, titre différent (ancienne version erronée) : une seule carte, la plus récente."""
        self.ouvrir()
        pdf = "eFarmz · p148.pdf p.2"
        self.charger([{"nom": "Filet doublé filet doublé", "source": pdf, "ingredients": ["a"]},
                      {"nom": "Autre", "source": "Mamie", "ingredients": ["b"]},
                      {"nom": "Autre 2", "source": "Mamie", "ingredients": ["c"]}])
        self.assertEqual(self.noms_affiches(), ["Autre", "Autre 2", "Filet doublé filet doublé"])
        self.charger([{"nom": "Filet de poisson", "source": pdf, "ingredients": ["a"]}])
        self.page.locator(".card", has_text="Filet de poisson").wait_for()   # le chargement du fichier est asynchrone
        self.assertEqual(self.noms_affiches(), ["Autre", "Autre 2", "Filet de poisson"])

    def test_favoris_et_courses_survivent_au_renommage_d_une_fiche_de_pdf(self):
        """Une fiche de PDF est identifiée par sa page : le favori et les courses suivent un titre corrigé au ré-import."""
        self.ouvrir()
        pdf = "eFarmz · p148.pdf p.2"
        self.charger([{"nom": "Ancien titre", "source": pdf, "ingredients": ["a"]}])
        self.page.locator(".card", has_text="Ancien titre").locator("[data-fav]").click()
        self.page.locator(".card", has_text="Ancien titre").locator("[data-pan]").click()
        self.charger([{"nom": "Nouveau titre", "source": pdf, "ingredients": ["a"]}])
        self.page.locator(".card", has_text="Nouveau titre").wait_for()      # le chargement du fichier est asynchrone
        self.assertEqual(self.noms_affiches(), ["Nouveau titre"])
        donnees = self.page.evaluate(f"JSON.parse(localStorage.getItem('{KEY}'))")
        self.assertEqual((donnees["favs"], donnees["panier"]), ([f"pdf:{pdf}"], [f"pdf:{pdf}"]))
        # base enregistrée par une version précédente : favoris et courses sous le nom, repris sous la clé de la page
        self.page.evaluate("""([key, pdf]) => localStorage.setItem(key, JSON.stringify({
            recettes: [{nom: "Titre", source: pdf, ingredients: ["a"]}], favs: ["nom:Titre"], panier: ["nom:Titre"]}))""",
                           [KEY, pdf])
        self.page.reload()
        self.page.wait_for_selector(".card")
        donnees = self.page.evaluate(f"JSON.parse(localStorage.getItem('{KEY}'))")
        self.assertEqual((donnees["favs"], donnees["panier"]), ([f"pdf:{pdf}"], [f"pdf:{pdf}"]))

    def test_json_mal_forme_ne_casse_pas_la_page(self):
        """Un JSON valide peut avoir n'importe quelle forme : les entrées inutilisables sont ignorées (et signalées),
        les autres normalisées ; rien n'est modifié par une entrée invalide."""
        self.ouvrir()
        self.charger([{"nom": "Base", "ingredients": ["a"]}])
        self.charger([None, 5, "texte", [], {"sans": "nom"}, {"nom": 123}, {"nom": "  "},
                      {"nom": "Soupe", "ingredients": "oignon\n  \ncarotte", "etapes": {"x": 1}, "note": "4,5",
                       "categorie": ["Entrée", 5], "total_min": "abc", "_ing": "piratage", "__proto__": {"x": 1}},
                      {"nom": "Gâteau", "ingredients": [1, None, {"a": 1}, "farine"], "image": 42, "url": 7}])
        self.page.locator(".card", has_text="Gâteau").wait_for()
        self.assertEqual(self.noms_affiches(), ["Base", "Gâteau", "Soupe"])
        self.assertTrue(any("ignorée(s)" in t for t in self.alertes_toast()), self.alertes_toast())
        base = {r["nom"]: r for r in self.page.evaluate(f"JSON.parse(localStorage.getItem('{KEY}')).recettes")}
        self.assertEqual(base["Soupe"]["ingredients"], ["oignon", "carotte"])
        self.assertEqual((base["Soupe"]["etapes"], base["Soupe"]["note"], base["Soupe"]["total_min"]), ([], 4.5, None))
        self.assertEqual(base["Gâteau"]["ingredients"], ["1", "farine"])
        self.assertNotIn("_ing", base["Soupe"])
        # fichier qui n'est pas une liste de recettes : accepté sans rien casser
        self.charger([{"nom": "Autre"}])
        self.page.locator(".card", has_text="Autre").wait_for()

    def test_stockage_navigateur_corrompu_ne_casse_pas_la_page(self):
        self.ouvrir()
        self.page.evaluate("""([key]) => localStorage.setItem(key, JSON.stringify({
            recettes: [null, 5, {nom: "Seule valide", ingredients: 5, etapes: "a\\nb"}, {nom: ["x"]}], favs: "abc", panier: {a: 1}}))""", [KEY])
        self.page.reload()
        self.page.locator(".card", has_text="Seule valide").wait_for()
        self.assertEqual(self.noms_affiches(), ["Seule valide"])
        self.assertEqual(self.page.inner_text("#nbPanier"), "0")

    def test_accessibilite_clavier_et_annonces(self):
        """Charger JSON et les filtres sont de vrais boutons ; les annonces passent par une zone role=status ;
        les champs de la fenêtre d'import ont un nom accessible."""
        self.ouvrir()
        self.assertEqual(self.page.eval_on_selector("#btnCharger", "e => e.tagName"), "BUTTON")
        self.assertEqual(self.page.get_attribute("#toasts", "role"), "status")
        self.charger([recette(1), recette(2)])
        self.page.fill("#avecIn", "poulet")
        self.page.press("#avecIn", "Enter")
        puce = self.page.locator("#avecChips button.chip")
        self.assertEqual(puce.get_attribute("aria-label"), "Retirer le filtre poulet")
        puce.focus()
        self.page.keyboard.press("Enter")                              # retirer au clavier
        self.assertEqual(self.page.locator("#avecChips .chip").count(), 0)
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "avecIn", "le focus revient au champ")
        self.ouvrir_import()
        for nom in ("Source des recettes", "Mot-clé ou titre à chercher", "Nombre maximum de résultats",
                    "Adresse d'une recette ou d'une page de sélection"):
            self.assertTrue(self.page.get_by_label(nom).first.is_visible(), nom)
        self.assertEqual(self.page.get_attribute("#impLog", "role"), "log")

    def test_fractions_en_exposant(self):
        """Dans la fiche, seuls les nombres mixtes (« 1 1/2 », « 2 1/4 ») ont la fraction en exposant ; « 1/2 gousse » reste seule."""
        self.ouvrir()
        r = dict(recette(1), ingredients=["1 1/2 oignon", "2 1/4 l de lait", "1/2 gousse d'ail", "1/4 càc de sel",
                                          "10/4 g de sucre", "2 pommes"])
        self.charger([r])
        self.page.locator(".card-link", has_text="Recette 1").click()
        self.assertEqual(self.page.locator("#dIng sup.frac").all_text_contents(), ["1/2", "1/4"])
        self.assertEqual(self.page.locator("#dIng li").nth(0).inner_text().strip(), "1 1/2 oignon")
        for i in (2, 3, 4, 5):
            self.assertEqual(self.page.locator("#dIng li").nth(i).locator("sup").count(), 0)

    def test_supprimer_une_recette(self):
        """Bouton « Supprimer » de la fiche : confirmation, retrait du navigateur et de recettes.json, favoris compris."""
        self.ouvrir()
        self.charger([recette(1), recette(2)])
        s.ajouter_base(recette(1))                                                            # la base du serveur les contient aussi
        s.ajouter_base(recette(2))
        self.page.locator(".card", has_text="Recette 2").locator("[data-fav]").click()      # favori à retirer avec elle
        self.assertEqual(sorted(r["nom"] for r in s.lire_base()), ["Recette 1", "Recette 2"])
        self.page.locator(".card", has_text="Recette 2").click()
        self.page.once("dialog", lambda d: d.dismiss())                                       # annuler : rien ne change
        self.page.click("#dSuppr")
        self.assertEqual(self.noms_affiches(), ["Recette 1", "Recette 2"])
        self.assertEqual(len(s.lire_base()), 2)
        self.page.once("dialog", lambda d: d.accept())
        self.page.click("#dSuppr")
        self.page.wait_for_function("() => document.querySelectorAll('.card').length === 1", polling=100)
        self.assertEqual(self.noms_affiches(), ["Recette 1"])
        self.assertEqual([r["nom"] for r in s.lire_base()], ["Recette 1"])                    # aussi dans le fichier du serveur
        stock = self.page.evaluate(f"JSON.parse(localStorage.getItem('{KEY}'))")
        self.assertEqual([r["nom"] for r in stock["recettes"]], ["Recette 1"])
        self.assertEqual(stock["favs"], [])
        self.assertFalse(self.page.is_visible("#dlgRecette"))

    def test_supprimer_sans_serveur_previent(self):
        self.ouvrir()
        self.charger([recette(1), recette(2)])
        self.page.locator(".card", has_text="Recette 1").click()
        with mock.patch.object(s, "supprimer_base", side_effect=OSError("disque")):
            self.page.once("dialog", lambda d: d.accept())
            self.page.click("#dSuppr")
            self.page.wait_for_function("() => document.querySelectorAll('.card').length === 1", polling=100)
        self.assertIn("supprimée du navigateur seulement", self.page.inner_text("body"))

    def test_favoris_independants_sans_url(self):
        self.ouvrir()
        self.charger([{"nom": "A sans url", "ingredients": ["a"], "note": 5}, {"nom": "B sans url", "ingredients": ["b"], "note": 4}])
        self.page.locator(".card", has_text="B sans url").locator("[data-fav]").click()
        etats = self.page.eval_on_selector_all(".card", "els => els.map(c => [c.querySelector('h3').textContent, c.querySelector('[data-fav]').className])")
        self.assertEqual(dict(etats), {"A sans url": "icon-btn off", "B sans url": "icon-btn on"})

    # ---------- clavier ----------
    def test_parcours_clavier(self):
        self.ouvrir()
        self.charger([recette(1), recette(2), recette(3)])
        k = self.page.keyboard
        self.page.locator(".card-link").first.focus()
        self.assertTrue(self.actif().startswith("card-link|Recette 1"))
        k.press("Tab")
        self.assertIn("Favori : Recette 1", self.actif())
        k.press("Enter")
        self.assertIn("Favori : Recette 1", self.actif(), "le focus survit au re-rendu")
        self.assertEqual(self.page.get_attribute('[data-fav="0"]', "aria-pressed"), "true")
        k.press("Tab")
        k.press("Space")
        self.assertIn("Courses : Recette 1", self.actif())
        self.assertEqual(self.page.inner_text("#nbPanier"), "1")
        k.press("Tab")
        self.assertTrue(self.actif().startswith("card-link|Recette 2"))
        k.press("Enter")
        self.assertTrue(self.page.eval_on_selector("#dlgRecette", "d => d.open"))
        self.assertEqual(self.page.inner_text("#dTitre"), "Recette 2")
        k.press("Escape")
        self.page.wait_for_timeout(50)
        self.assertTrue(self.actif().startswith("card-link|Recette 2"), "le focus revient sur le titre")
        # ajout aux courses depuis la fiche : la grille est recréée, le focus retrouve quand même la carte
        k.press("Enter")
        self.page.click("#dPanier")
        k.press("Escape")
        self.page.wait_for_timeout(50)
        self.assertTrue(self.actif().startswith("card-link|Recette 2"))
        # la souris fonctionne toujours
        self.page.locator(".card .img").nth(2).click()
        self.assertEqual(self.page.inner_text("#dTitre"), "Recette 3")

    # ---------- import ----------
    def test_import_en_lot(self):
        self.ouvrir()
        self.charger([recette(1), recette(9)])
        self.page.locator(".card", has_text="Recette 1").locator("[data-fav]").click()
        self.echecs = {3}
        self.noms = {1: "Recette 1 mise à jour"}
        self.liste = [{"url": recette(i)["url"], "titre": f"t{i}"} for i in (1, 2, 3, 4, 5)]
        self.importer_url("https://www.marmiton.org/recettes/liste")
        self.page.wait_for_function("() => document.querySelectorAll('#impRes input').length === 5", polling=100)
        self.page.locator("#impRes input").first.check()          # « Recette 1 » est déjà en base : décochée
        self.page.evaluate("() => { window.__ecritures = 0; }")
        self.page.click("#impGo")
        self.attendre_journal("Terminé")
        journal = self.page.inner_text("#impLog")
        self.assertIn("Terminé : 4/5", journal)
        self.assertIn("HTTP 404", journal)                          # l'échec est signalé, le lot continue
        self.assertEqual(self.page.evaluate("() => window.__ecritures"), 1, "une seule sauvegarde pour tout le lot")
        self.page.keyboard.press("Escape")
        self.assertEqual(self.noms_affiches(), ["Recette 1 mise à jour", "Recette 2", "Recette 4", "Recette 5", "Recette 9"])
        favs = self.page.evaluate(f"JSON.parse(localStorage.getItem('{KEY}')).favs")
        self.assertEqual(favs, [recette(1)["url"]], "le favori survit au ré-import")
        self.assertEqual(self.page.locator("#cat option").count(), 3)        # Toutes + Plat + Dessert
        self.assertEqual(sorted(r["nom"] for r in s.lire_base()),
                         ["Recette 1 mise à jour", "Recette 2", "Recette 4", "Recette 5"])   # copie serveur

    def test_import_d_une_url_et_erreur_site_non_autorise(self):
        self.ouvrir()
        self.importer_url(recette(42)["url"])
        self.attendre_journal("✓ Recette 42")
        self.assertEqual([r["nom"] for r in s.lire_base()], ["Recette 42"])
        self.page.fill("#impUrl", "http://127.0.0.1/x")
        self.page.click("#impUrlGo")
        self.attendre_journal("Site non autorisé")

    @unittest.skipUnless(pdf_recettes.disponible(), "pdfplumber non installé")
    def test_import_pdf_efarmz(self):
        """Source eFarmz : lecture du dossier de PDF, extraction visible, sélection, import avec photo, affichage."""
        dossier = os.path.join(self.tmp.name, "eFarmz")
        os.makedirs(dossier)
        shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "fiches.pdf"),
                    os.path.join(dossier, "v375.pdf"))
        p = mock.patch.object(s, "DOSSIER_PDF", dossier)
        p.start()
        self.addCleanup(p.stop)
        s._cache_pdf.clear()
        self.ouvrir()
        self.ouvrir_import()
        self.page.select_option("#impSrc", "efarmz")
        self.assertEqual(self.page.inner_text("#impSearch"), "Lire les PDF")
        self.assertTrue(self.page.is_hidden("#impN") and self.page.is_visible("#impPers"))
        self.page.click("#impSearch")                                        # aucun mot-clé nécessaire
        self.page.wait_for_function("() => document.querySelectorAll('#impRes input').length === 4", polling=100)
        self.attendre_journal("4 recettes extraite")
        journal = self.page.inner_text("#impLog")
        self.assertIn("📄 v375.pdf : 4 recette(s) lue(s)", journal)
        self.assertIn("✓ Steak de bœuf et frites de patates douces (p.2) — 10 ingrédients, 6 étapes, photo p.1", journal)
        self.assertIn("⚠ Œufs cocotte (p.4)", journal)                       # alerte d'extraction visible
        self.assertEqual(self.page.locator("#impRes img").count(), 4)         # miniatures
        self.page.locator("#impRes details").first.locator("summary").click()
        self.assertIn("Ingrédients", self.page.locator("#impRes details").first.inner_text())     # aperçu du contenu extrait
        cases = self.page.locator("#impRes input")
        cases.nth(0).uncheck()
        cases.nth(2).uncheck()
        cases.nth(3).uncheck()                                                # seule « Œufs cocotte » reste cochée
        self.page.click("#impGo")
        self.attendre_journal("Terminé : 1/1")
        self.assertIn("[1/1] ✓ Œufs cocotte", self.page.inner_text("#impLog"))
        self.page.keyboard.press("Escape")
        self.assertEqual(self.noms_affiches(), ["Œufs cocotte"])
        self.page.wait_for_function("() => [...document.querySelectorAll('.card img')].every(i => i.complete && i.naturalWidth > 0)")
        self.assertEqual(self.page.locator(".card img").count(), 1)           # la photo du PDF est affichée
        self.assertEqual([r["nom"] for r in s.lire_base()], ["Œufs cocotte"])  # et sauvegardée côté serveur
        self.page.click("#btnImport")                                         # relire : « déjà en base »
        self.page.click("#impSearch")
        self.page.wait_for_function("() => document.querySelectorAll('#impRes input').length === 4", polling=100)
        self.assertEqual(self.page.locator("#impRes input:checked").count(), 3)
        self.assertIn("déjà en base", self.page.inner_text("#impRes"))

    def test_filtres_sur_recettes_importees(self):
        self.ouvrir()
        base = [recette(i, ingredients=["poulet"] if i < 3 else ["veau"]) for i in range(1, 6)]
        self.charger(base)
        self.page.fill("#avecIn", "poulet")
        self.page.press("#avecIn", "Enter")
        self.assertEqual(self.page.locator(".card").count(), 2)
        self.page.fill("#sansIn", "poulet")
        self.page.press("#sansIn", "Enter")
        self.assertEqual(self.page.locator(".card").count(), 0)
        self.page.click("#btnReset")
        self.page.fill("#q", "Recette 4")
        self.assertEqual(self.noms_affiches(), ["Recette 4"])

    # ---------- pagination ----------
    def test_pagination(self):
        self.ouvrir()
        self.charger([recette(i, nom=f"Recette {i:03d}", ingredients=["poulet" if i < 100 else "veau"], note=4) for i in range(130)])
        cartes = lambda: self.page.locator(".card").count()          # noqa: E731
        self.assertEqual(cartes(), 48)
        self.assertEqual(self.page.inner_text(".plus .meta"), "48 sur 130 affichées")
        self.assertEqual(self.page.inner_text("#plus"), "Afficher 48 de plus (82 restantes)")
        self.assertEqual(self.page.inner_text("#count"), "130 / 130 recettes")
        self.page.focus("#plus")
        self.page.keyboard.press("Enter")
        self.assertEqual(cartes(), 96)
        self.assertEqual(self.actif().split("|")[1], "Recette 048", "focus sur la 1re nouvelle carte")
        self.page.locator(".card", has_text="Recette 070").locator("[data-fav]").click()
        self.assertEqual(cartes(), 96, "un favori ne ramène pas à la première page")
        self.page.click("#plus")
        self.assertEqual((cartes(), self.page.locator("#plus").count()), (130, 0))
        self.page.fill("#avecIn", "poulet")
        self.page.press("#avecIn", "Enter")
        self.assertEqual((cartes(), self.page.inner_text(".plus .meta")), (48, "48 sur 100 affichées"))
        self.page.click("#btnReset")
        self.assertEqual(cartes(), 48)
        self.page.click("#btnSurprise")
        self.assertEqual((cartes(), self.page.locator("#plus").count()), (3, 0))
        self.page.click("#voirTout")
        self.assertEqual(cartes(), 48)
        self.page.click("#btnReset")
        self.page.click("#btnExport")
        self.assertEqual(self.page.inner_text("#expFiltreInfo"), "130 recettes", "l'export porte sur tout le résultat")

    # ---------- compatibilité avec un serveur plus ancien ----------
    def test_serveur_ancien_repli_sur_get(self):
        methodes = []
        self.page.on("request", lambda r: methodes.append(r.method) if "/api/recipe" in r.url else None)
        self.ouvrir(self.url_ancien)
        self.importer_url(recette(7)["url"])
        self.attendre_journal("✓ Recette 7")
        self.assertIn("ancien", self.page.inner_text("#srvStatus"))
        self.assertEqual(methodes, ["GET"])

    def test_serveur_actuel_utilise_post(self):
        methodes = []
        self.page.on("request", lambda r: methodes.append(r.method) if "/api/recipe" in r.url else None)
        self.ouvrir()
        self.importer_url(recette(7)["url"])
        self.attendre_journal("✓ Recette 7")
        self.assertNotIn("ancien", self.page.inner_text("#srvStatus"))
        self.assertEqual(methodes, ["POST"])

    # ---------- boutons : chacun fait réellement quelque chose ----------
    def ouvert(self, dialogue):
        return self.page.eval_on_selector(dialogue, "d => d.open")

    def alertes_toast(self):
        return self.page.eval_on_selector_all("#toasts > div", "els => els.map(e => e.textContent)")

    def test_numero_de_version_affiche(self):
        version_page = s.VERSION
        self.ouvrir()
        self.assertEqual(self.page.inner_text("header h1 .version"), f"v{s.VERSION}")
        self.page.wait_for_function("() => document.getElementById('srvStatus').title.includes('serveur v')", polling=100)
        self.assertIn(f"serveur v{s.VERSION}", self.page.get_attribute("#srvStatus", "title"))
        self.assertNotIn("mets le serveur à jour", self.page.get_attribute("#srvStatus", "title"))   # même version
        with mock.patch.object(s, "VERSION", "0.9.0"):                                               # serveur plus ancien que la page
            self.page.reload()
            self.page.wait_for_function("() => document.getElementById('srvStatus').title.includes('serveur v0.9.0')", polling=100)
            self.assertIn(f"page v{version_page} : mets le serveur à jour", self.page.get_attribute("#srvStatus", "title"))

    def test_dialogue_recette(self):
        self.ouvrir()
        self.charger([recette(1), recette(2)])
        self.page.locator(".card-link", has_text="Recette 1").click()
        self.assertTrue(self.ouvert("#dlgRecette"))
        self.assertEqual(self.page.inner_text("#dTitre"), "Recette 1")
        self.assertIn("marmiton.org", self.page.inner_text("#dMeta"))
        self.assertEqual(self.page.locator("#dIng li").count(), 2)
        self.assertEqual(self.page.inner_text("#dSteps li"), "Cuire.")
        case = self.page.locator("#dIng input").first
        case.check()                                                    # ingrédient à cocher
        self.assertTrue(case.is_checked())
        self.assertEqual(self.page.get_attribute("#dLink", "href"), recette(1)["url"])
        self.assertEqual(self.page.get_attribute("#dLink", "target"), "_blank")
        self.page.keyboard.press("Escape")
        fermetures = (lambda: self.page.click("#dlgRecette .dlg-head [data-close]"),        # ✕
                      lambda: self.page.click("#dlgRecette .dlg-foot [data-close]"),        # Fermer
                      lambda: self.page.mouse.click(5, 5),                                  # clic hors de la fenêtre
                      lambda: self.page.keyboard.press("Escape"))
        for fermer in fermetures:
            self.page.locator(".card-link").first.click()
            self.assertTrue(self.ouvert("#dlgRecette"))
            fermer()
            self.assertFalse(self.ouvert("#dlgRecette"))

    def test_favoris_et_filtre(self):
        self.ouvrir()
        self.charger([recette(1), recette(2), recette(3)])
        fav = lambda n: self.page.locator(".card", has_text=f"Recette {n}").locator("[data-fav]")   # noqa: E731
        fav(2).click()
        self.assertEqual(fav(2).get_attribute("aria-pressed"), "true")
        self.assertIn("on", fav(2).get_attribute("class").split())
        self.page.check("#favOnly")
        self.assertEqual(self.noms_affiches(), ["Recette 2"])
        fav(2).click()                                                  # retiré alors que le filtre est actif
        self.assertEqual(self.page.locator(".card").count(), 0)
        self.assertIn("Aucune recette ne correspond", self.page.inner_text("#grid"))
        self.page.uncheck("#favOnly")
        self.assertEqual(self.page.locator(".card").count(), 3)
        fav(3).click()
        self.page.reload()                                              # conservé après rechargement
        self.page.wait_for_selector(".card")
        self.assertEqual(fav(3).get_attribute("aria-pressed"), "true")
        self.assertEqual(fav(1).get_attribute("aria-pressed"), "false")

    def test_courses(self):
        self.ouvrir()
        self.charger([recette(1), recette(2)])
        self.page.locator(".card", has_text="Recette 1").locator("[data-pan]").click()
        self.assertEqual(self.page.inner_text("#nbPanier"), "1")
        self.page.locator(".card-link", has_text="Recette 2").click()   # ajout depuis la fiche
        self.assertEqual(self.page.inner_text("#dPanier"), "🛒 Ajouter aux courses")
        self.page.click("#dPanier")
        self.assertEqual(self.page.inner_text("#dPanier"), "✓ Dans les courses")
        self.assertEqual(self.page.inner_text("#nbPanier"), "2")
        self.page.keyboard.press("Escape")
        self.page.click("#btnPanier")
        self.assertTrue(self.ouvert("#dlgPanier"))
        liste = self.page.input_value("#txtCourses")
        for attendu in ("== Recette 1", "== Recette 2", "☐ poulet", "☐ sel"):
            self.assertIn(attendu, liste)
        self.page.click("#btnCopier")
        if self.moteur == "chromium":                                   # lecture du presse-papiers : Chromium seulement
            self.assertEqual(self.page.evaluate("() => navigator.clipboard.readText()"), liste)
        self.assertIn("Liste copiée", self.alertes_toast())
        self.page.click("#btnViderPanier")
        self.assertEqual(self.page.inner_text("#nbPanier"), "0")
        self.assertIn("Panier vide", self.page.input_value("#txtCourses"))
        self.page.click("#dlgPanier .dlg-foot [data-close]")
        self.assertFalse(self.ouvert("#dlgPanier"))

    def test_export(self):
        self.ouvrir()
        self.page.click("#btnExport")                                   # base vide : pas de fenêtre, un message
        self.assertFalse(self.ouvert("#dlgExport"))
        self.assertIn("Aucune recette à exporter", self.alertes_toast())
        self.charger([recette(1), recette(2), recette(3)])
        self.page.locator(".card", has_text="Recette 2").locator("[data-fav]").click()
        self.page.click("#btnExport")
        self.assertEqual(self.page.inner_text("#expToutInfo"), "3 recettes")
        self.assertEqual(self.page.inner_text("#expFavInfo"), "1 recette")
        with self.page.expect_download() as dl:
            self.page.click("#expTout")
        self.assertRegex(dl.value.suggested_filename, r"^recettes_base_\d{4}-\d{2}-\d{2}\.json$")
        with open(dl.value.path(), encoding="utf-8") as f:
            contenu = json.load(f)
        self.assertEqual({r["nom"]: r["favori"] for r in contenu},
                         {"Recette 1": False, "Recette 2": True, "Recette 3": False})
        self.assertFalse(any(k.startswith("_") for r in contenu for k in r), "index interne exporté")
        self.assertFalse(self.ouvert("#dlgExport"), "la fenêtre se ferme après l'export")
        self.page.click("#btnExport")
        with self.page.expect_download() as dl:
            self.page.click("#expFav")
        self.assertTrue(dl.value.suggested_filename.startswith("recettes_favoris_"))
        with open(dl.value.path(), encoding="utf-8") as f:
            self.assertEqual([r["nom"] for r in json.load(f)], ["Recette 2"])
        self.page.locator(".card", has_text="Recette 2").locator("[data-fav]").click()   # plus aucun favori
        self.page.click("#btnExport")
        self.assertTrue(self.page.is_disabled("#expFav"))

    def test_import_par_recherche(self):
        self.recherche = [{"url": recette(i)["url"], "titre": f"Titre {i}"} for i in (1, 2, 3)]
        self.ouvrir()
        self.ouvrir_import()
        self.assertIn("serveur", self.page.inner_text("#srvStatus"))
        sources = self.page.eval_on_selector_all("#impSrc option", "els => els.map(e => e.textContent)")
        self.assertEqual(sources, ["Marmiton", "PtitChef", "eFarmz (PDF)"])             # fournies par le serveur
        aide = self.page.inner_text("#impSrcAide")
        self.page.select_option("#impSrc", "ptitchef")
        self.assertNotEqual(self.page.inner_text("#impSrcAide"), aide)
        self.page.select_option("#impSrc", "marmiton")
        self.page.fill("#impQ", "quiche")
        self.page.press("#impQ", "Enter")                               # Entrée lance la recherche
        self.page.wait_for_function("() => document.querySelectorAll('#impRes input').length === 3", polling=100)
        self.assertEqual(self.appels_recherche, [("quiche", 10, "marmiton")])
        cases = self.page.locator("#impRes input")
        self.assertEqual(cases.evaluate_all("els => els.filter(e => e.checked).length"), 3)
        self.page.click("#impAll")                                      # tout décocher…
        self.assertEqual(cases.evaluate_all("els => els.filter(e => e.checked).length"), 0)
        self.page.click("#impAll")                                      # …puis tout cocher
        self.assertEqual(cases.evaluate_all("els => els.filter(e => e.checked).length"), 3)
        cases.nth(1).uncheck()
        self.page.click("#impGo")
        self.attendre_journal("Terminé : 2/2")
        self.page.click("#dlgImport .dlg-head [data-close]")
        self.assertEqual(self.noms_affiches(), ["Recette 1", "Recette 3"])
        self.page.click("#btnImport")                                   # la recherche suivante signale « déjà en base »
        self.page.fill("#impQ", "quiche")
        self.page.click("#impSearch")
        self.page.wait_for_function("() => document.querySelectorAll('#impRes input').length === 3", polling=100)
        self.assertEqual(self.page.locator("#impRes input:checked").count(), 1)       # seule la nouvelle est cochée
        self.assertIn("déjà en base", self.page.inner_text("#impRes"))

    def test_categories_regroupees_efarmz_classe_et_filtre_source(self):
        """Variantes de catégories regroupées, « eFarmz » absent des catégories (recettes classées), filtre par source."""
        self.ouvrir()
        ef = lambda i, nom, ing: recette(i, nom, url="", source=f"eFarmz · v375.pdf p.{i}", categorie="eFarmz",   # noqa: E731
                                         ingredients=ing)
        self.charger([recette(1, categorie="Entrée"), recette(2, categorie="Entrées"),
                      recette(3, categorie="Dessert", source="ptitchef.com"), recette(4, categorie="Desserts"),
                      recette(5, categorie="Desert"), recette(6, categorie="Plats principaux"),
                      recette(7, categorie=["Plat principal", "plat"]),
                      ef(8, "Mousse au chocolat", ["chocolat", "oeufs"]), ef(9, "Soupe de potiron", ["potiron"]),
                      ef(10, "Poulet rôti", ["poulet"])])
        options = lambda sel: self.page.locator(f"{sel} option").all_text_contents()    # noqa: E731
        self.assertEqual(options("#cat"), ["Toutes", "Dessert", "Entrée", "Plat principal"])
        ordre = lambda: sorted(self.page.locator(".card h3").all_text_contents())     # noqa: E731
        self.page.select_option("#cat", label="Dessert")
        self.assertEqual(ordre(), ["Mousse au chocolat", "Recette 3", "Recette 4", "Recette 5"])
        self.page.select_option("#cat", label="Entrée")
        self.assertEqual(ordre(), ["Recette 1", "Recette 2", "Soupe de potiron"])
        self.page.select_option("#cat", label="Plat principal")
        self.assertEqual(ordre(), ["Poulet rôti", "Recette 6", "Recette 7"])
        self.assertEqual(options("#src"), ["Toutes", "eFarmz", "Marmiton", "PtitChef"])
        self.page.select_option("#cat", "")
        self.page.select_option("#src", "eFarmz")
        self.assertEqual(ordre(), ["Mousse au chocolat", "Poulet rôti", "Soupe de potiron"])
        self.page.select_option("#src", "PtitChef")
        self.assertEqual(ordre(), ["Recette 3"])
        self.page.click("#btnReset")
        self.assertEqual(self.page.input_value("#src"), "")
        self.assertEqual(len(ordre()), 10)
        base = self.page.evaluate(f"JSON.parse(localStorage.getItem('{KEY}')).recettes")      # classement enregistré
        self.assertEqual([r["categorie"] for r in base if r["nom"] == "Soupe de potiron"], ["Entrée"])

    def test_port_personnalise_hors_serveur(self):
        # Page ouverte en fichier : ?port=8766 désigne le serveur local, et le choix est retenu.
        vus = []
        self.page.on("request", lambda r: vus.append(r.url))
        self.page.goto(pathlib.Path(s.DIR_PAGE, "generateur-recettes.html").as_uri() + "?port=8766")
        self.page.wait_for_function("() => document.getElementById('srvStatus')", polling=100)
        self.page.wait_for_timeout(800)
        self.assertTrue(any(u.startswith("http://localhost:8766/") for u in vus), vus)
        self.assertFalse(any(u.startswith("http://localhost:8765/") for u in vus), vus)
        stockage = self.page.evaluate("(() => { try { return localStorage.getItem('recettes.port') === '8766'; }"
                                      " catch { return false; } })()")
        if stockage:                                    # (certains moteurs refusent le stockage des fichiers)
            vus.clear()
            self.page.goto(pathlib.Path(s.DIR_PAGE, "generateur-recettes.html").as_uri())     # sans paramètre : retenu
            self.page.wait_for_timeout(800)
            self.assertTrue(any(u.startswith("http://localhost:8766/") for u in vus), vus)
        self.erreurs.clear()           # serveur absent sur ce port : les refus de connexion sont attendus

    def test_journal_d_import_non_cumule(self):
        self.ouvrir()
        self.ouvrir_import()
        self.page.evaluate("document.getElementById('impLog').textContent = 'ancien message\\n'")
        self.page.keyboard.press("Escape")
        self.ouvrir_import()
        self.assertNotIn("ancien message", self.page.inner_text("#impLog"))

    def test_filtres_en_accordeon(self):
        # Grand écran : groupes ouverts ; téléphone : repliés, dépliables au clic et au clavier.
        self.ouvrir()
        self.assertEqual(self.page.locator("details.fgrp[open]").count(), 4)
        self.assertTrue(self.page.is_visible("#cat"))
        self.page.click("details.fgrp:has(#cat) > summary")
        self.assertFalse(self.page.is_visible("#cat"))
        self.page.click("details.fgrp:has(#cat) > summary")
        self.assertTrue(self.page.is_visible("#cat"))
        self.assertFalse(self.page.is_visible("#btnFiltres"))            # grand écran : pas de ☰
        self.assertFalse(self.page.is_visible("#btnFermerFiltres"))

    def test_filtres_en_tiroir_sur_telephone(self):
        self.page.set_viewport_size({"width": 400, "height": 800})
        self.ouvrir()
        self.charger([recette(1, categorie="Plat", note=4.8), recette(2, categorie="Dessert", note=3.2)])
        self.assertTrue(self.page.is_visible("#btnFiltres"))
        self.assertFalse(self.page.is_visible("#cat"), "le tiroir est fermé au départ")
        self.assertEqual(self.page.get_attribute("#btnFiltres", "aria-expanded"), "false")
        self.page.click("#btnFiltres")
        self.page.wait_for_selector("#cat", state="visible")
        self.assertEqual(self.page.get_attribute("#btnFiltres", "aria-expanded"), "true")
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "btnFermerFiltres")
        self.page.select_option("#cat", "Dessert")
        self.assertEqual(self.noms_affiches(), ["Recette 2"])            # le filtre agit pendant que le tiroir est ouvert
        self.assertEqual(self.page.inner_text("#nbFiltres"), "1")
        self.page.click("#btnVoirRecettes")                             # fermeture par le bouton du bas
        self.page.wait_for_selector("#cat", state="hidden")
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "btnFiltres")
        self.page.click("#btnFiltres")
        self.page.keyboard.press("Escape")                              # Échap
        self.page.wait_for_selector("#cat", state="hidden")
        self.page.click("#btnFiltres")
        self.page.click("#voile", position={"x": 380, "y": 400})        # clic sur le voile
        self.page.wait_for_selector("#cat", state="hidden")
        self.page.click("#btnFiltres")
        self.page.click("#btnReset")
        self.assertTrue(self.page.is_hidden("#nbFiltres"))
        self.page.click("#btnFermerFiltres")                            # ✕
        self.page.wait_for_selector("#cat", state="hidden")
        self.page.set_viewport_size({"width": 1200, "height": 800})     # retour grand écran : colonne visible
        self.assertTrue(self.page.is_visible("#cat"))

    def test_filtres_tri_et_reinitialisation(self):
        self.ouvrir()
        self.charger([recette(1, note=4.9, total_min=30, categorie="Plat"),
                      recette(2, note=3.5, total_min=90, categorie="Dessert"),
                      recette(3, note=4.5, total_min=10, categorie="Plat")])
        ordre = lambda: self.page.locator(".card h3").all_text_contents()   # noqa: E731
        self.assertEqual(ordre(), ["Recette 1", "Recette 3", "Recette 2"])      # tri par note
        self.page.select_option("#tri", "temps")
        self.assertEqual(ordre(), ["Recette 3", "Recette 1", "Recette 2"])
        self.page.select_option("#tri", "nom")
        self.assertEqual(ordre(), ["Recette 1", "Recette 2", "Recette 3"])
        self.page.select_option("#nmin", "4")
        self.assertEqual(ordre(), ["Recette 1", "Recette 3"])
        self.page.select_option("#nmin", "0")
        self.page.select_option("#cat", "Dessert")
        self.assertEqual(ordre(), ["Recette 2"])
        self.page.select_option("#cat", "")
        self.page.eval_on_selector("#tmax", "e => { e.value = 40; e.dispatchEvent(new Event('input')); }")
        self.assertEqual(self.page.inner_text("#tmaxVal"), "40 min")
        self.assertEqual(ordre(), ["Recette 1", "Recette 3"])
        self.page.click("#btnSurprise")                                 # 🎲 : bandeau + relance + retour
        self.assertIn("Sélection au hasard", self.page.inner_text("#grid"))
        self.page.click("#reroll")
        self.assertIn("Sélection au hasard", self.page.inner_text("#grid"))
        self.page.click("#voirTout")
        self.assertNotIn("Sélection au hasard", self.page.inner_text("#grid"))
        self.page.fill("#q", "Recette 3")
        self.page.click("#btnReset")                                    # tout revient à zéro
        self.assertEqual(self.page.input_value("#q"), "")
        self.assertEqual(self.page.input_value("#tri"), "note")
        self.assertEqual(self.page.inner_text("#tmaxVal"), "illimité")
        self.assertEqual(self.page.locator(".card").count(), 3)

    def test_vider_la_base(self):
        self.ouvrir()
        self.charger([recette(1)])
        self.page.once("dialog", lambda d: d.dismiss())                 # « Annuler » : rien ne change
        self.page.click("#btnClear")
        self.assertEqual(self.page.locator(".card").count(), 1)
        self.page.once("dialog", lambda d: d.accept())
        self.page.click("#btnClear")
        self.assertEqual(self.page.locator(".card").count(), 0)
        self.assertIn("Aucune recette chargée", self.page.inner_text("#grid"))
        self.assertEqual(self.page.inner_text("#count"), "0 / 0 recette")

    def test_fermeture_des_fenetres(self):
        self.ouvrir()
        self.charger([recette(1)])
        for ouvrir, dialogue in (("#btnImport", "#dlgImport"), ("#btnPanier", "#dlgPanier"), ("#btnExport", "#dlgExport")):
            self.page.click(ouvrir)
            self.assertTrue(self.ouvert(dialogue), dialogue)
            self.assertEqual(self.page.locator(f"{dialogue} [data-close][aria-label='Fermer']").count(), 1)
            self.page.click(f"{dialogue} .dlg-head [data-close]")       # ✕
            self.assertFalse(self.ouvert(dialogue), dialogue)
            self.page.click(ouvrir)
            self.page.keyboard.press("Escape")                          # Échap
            self.assertFalse(self.ouvert(dialogue), dialogue)

    def test_charger_json_par_le_bouton(self):
        self.ouvrir()
        with self.page.expect_file_chooser() as choix:
            self.page.click("#btnCharger")                              # le vrai bouton 📂
        choix.value.set_files({"name": "a.json", "mimeType": "application/json",
                               "buffer": json.dumps([recette(1)]).encode()})
        self.page.wait_for_selector(".card")
        self.assertIn("1 recette ajoutée(s)", self.alertes_toast())

    def test_charger_json_au_clavier(self):
        self.ouvrir()
        self.page.focus("#btnCharger")
        with self.page.expect_file_chooser() as choix:
            self.page.keyboard.press("Enter")                           # sans souris
        choix.value.set_files({"name": "a.json", "mimeType": "application/json",
                               "buffer": json.dumps([recette(1)]).encode()})
        self.page.wait_for_selector(".card")
        self.assertIn("1 recette ajoutée(s)", self.alertes_toast())

    # ---------- fichiers et stockage ----------
    def test_plusieurs_fichiers_charges_d_un_coup(self):
        self.ouvrir()
        self.page.set_input_files("#file", [
            {"name": f"{i}.json", "mimeType": "application/json", "buffer": json.dumps([recette(i)]).encode()}
            for i in (1, 2, 3)])
        self.page.wait_for_function("() => document.querySelectorAll('.card').length === 3", polling=100)

    def test_fichier_trop_volumineux_refuse(self):
        messages = []
        self.page.on("dialog", lambda d: (messages.append(d.message), d.accept()))
        self.ouvrir()
        enorme = b'[{"nom": "enorme", "etapes": ["' + b"y" * (26 * 1024 * 1024) + b'"]}]'
        self.page.set_input_files("#file", {"name": "enorme.json", "mimeType": "application/json", "buffer": enorme})
        self.page.wait_for_timeout(300)
        self.assertEqual(len(messages), 1)
        self.assertIn("Fichier trop volumineux : enorme.json", messages[0])
        self.assertIn("Maximum 25,0 Mo", messages[0])
        self.assertEqual(self.page.locator(".card").count(), 0)

    def test_stockage_plein_alerte_unique(self):
        self.ouvrir()
        self.page.evaluate("""() => { Storage.prototype.setItem = function () {
            throw new DOMException("plein", "QuotaExceededError"); }; }""")
        self.charger([recette(1)])
        self.page.locator(".card [data-fav]").click()
        self.page.locator(".card [data-fav]").click()                   # d'autres enregistrements ratés
        avertissements = [m for m in self.alertes_toast() if m.startswith("⚠ Stockage du navigateur plein")]
        self.assertEqual(len(avertissements), 1, "une seule alerte")
        self.assertEqual(self.page.locator(".card").count(), 1, "les recettes restent utilisables en mémoire")

    # ---------- nom d'hôte personnalisé (RECETTES_HOTES) ----------
    def test_nom_d_hote_personnalise_appelle_le_bon_serveur(self):
        try:
            socket.gethostbyname("monpc.local")
        except OSError:
            if self.moteur == "webkit":
                self.skipTest("monpc.local ne se résout pas (ajouter « 127.0.0.1 monpc.local » à /etc/hosts)")
        url = self.url.replace("127.0.0.1", "monpc.local")
        appels = []
        self.page.on("request", lambda r: appels.append(urlparse(r.url).netloc) if "/api/" in r.url else None)
        with mock.patch.object(s, "HOTES", s.HOTES | {"monpc.local"}):
            self.ouvrir(url)
            self.importer_url(recette(5)["url"])
            self.attendre_journal("✓ Recette 5")
        self.assertIn("serveur", self.page.inner_text("#srvStatus"))
        hote = urlparse(url).netloc
        self.assertEqual(set(appels), {hote}, "aucun appel vers localhost")


if __name__ == "__main__":
    unittest.main()
