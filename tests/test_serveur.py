"""Tests hors-ligne du serveur : python -m unittest discover -s tests"""
import io
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from email.message import Message
from unittest import mock
from urllib.error import HTTPError

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import serveur_recettes as s  # noqa: E402


class Duree(unittest.TestCase):
    def test_valeurs(self):
        self.assertEqual(s.iso_duration_to_min("PT1H30M"), 90)
        self.assertEqual(s.iso_duration_to_min("PT45M"), 45)
        self.assertEqual(s.iso_duration_to_min("P1DT2H"), 1560)

    def test_inconnue(self):
        for v in ("PT0S", "PT45S", "P0D", "", None, "abc", "PT"):
            self.assertIsNone(s.iso_duration_to_min(v), v)


class Parametres(unittest.TestCase):
    def test_entier(self):
        self.assertEqual(s.entier(None, 10, 1, 50), 10)
        self.assertEqual(s.entier("999", 10, 1, 50), 50)
        self.assertEqual(s.entier("0", 10, 1, 50), 1)
        with self.assertRaises(s.ParametreInvalide):
            s.entier("abc", 10, 1, 50)


class Hotes(unittest.TestCase):
    def test_hote_ok(self):
        for h in ("localhost:8765", "127.0.0.1:8765", "[::1]:8765", "localhost"):
            self.assertTrue(s.hote_ok(h), h)
        for h in ("evil.com", "evil.com:8765", "localhost.evil.com", "", None, "192.168.1.5:8765"):
            self.assertFalse(s.hote_ok(h), h)

    def test_hote_ok_lan(self):
        with mock.patch.object(s, "LAN", True):
            self.assertTrue(s.hote_ok("192.168.1.5:8765"))
            self.assertFalse(s.hote_ok("8.8.8.8:8765"))
            self.assertFalse(s.hote_ok("evil.com:8765"))


