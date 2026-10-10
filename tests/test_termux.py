"""Scripts Termux (termux/) : exécutés pour de vrai avec de faux curl / python / termux-wake-lock.
Ignorés si bash n'est pas disponible (ex. Windows sans Git Bash)."""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TERMUX = os.path.join(RACINE, "termux")
SCRIPTS = ("Recettes", "Recettes-maj", "installer.sh")
BASH = shutil.which("bash")

FAUX_CURL = r"""#!/bin/bash
# copie un fichier local au lieu de télécharger ; FAUX_ECHEC_SUR = fragment d'URL qui échoue
out=""; url=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; http*) url="$1";; esac; shift; done
echo "$url" >> "$FAUX_JOURNAL"
if [ -n "$FAUX_ECHEC_SUR" ]; then case "$url" in *"$FAUX_ECHEC_SUR"*) exit 22;; esac; fi
cp "$FAUX_SOURCES/$(basename "$url")" "$out"
"""
FAUX_PYTHON = '#!/bin/bash\nexec "%s" "$@"\n' % sys.executable
FAUX_PYTHON_ESPION = '#!/bin/bash\necho "python $* (dans $(pwd))" >> "$FAUX_JOURNAL"\n'
FAUX_VERROU = '#!/bin/bash\necho "$(basename "$0")" >> "$FAUX_JOURNAL"\n'


def ecrire(chemin, contenu, executable=True):
    with open(chemin, "w", encoding="utf-8", newline="\n") as f:
        f.write(contenu)
    if executable:
        os.chmod(chemin, os.stat(chemin).st_mode | stat.S_IEXEC)


