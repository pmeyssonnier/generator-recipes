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

    def get(self, path, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {})
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
            def read(self): return b"ok"
        (res, o) = self.appeler("https://marmiton.org/x", self.redir("https://www.marmiton.org/x"), Rep())
        self.assertEqual(res[0], b"ok")
        self.assertEqual(o.call_count, 2)

    def test_boucle_de_redirections(self):
        res, _ = self.appeler("https://www.marmiton.org/x", *[self.redir("https://www.marmiton.org/x")] * 10)
        self.assertIsInstance(res, s.AccesInterdit)


if __name__ == "__main__":
    unittest.main()
