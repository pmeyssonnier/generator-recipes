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
if [ -n "$out" ]; then cp "$FAUX_SOURCES/$(basename "$url")" "$out"; else cat "$FAUX_SOURCES/$(basename "$url")"; fi
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

    def sources_release(self, tag="v9.9.9"):
        """Faux dépôt : les fichiers de l'application, les scripts Termux et la réponse de l'API « latest »."""
        d = os.path.join(self.tmp.name, "sources")
        os.makedirs(d, exist_ok=True)
        for nom in ("serveur_recettes.py", "generateur-recettes.html", "pdf_recettes.py"):
            shutil.copy(os.path.join(RACINE, nom), d)
        for nom in ("Recettes", "Recettes-maj"):
            shutil.copy(os.path.join(TERMUX, nom), d)
        with open(os.path.join(d, "latest"), "w", encoding="utf-8") as f:
            f.write('{\n  "url": "x",\n  "tag_name": "%s",\n  "name": "Une release"\n}\n' % tag)
        return d

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
    def test_maj_remplace_les_fichiers_sans_toucher_la_base(self):
        """Sans RECETTES_VERSION : la dernière release publiée est cherchée, puis téléchargée."""
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            ecrire(os.path.join(self.dossier, nom), "ANCIEN", executable=False)
        ecrire(os.path.join(self.dossier, "recettes_marmiton.json"), '[{"nom": "ma recette"}]', executable=False)
        r = self.lancer("Recettes-maj", sources=self.sources_release("v9.9.9"), RECETTES_DOSSIER=self.dossier)
        self.assertEqual(r.returncode, 0, r.stderr)
        for nom in ("serveur_recettes.py", "generateur-recettes.html", "pdf_recettes.py"):
            self.assertEqual(self.lire(self.dossier, nom), self.lire(RACINE, nom), nom)
        self.assertEqual(self.lire(self.dossier, "recettes_marmiton.json"), '[{"nom": "ma recette"}]')
        self.assertEqual(sorted(os.listdir(self.dossier)),
                         ["generateur-recettes.html", "pdf_recettes.py", "recettes_marmiton.json", "serveur_recettes.py"],
                         "aucun reste .tmp")
        lignes = self.journal_lignes()
        self.assertIn("/releases/latest", lignes[0])
        self.assertTrue(all("/v9.9.9/" in u for u in lignes[1:]), "les fichiers viennent de la release trouvée")
        self.assertIn("Version : v9.9.9", r.stdout)
        self.assertIn("serveur_recettes ", r.stdout)                    # --version affichée

    def test_maj_ne_revient_pas_en_arriere(self):
        """Serveur installé en 1.5.1 (après « main »), dernière release publiée 1.5.0 : rien n'est téléchargé ni remplacé."""
        ecrire(os.path.join(self.bin, "python"), '#!/bin/bash\necho "serveur_recettes 1.5.1"\n')
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            ecrire(os.path.join(self.dossier, nom), "INSTALLE", executable=False)
        r = self.lancer("Recettes-maj", sources=self.sources_release("v1.5.0"), RECETTES_DOSSIER=self.dossier)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("plus récente", r.stdout)
        self.assertEqual(self.lire(self.dossier, "serveur_recettes.py"), "INSTALLE")
        self.assertEqual(len(self.journal_lignes()), 1, "seul l'appel à l'API des releases")

    def test_maj_version_imposee_permet_de_revenir_en_arriere(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        ecrire(os.path.join(self.dossier, "serveur_recettes.py"), "INSTALLE", executable=False)
        r = self.lancer("Recettes-maj", sources=self.sources_release("v1.5.0"), RECETTES_DOSSIER=self.dossier,
                        RECETTES_VERSION="v1.5.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.lire(self.dossier, "serveur_recettes.py"), self.lire(RACINE, "serveur_recettes.py"))

    def test_maj_version_au_choix(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        self.lancer("Recettes-maj", RECETTES_DOSSIER=self.dossier, RECETTES_VERSION="main")
        self.assertTrue(all("/main/" in u for u in self.journal_lignes()))
        self.assertFalse(any("releases/latest" in u for u in self.journal_lignes()), "version imposée : pas d'appel à l'API")

    def test_maj_derniere_version_introuvable(self):
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            ecrire(os.path.join(self.dossier, nom), "ANCIEN", executable=False)
        r = self.lancer("Recettes-maj", sources=self.sources_release(), RECETTES_DOSSIER=self.dossier,
                        FAUX_ECHEC_SUR="releases/latest")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Dernière version introuvable", r.stdout)
        self.assertIn("RECETTES_VERSION=", r.stdout)
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            self.assertEqual(self.lire(self.dossier, nom), "ANCIEN")

    def test_maj_version_invalide_refusee(self):
        r = self.lancer("Recettes-maj", RECETTES_DOSSIER=self.dossier, RECETTES_VERSION="../main")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Version invalide", r.stdout)
        self.assertEqual(self.journal_lignes(), [], "aucun téléchargement tenté")

    def test_maj_met_a_jour_les_scripts_de_raccourci(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        raccourcis = os.path.join(self.tmp.name, "shortcuts")
        os.makedirs(raccourcis)
        for nom in ("Recettes", "Recettes-maj"):
            ecrire(os.path.join(raccourcis, nom), "#!/bin/bash\necho ANCIEN\n")
        r = self.lancer("Recettes-maj", sources=self.sources_release(), RECETTES_DOSSIER=self.dossier,
                        RECETTES_RACCOURCIS=raccourcis)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Scripts de raccourci mis à jour", r.stdout)
        for nom in ("Recettes", "Recettes-maj"):
            self.assertEqual(self.lire(raccourcis, nom), self.lire(TERMUX, nom), nom)
            self.assertTrue(os.access(os.path.join(raccourcis, nom), os.X_OK), f"{nom} exécutable")
        self.assertEqual(sorted(os.listdir(raccourcis)), ["Recettes", "Recettes-maj"], "aucun reste .tmp")

    def test_maj_depuis_le_raccourci_installe_se_remplace_sans_planter(self):
        """Le script exécuté depuis ~/.shortcuts se remplace lui-même pendant son exécution."""
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        raccourcis = os.path.join(self.tmp.name, "shortcuts")
        os.makedirs(raccourcis)
        shutil.copy(os.path.join(TERMUX, "Recettes"), raccourcis)
        copie = os.path.join(raccourcis, "Recettes-maj")
        shutil.copy(os.path.join(TERMUX, "Recettes-maj"), copie)
        env = dict(os.environ, HOME=self.home, FAUX_JOURNAL=self.journal, FAUX_SOURCES=self.sources_release("v9.9.9"),
                   PATH=self.bin + os.pathsep + os.environ["PATH"], RECETTES_DOSSIER=self.dossier,
                   RECETTES_RACCOURCIS=raccourcis)
        r = subprocess.run([BASH, copie], env=env, cwd=self.tmp.name, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn("Scripts de raccourci mis à jour", r.stdout)
        self.assertEqual(self.lire(raccourcis, "Recettes-maj"), self.lire(TERMUX, "Recettes-maj"))

    def test_maj_scripts_de_raccourci_non_installes_ignores(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        r = self.lancer("Recettes-maj", sources=self.sources_release(), RECETTES_DOSSIER=self.dossier,
                        RECETTES_RACCOURCIS=os.path.join(self.tmp.name, "absent"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Scripts de raccourci", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "absent")), "rien n'est créé hors installation")

    def test_maj_echec_des_scripts_de_raccourci_n_annule_pas_la_maj(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        raccourcis = os.path.join(self.tmp.name, "shortcuts")
        os.makedirs(raccourcis)
        for nom in ("Recettes", "Recettes-maj"):
            ecrire(os.path.join(raccourcis, nom), "ANCIEN")
        r = self.lancer("Recettes-maj", sources=self.sources_release(), RECETTES_DOSSIER=self.dossier,
                        RECETTES_RACCOURCIS=raccourcis, FAUX_ECHEC_SUR="termux/Recettes-maj")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("non mis à jour", r.stdout)
        self.assertEqual(self.lire(self.dossier, "serveur_recettes.py"), self.lire(RACINE, "serveur_recettes.py"))
        for nom in ("Recettes", "Recettes-maj"):
            self.assertEqual(self.lire(raccourcis, nom), "ANCIEN", f"{nom} inchangé")
        self.assertEqual(sorted(os.listdir(raccourcis)), ["Recettes", "Recettes-maj"], "aucun reste .tmp")

    def test_maj_echec_ne_modifie_rien(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            ecrire(os.path.join(self.dossier, nom), "ANCIEN", executable=False)
        r = self.lancer("Recettes-maj", sources=self.sources_release(), RECETTES_DOSSIER=self.dossier,
                        FAUX_ECHEC_SUR="generateur-recettes.html")
        self.assertEqual(r.returncode, 1)
        self.assertIn("rien n'a été modifié", r.stdout)
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            self.assertEqual(self.lire(self.dossier, nom), "ANCIEN", f"{nom} modifié malgré l'échec")
        self.assertEqual(sorted(os.listdir(self.dossier)), ["generateur-recettes.html", "serveur_recettes.py"])

    def faux_mv(self, echec_sur, aussi_les_bak=False):
        """mv qui échoue quand la destination est `echec_sur` (et, si demandé, quand la source est une sauvegarde .bak)."""
        reel = shutil.which("mv")
        ecrire(os.path.join(self.bin, "mv"),
               '#!/bin/bash\nfor dernier; do :; done\n'
               f'if [ "$dernier" = "{echec_sur}" ]; then exit 1; fi\n'
               + ('case "$1" in *.bak) exit 1;; esac\n' if aussi_les_bak else "")
               + f'exec "{reel}" "$@"\n')

    def test_maj_panne_au_deuxieme_remplacement_restaure_tout(self):
        """Transactionnelle : si le 2e fichier ne peut pas être remplacé, le 1er revient à l'ancienne version."""
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            ecrire(os.path.join(self.dossier, nom), "ANCIEN", executable=False)
        self.faux_mv("generateur-recettes.html")
        r = self.lancer("Recettes-maj", sources=self.sources_release(), RECETTES_DOSSIER=self.dossier)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("Les fichiers d'origine ont été restaurés", r.stdout)
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            self.assertEqual(self.lire(self.dossier, nom), "ANCIEN", nom)
        self.assertEqual(sorted(os.listdir(self.dossier)), ["generateur-recettes.html", "serveur_recettes.py"],
                         "ni .tmp ni .bak, et pdf_recettes.py (nouveau) n'est pas resté")

    def test_maj_restauration_impossible_gardee_et_signalee(self):
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        for nom in ("serveur_recettes.py", "generateur-recettes.html"):
            ecrire(os.path.join(self.dossier, nom), "ANCIEN", executable=False)
        self.faux_mv("generateur-recettes.html", aussi_les_bak=True)
        r = self.lancer("Recettes-maj", sources=self.sources_release(), RECETTES_DOSSIER=self.dossier)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Restauration incomplète pour : serveur_recettes.py", r.stdout)
        self.assertNotIn("ont été restaurés", r.stdout)
        self.assertEqual(self.lire(self.dossier, "serveur_recettes.py.bak"), "ANCIEN")       # seule copie : conservée
        self.assertEqual(self.lire(self.dossier, "generateur-recettes.html"), "ANCIEN")

    def test_maj_module_pdf_facultatif(self):
        """Une version sans pdf_recettes.py (ex. v1.0.0) se met quand même à jour."""
        ecrire(os.path.join(self.bin, "python"), FAUX_PYTHON)
        r = self.lancer("Recettes-maj", sources=self.sources_release(), RECETTES_DOSSIER=self.dossier,
                        FAUX_ECHEC_SUR="pdf_recettes.py")
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