class Serveur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = s.ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, path, headers=None, method="GET"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_fichiers_sensibles_non_servis(self):
        for p in ("/serveur_recettes.py", "/.git/config", "/.git/HEAD", "/colab/", "/recettes.json", "/recettes_marmiton.json",
                  "/../serveur_recettes.py", "/README.md"):
            self.assertEqual(self.get(p)[0], 404, p)

    def test_page_servie(self):
        code, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"<title>", body)

    def test_dns_rebinding(self):
        # même schéma d'attaque : Host et Origin contrôlés par un site pirate
        code, _ = self.get("/api/ping", {"Host": "evil.com:8765", "Origin": "http://evil.com:8765"})
        self.assertEqual(code, 403)
        self.assertEqual(self.get("/", {"Host": "evil.com"})[0], 403)

    def test_origine_etrangere(self):
        self.assertEqual(self.get("/api/ping", {"Origin": "http://evil.com"})[0], 403)
        self.assertEqual(self.get("/api/ping")[0], 200)

    def test_n_invalide(self):
        code, body = self.get("/api/search?q=x&n=abc")
        self.assertEqual(code, 400)
        self.assertIn("erreur", json.loads(body))

    def test_post_exige_l_en_tete_x_recettes(self):
        url = "/api/recipe?url=https://evil.example/x"
        self.assertEqual(self.get(url, method="POST")[0], 403)                       # en-tête manquant
        code, body = self.get(url, {"X-Recettes": "1"}, "POST")
        self.assertEqual(code, 400)                                                  # accepté, mais site non autorisé
        self.assertIn("Site non autorisé", json.loads(body)["erreur"])

    def test_post_origine_etrangere_refusee(self):
        h = {"X-Recettes": "1", "Origin": "http://evil.com"}
        self.assertEqual(self.get("/api/recipe?url=https://www.marmiton.org/x", h, "POST")[0], 403)
        h = {"X-Recettes": "1", "Host": "evil.com", "Origin": "http://evil.com"}       # DNS rebinding
        self.assertEqual(self.get("/api/recipe?url=https://www.marmiton.org/x", h, "POST")[0], 403)

    def test_get_n_ecrit_jamais(self):
        self.assertEqual(self.get("/api/recipe?url=https://www.marmiton.org/x")[0], 405)
        self.assertEqual(self.get("/api/ping", {"X-Recettes": "1"}, "POST")[0], 405)

    def test_post_enregistre_la_recette(self):
        import tempfile
        rec = {"url": "https://www.marmiton.org/recettes/recette_a_1.aspx", "nom": "A", "ingredients": []}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(s, "BASE_FILE", os.path.join(d, "r.json")), \
                mock.patch.object(s, "scrape_recipe", return_value=rec):
            code, body = self.get("/api/recipe?url=" + rec["url"], {"X-Recettes": "1"}, "POST")
            self.assertEqual((code, json.loads(body)["nom"]), (200, "A"))
            self.assertEqual([r["nom"] for r in s.lire_base()], ["A"])

    def test_preflight_post_origine_autorisee(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/recipe", method="OPTIONS", headers={
            "Origin": "https://pmeyssonnier.github.io", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-recettes"})
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 204)
            self.assertIn("POST", r.headers["Access-Control-Allow-Methods"])
            self.assertEqual(r.headers["Access-Control-Allow-Origin"], "https://pmeyssonnier.github.io")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/recipe", method="OPTIONS",
                                     headers={"Origin": "http://evil.com"})
        with self.assertRaises(urllib.error.HTTPError) as c:
            urllib.request.urlopen(req)
        self.assertEqual(c.exception.code, 403)

    def test_head_refuse(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/serveur_recettes.py", method="HEAD")
        with self.assertRaises(urllib.error.HTTPError) as c:
            urllib.request.urlopen(req)
        self.assertEqual(c.exception.code, 405)


class Redirections(unittest.TestCase):
    """telecharger() revalide chaque redirection (pas d'accès à un hôte non autorisé)."""

    def redir(self, location, code=302):
        h = Message()
        h["Location"] = location
        return urllib.error.HTTPError("https://www.marmiton.org/x", code, "redir", h, io.BytesIO())

    def appeler(self, url, *reponses):
        suites = list(reponses)

        def faux_open(req, timeout=None):
            r = suites.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with mock.patch.object(s, "robots_autorise", return_value=True), \
                mock.patch.object(s, "PAUSE", 0), \
                mock.patch.object(s._opener, "open", side_effect=faux_open) as o:
            try:
                return s.telecharger(url), o
            except s.AccesInterdit as e:
                return e, o

    def test_vers_hote_interne_refuse(self):
        for cible in ("http://169.254.169.254/latest/", "http://192.168.1.1/", "http://localhost:8765/api/base",
                      "https://evil.com/"):
            res, o = self.appeler("https://www.marmiton.org/x", self.redir(cible))
            self.assertIsInstance(res, s.AccesInterdit, cible)
            self.assertEqual(o.call_count, 1, cible)        # jamais suivi

    def test_retour_en_http_refuse(self):
        res, _ = self.appeler("https://www.marmiton.org/x", self.redir("http://www.marmiton.org/x"))
        self.assertIsInstance(res, s.AccesInterdit)

    def test_redirection_autorisee_suivie(self):
        class Rep:
            headers = Message()
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1): return b"ok"
        (res, o) = self.appeler("https://marmiton.org/x", self.redir("https://www.marmiton.org/x"), Rep())
        self.assertEqual(res[0], b"ok")
        self.assertEqual(o.call_count, 2)

    def test_boucle_de_redirections(self):
        res, _ = self.appeler("https://www.marmiton.org/x", *[self.redir("https://www.marmiton.org/x")] * 10)
        self.assertIsInstance(res, s.AccesInterdit)


if __name__ == "__main__":
    unittest.main()


