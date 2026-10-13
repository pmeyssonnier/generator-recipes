"""Tests de l'archive à distribuer (outils/construire_archive.py) : python -m unittest discover -s tests"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(RACINE, "outils"))
import construire_archive as ca  # noqa: E402


class Archive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.chemin = ca.construire(cls.tmp)
        cls.zip = zipfile.ZipFile(cls.chemin)

    @classmethod
    def tearDownClass(cls):
        cls.zip.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_nom_avec_la_version(self):
        self.assertEqual(os.path.basename(self.chemin), f"recettes-v{ca.version()}.zip")

    def test_contenu(self):
        attendu = {"serveur_recettes.py", "pdf_recettes.py", "generateur-recettes.html", "lancer-recettes.bat",
                   "lancer-recettes.sh", "lancer-recettes.command", "eFarmz/LISEZMOI.txt", "LICENSE", "LISEZMOI.txt"}
        self.assertEqual({n.split("/", 1)[1] for n in self.zip.namelist()}, attendu)

    def test_lanceurs_executables_et_fins_de_ligne_unix(self):
        for nom in ("lancer-recettes.sh", "lancer-recettes.command"):
            info = self.zip.getinfo(f"recettes/{nom}")
            self.assertEqual((info.external_attr >> 16) & 0o111, 0o111, nom)
            self.assertNotIn(b"\r", self.zip.read(info))

    def test_lanceur_windows_en_crlf(self):
        bat = self.zip.read("recettes/lancer-recettes.bat")
        self.assertIn(b"\r\n", bat)
        self.assertNotIn(b"\n", bat.replace(b"\r\n", b""))

    def test_mode_d_emploi_porte_la_version(self):
        texte = self.zip.read("recettes/LISEZMOI.txt").decode("utf-8")
        self.assertIn(f"version {ca.version()}", texte)
        self.assertNotIn("{VERSION}", texte)

    def test_archive_reproductible(self):
        autre = tempfile.mkdtemp()
        try:
            with open(ca.construire(autre), "rb") as a, open(self.chemin, "rb") as b:
                self.assertEqual(a.read(), b.read())
        finally:
            shutil.rmtree(autre, ignore_errors=True)

    def test_serveur_de_l_archive_demarre(self):
        dossier = tempfile.mkdtemp()
        try:
            self.zip.extractall(dossier)
            sortie = subprocess.run([sys.executable, "-I", "serveur_recettes.py", "--version"], cwd=os.path.join(dossier, "recettes"),
                                    capture_output=True, text=True, timeout=30).stdout
            self.assertIn(ca.version(), sortie)
        finally:
            shutil.rmtree(dossier, ignore_errors=True)

    def test_syntaxe_des_lanceurs_unix(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash absent")
        for nom in ("lancer-recettes.sh", "lancer-recettes.command"):
            self.assertEqual(subprocess.run([bash, "-n", os.path.join(RACINE, "pc", nom)]).returncode, 0, nom)


if __name__ == "__main__":
    unittest.main()