@unittest.skipIf(BASH is None, "bash introuvable")
class ScriptsTermux(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dossier = os.path.join(self.tmp.name, "recettes")
        self.home = os.path.join(self.tmp.name, "home")
        self.bin = os.path.join(self.tmp.name, "bin")
        self.journal = os.path.join(self.tmp.name, "journal.txt")
        for d in (self.dossier, self.home, self.bin):
            os.makedirs(d)
        open(self.journal, "w").close()
        ecrire(os.path.join(self.bin, "curl"), FAUX_CURL)

    def lancer(self, script, sources=RACINE, **env_extra):
        env = dict(os.environ, HOME=self.home, FAUX_JOURNAL=self.journal, FAUX_SOURCES=sources,
                   PATH=self.bin + os.pathsep + os.environ["PATH"], **env_extra)
        return subprocess.run([BASH, os.path.join(TERMUX, script)], env=env, cwd=self.tmp.name,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)

    def journal_lignes(self):
        with open(self.journal, encoding="utf-8") as f:
            return f.read().splitlines()

    def lire(self, *chemin):
        with open(os.path.join(*chemin), encoding="utf-8") as f:
            return f.read()

    # ---------- forme des scripts ----------
    def test_syntaxe_shebang_et_fins_de_ligne(self):
        for nom in SCRIPTS:
            chemin = os.path.join(TERMUX, nom)
            with open(chemin, "rb") as f:
                brut = f.read()
            self.assertTrue(brut.startswith(b"#!/data/data/com.termux/files/usr/bin/bash\n"), nom)
            self.assertNotIn(b"\r", brut, f"{nom} : fins de ligne CRLF")
            r = subprocess.run([BASH, "-n", chemin], capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stderr), (0, ""), nom)

    # ---------- Recettes-maj ----------
    def test_maj_remplace_les_deux_fichiers_sans_toucher_la_base(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            ecrire(os.path.join(self.dossier, nom), "ANCIEN", executable=False)
        ecrire(os.path.join(self.dossier, "recettes_marmiton.json"), '[{"nom": "ma recette"}]', executable=False)
        r = self.lancer("Recettes-maj", RECETTES_DOSSIER=self.dossier)
        self.assertEqual(r.returncode, 0, r.stderr)
        for nom in ("serveur_recettes.py", "generateur-recettes.html", "pdf_recettes.py"):
            self.assertEqual(self.lire(self.dossier, nom), self.lire(RACINE, nom), nom)
        self.assertEqual(self.lire(self.dossier, "recettes_marmiton.json"), '[{"nom": "ma recette"}]')
        self.assertEqual(sorted(os.listdir(self.dossier)),
                         ["generateur-recettes.html", "pdf_recettes.py", "recettes_marmiton.json", "serveur_recettes.py"],
                         "aucun reste .tmp")
        self.assertTrue(all("/v1.1.0/" in u for u in self.journal_lignes()), "version par défaut épinglée")
        self.assertIn("serveur_recettes ", r.stdout)                    # --version affichée

    def test_maj_version_au_choix(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        self.lancer("Recettes-maj", RECETTES_DOSSIER=self.dossier, RECETTES_VERSION="main")
        self.assertTrue(all("/main/" in u for u in self.journal_lignes()))

    def test_maj_echec_ne_modifie_rien(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            ecrire(os.path.join(self.dossier, nom), "ANCIEN", executable=False)
        r = self.lancer("Recettes-maj", RECETTES_DOSSIER=self.dossier, FAUX_ECHEC_SUR="generateur-recettes.html")
        self.assertEqual(r.returncode, 1)
        self.assertIn("rien n'a été modifié", r.stdout)
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            self.assertEqual(self.lire(self.dossier, nom), "ANCIEN", f"{nom} modifié malgré l'échec")
        self.assertEqual(sorted(os.listdir(self.dossier)), ["generateur-recettes.html", "serveur_recettes.py"])

    def test_maj_module_pdf_facultatif(self):
        """Une version sans pdf_recettes.py (ex. v1.0.0) se met quand même à jour."""
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        r = self.lancer("Recettes-maj", RECETTES_DOSSIER=self.dossier, FAUX_ECHEC_SUR="pdf_recettes.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("eFarmz (PDF) restera indisponible", r.stdout)
        self.assertEqual(sorted(os.listdir(self.dossier)), ["generateur-recettes.html", "serveur_recettes.py"])

    def test_maj_dossier_introuvable(self):
        r = self.lancer("Recettes-maj", RECETTES_DOSSIER=os.path.join(self.tmp.name, "absent"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("Dossier introuvable", r.stdout)
        self.assertEqual(self.journal_lignes(), [], "aucun téléchargement tenté")

    # ---------- Recettes ----------
    def test_lancement_dans_le_bon_dossier_avec_verrou(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON_ESPION)
        ecrire(os.path.join(self.bin, "termux-wake-lock"), FAUX_VERROU)
        ecrire(os.path.join(self.bin, "termux-wake-unlock"), FAUX_VERROU)
        r = self.lancer("Recettes", RECETTES_DOSSIER=self.dossier)
        self.assertEqual(r.returncode, 0, r.stderr)
        lignes = self.journal_lignes()
        self.assertEqual(lignes[0], "termux-wake-lock")
        self.assertTrue(lignes[1].startswith("python serveur_recettes.py"), lignes[1])
        self.assertIn(os.path.basename(self.dossier), lignes[1])          # exécuté dans le dossier des recettes
        self.assertEqual(lignes[-1], "termux-wake-unlock", "verrou relâché à la sortie")

    def test_lancement_sans_termux_api(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON_ESPION)      # pas de termux-wake-lock : pas d'erreur
        r = self.lancer("Recettes", RECETTES_DOSSIER=self.dossier)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.journal_lignes()), 1)

    def test_lancement_dossier_introuvable(self):
        r = self.lancer("Recettes", RECETTES_DOSSIER=os.path.join(self.tmp.name, "absent"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("Dossier introuvable", r.stdout)

    # ---------- installer.sh ----------
    def installer(self, **env):
        return self.lancer("installer.sh", sources=TERMUX, RECETTES_BASE_URL="https://exemple.test/termux",
                           RECETTES_RACCOURCIS=os.path.join(self.home, ".shortcuts"), **env)

    def test_installateur_et_alias_sans_doublon(self):
        for _ in range(2):                                                 # relancé : même résultat
            r = self.installer()
            self.assertEqual(r.returncode, 0, r.stderr)
        for nom in ("Recettes", "Recettes-maj"):
            chemin = os.path.join(self.home, ".shortcuts", nom)
            self.assertEqual(self.lire(chemin), self.lire(TERMUX, nom))
            self.assertTrue(os.access(chemin, os.X_OK), f"{nom} non exécutable")
        bashrc = self.lire(self.home, ".bashrc")
        self.assertEqual(bashrc.count("alias recettes="), 1)
        self.assertEqual(bashrc.count("alias recettes-maj="), 1)
        self.assertIn(os.path.join(self.home, ".shortcuts", "Recettes"), bashrc)
        self.assertEqual(sorted(os.listdir(os.path.join(self.home, ".shortcuts"))), ["Recettes", "Recettes-maj"])

    def test_installateur_echec_laisse_les_raccourcis_existants(self):
        self.installer()
        chemin = os.path.join(self.home, ".shortcuts", "Recettes-maj")
        ecrire(chemin, "#!/bin/bash\necho personnalisé\n")
        r = self.installer(FAUX_ECHEC_SUR="Recettes-maj")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("personnalisé", self.lire(chemin), "raccourci existant conservé")
        self.assertFalse([f for f in os.listdir(os.path.join(self.home, ".shortcuts")) if f.endswith(".tmp")])


if __name__ == "__main__":
    unittest.main()