class Robots(unittest.TestCase):
    """robots.txt : cache à durée limitée, injoignable/5xx = refus (RFC 9309), nom d'agent dédié."""

    def setUp(self):
        s._robots.clear()
        self.addCleanup(s._robots.clear)

    def autorise(self, url, robots=b"", **kw):
        with mock.patch.object(s, "telecharger", **kw or {"return_value": (robots, "utf-8")}) as t:
            return s.robots_autorise(url), t

    def test_regles_generales_et_agent_dedie(self):
        ok, _ = self.autorise("https://www.marmiton.org/recettes/x", b"User-agent: *\nDisallow: /prive\n")
        self.assertTrue(ok)
        ok, _ = self.autorise("https://www.marmiton.org/prive/x", b"User-agent: *\nDisallow: /prive\n")
        self.assertFalse(ok)
        s._robots.clear()
        regles = b"User-agent: *\nDisallow:\n\nUser-agent: RecettesPerso\nDisallow: /recettes/\n"
        ok, _ = self.autorise("https://www.marmiton.org/recettes/x", regles)
        self.assertFalse(ok)                                           # règle visant notre nom

    def test_absent_404_autorise_et_en_cache(self):
        err = HTTPError("u", 404, "nf", None, None)
        ok, t = self.autorise("https://a.test/x", side_effect=err)
        self.assertTrue(ok)
        with mock.patch.object(s, "telecharger", side_effect=AssertionError("pas de nouvelle requête")):
            self.assertTrue(s.robots_autorise("https://a.test/y"))     # servi depuis le cache

    def test_cache_expire(self):
        self.autorise("https://a.test/x", b"User-agent: *\nDisallow:\n")
        with mock.patch.object(s.time, "time", return_value=time_dans(s.ROBOTS_TTL + 5)):
            ok, t = self.autorise("https://a.test/x", b"User-agent: *\nDisallow: /\n")
        self.assertFalse(ok)                                           # robots.txt relu après expiration
        self.assertEqual(t.call_count, 1)

    def test_403_interdit(self):
        ok, _ = self.autorise("https://a.test/x", side_effect=HTTPError("u", 403, "no", None, None))
        self.assertFalse(ok)

    def test_5xx_et_reseau_refuses_sans_memorisation(self):
        for erreur in (HTTPError("u", 503, "ko", None, None), urllib.error.URLError("dns"), TimeoutError("lent")):
            with self.assertRaises(s.AccesInterdit, msg=repr(erreur)):
                self.autorise("https://a.test/x", side_effect=erreur)
            self.assertNotIn("https://a.test", s._robots)             # pas mémorisé : on réessaiera
        ok, _ = self.autorise("https://a.test/x", b"User-agent: *\nDisallow:\n")   # le site revient
        self.assertTrue(ok)


def time_dans(secondes):
    import time
    return time.time() + secondes


class Identite(unittest.TestCase):
    def test_user_agent_s_identifie(self):
        self.assertIn("RecettesPerso", s.HEADERS["User-Agent"])
        self.assertNotIn("Chrome", s.HEADERS["User-Agent"])


class Taille(unittest.TestCase):
    class Rep:
        def __init__(self, data, gzip_=False):
            self.data = data
            self.headers = Message()
            if gzip_:
                self.headers["Content-Encoding"] = "gzip"

        def read(self, n=-1):
            return self.data if n < 0 else self.data[:n]

    def test_page_normale(self):
        import gzip
        self.assertEqual(s.lire_limite(self.Rep(b"abc")), b"abc")
        self.assertEqual(s.lire_limite(self.Rep(gzip.compress(b"abc" * 1000), True)), b"abc" * 1000)

    def test_page_trop_grosse(self):
        with self.assertRaises(s.ReponseTropGrosse):
            s.lire_limite(self.Rep(b"a" * (s.MAX_OCTETS + 1)))

    def test_bombe_gzip(self):
        import gzip
        bombe = gzip.compress(b"a" * (s.MAX_OCTETS + 10))             # quelques Ko compressés
        self.assertLess(len(bombe), 100_000)
        with self.assertRaises(s.ReponseTropGrosse):
            s.lire_limite(self.Rep(bombe, True))

    def test_cache_borne(self):
        s._cache.clear()
        self.addCleanup(s._cache.clear)
        with mock.patch.object(s, "telecharger", return_value=(b"x", "utf-8")):
            for i in range(s.MAX_CACHE + 20):
                s.fetch(f"https://a.test/{i}")
        self.assertEqual(len(s._cache), s.MAX_CACHE)
        self.assertNotIn("https://a.test/0", s._cache)                 # la plus ancienne est évincée
