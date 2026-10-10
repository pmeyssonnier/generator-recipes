# 🍲 Générateur de recettes

Application personnelle pour constituer un carnet de recettes à partir de sites de cuisine
(Marmiton, 750g, Cuisine AZ, Ricardo…), puis les filtrer selon ce qu'on a dans le frigo,
en tirer au sort et préparer une liste de courses.

- **Interface** : un seul fichier HTML/JS, sans dépendance (`generateur-recettes.html`)
- **Serveur** : Python, bibliothèque standard uniquement, aucun `pip install` (`serveur_recettes.py`)
- **Extraction** : données structurées schema.org/Recipe (JSON-LD) publiées par les sites
- **Plateformes** : Windows, Linux, macOS, Android (Termux)

## Fonctionnalités

| Fonction | Détail |
|---|---|
| Import | Recherche par mot-clé sur Marmiton, import par URL depuis les sites de la liste `SITES`, ou lecture de PDF de fiches recettes (eFarmz, avec photo) |
| Sauvegarde | Automatique dans `recettes.json` + stockage du navigateur (l'ancien `recettes_marmiton.json` est renommé automatiquement au lancement) |
| Base illisible | Si `recettes.json` est corrompu, il n'est jamais écrasé : à la prochaine importation il est conservé sous `recettes.json.corrompu-AAAAMMJJ-HHMMSS` (récupérable à la main) et une nouvelle base est créée ; un avertissement s'affiche dans la fenêtre du serveur |
| Filtres | Texte libre, ingrédients avec / sans, temps max, note minimale, catégorie, favoris |
| Affichage | 48 recettes à la fois, bouton « Afficher plus » (la page reste fluide avec plusieurs milliers de recettes) |
| 🎲 Surprends-moi | 3 recettes tirées au hasard parmi les résultats filtrés |
| Fiche recette | Ingrédients à cocher, étapes, lien vers la source |
| 🛒 Courses | Liste agrégée des ingrédients, copiable |
| 💾 Export | JSON de toute la base, de la sélection ou des favoris |

## Démarrage

```bash
python serveur_recettes.py
```

Le navigateur s'ouvre sur <http://localhost:8765>.

Sous Windows, un double-clic sur **`lancer-recettes.bat`** fait la même chose : il met
d'abord le code à jour depuis GitHub (`git pull`, si le dossier est un clone), puis lance
le serveur. Les options se transmettent : `lancer-recettes.bat --lan`.

| Option | Effet |
|---|---|
| `--lan` | Accès depuis un autre appareil du même Wi-Fi (l'adresse s'affiche au lancement) |
| `--no-browser` | N'ouvre pas le navigateur |
| `RECETTES_PORT=8766` | Change le port |
| `RECETTES_ORIGINES=https://a.org,null` | Autorise d'autres sites à appeler l'API (`null` = page ouverte en `file://`) |

Sans serveur, `generateur-recettes.html` s'ouvre aussi en double-clic pour consulter
une base chargée via **📂 Charger JSON**. Pour importer depuis une page ouverte en
`file://`, ouvre plutôt <http://localhost:8765> (ou ajoute `null` à `RECETTES_ORIGINES`).

### Sécurité du serveur local

- L'API n'accepte que la page servie par le serveur lui-même et
  `https://pmeyssonnier.github.io`. Les appels venant d'autres sites sont refusés (403).
- L'en-tête `Host` est vérifié (`localhost`, adresses IP locales ; réseau privé seulement avec
  `--lan`) : cela bloque le *DNS rebinding*. Autre nom d'hôte (ex. `monpc.local`) :
  `RECETTES_HOTES=monpc.local`. La page détecte seule qu'elle est servie par le serveur (sonde `/api/ping` sur sa propre
  origine) : sous n'importe quel nom ou adresse, elle appelle ce serveur et jamais `localhost`.
- Le serveur ne sert **que** la page HTML : ni `.git/`, ni le code source, ni la base JSON.
- L'import par URL est limité aux domaines de `SITES`. Les redirections sont suivies à la main
  et revalidées (domaine autorisé, pas de retour en `http`, `robots.txt`, 5 sauts maximum).
- Ce qui écrit dans la base (`POST /api/recipe`) exige l'en-tête `X-Recettes` : un site tiers ne
  peut pas l'envoyer sans pré-vol CORS, que seules les origines autorisées obtiennent. Les `GET`
  ne modifient jamais rien.
  La page en ligne (GitHub Pages) se met à jour seule : face à un serveur local plus ancien (sans
  `POST`), elle se rabat sur l'ancien `GET` et affiche « serveur ancien » — mets-le alors à jour
  (`git pull`, puis relance-le) pour bénéficier de la protection renforcée.
- `/api/ping` ne révèle que le nom du fichier de la base (pas son chemin) ; les erreurs internes
  renvoient un message générique (le détail reste dans la fenêtre du serveur).
- Un fichier JSON importé est limité à 25 Mo (par chargement) ; si le stockage du navigateur
  (≈ 5 Mo) est plein, une alerte invite à exporter la base.
- Les pages téléchargées sont limitées à 5 Mo (compressées comme décompressées) et 200 pages
  restent en mémoire au maximum.
- La page applique une politique CSP, n'accepte que des URL `http(s)` pour les liens et images
  d'un JSON importé, et affiche les images sans transmettre de référent.

### Version en ligne (GitHub Pages)

<https://pmeyssonnier.github.io/generator-recipes/>

La page en ligne fonctionne sans rien installer pour consulter, filtrer, charger un JSON,
exporter et faire la liste de courses. GitHub Pages ne peut pas exécuter Python : pour
l'**import** de recettes, lance `serveur_recettes.py` sur le même appareil (PC ou Termux),
la page en ligne l'utilisera automatiquement via `http://localhost:8765`.

> **Safari :** une page `https` (GitHub Pages) qui appelle un serveur en `http://localhost` est du
> « contenu mixte », que Safari peut refuser (non vérifié ici : les tests tournent sur des pages
> `http`). Si l'import ne fonctionne pas sous Safari, ouvre plutôt <http://localhost:8765/>, la page
> servie par le serveur lui-même : elle marche dans tous les navigateurs.

Les recettes, favoris et panier restent dans le navigateur de chaque appareil.

### Android (Termux)

Installer Termux depuis F-Droid, puis :

```bash
pkg install -y python termux-api
termux-setup-storage
cd ~/storage/downloads/recettes      # dossier contenant les deux fichiers
termux-wake-lock
python serveur_recettes.py
```

#### Raccourcis et mise à jour (Termux)

Le dossier `termux/` fournit deux scripts : **`Recettes`** (lance le serveur, avec `termux-wake-lock`)
et **`Recettes-maj`** (télécharge `serveur_recettes.py`, `generateur-recettes.html` et, si la version le propose, `pdf_recettes.py` (source eFarmz) ; la base n'est
pas touchée, et rien n'est remplacé si un téléchargement échoue). Installation en une commande :

```bash
curl -fsSL https://raw.githubusercontent.com/pmeyssonnier/generator-recipes/main/termux/installer.sh | bash
```

Elle crée `~/.shortcuts/Recettes` et `~/.shortcuts/Recettes-maj`, et les commandes `recettes` /
`recettes-maj` (alias dans `~/.bashrc`, après avoir rouvert Termux). Pour un **raccourci sur l'écran
d'accueil**, installe l'application *Termux:Widget* (même source que Termux, par exemple F-Droid), puis
ajoute un widget « Termux shortcut ». Le dossier des recettes par défaut est
`~/storage/downloads/recettes` ; `RECETTES_DOSSIER=…` en choisit un autre, et `RECETTES_VERSION=main`
(ou un numéro, par exemple `v1.0.0`, la valeur par défaut) la version téléchargée par `Recettes-maj`.
Ces scripts exécutent du code téléchargé depuis ce dépôt : relis-les avant de les installer.

### Google Colab

`colab/import_recettes_colab.py` fait l'import en lot dans un notebook. Il télécharge
`serveur_recettes.py` depuis GitHub et **réutilise son code** : même extraction JSON-LD, mêmes
sources (Marmiton, PtitChef), mêmes règles (`robots.txt`, pause entre requêtes, domaines de `SITES`).
Il fusionne les recettes dans `recettes.json` (par URL), à charger ensuite dans l'interface.

```python
import_recipes("blanquette", max_results=8)            # recherche (source="ptitchef" possible)
import_url("https://www.marmiton.org/recettes/recette_....aspx")
import_page("https://www.ricardocuisine.com/...")      # page qui liste plusieurs recettes
generer(charger_base(), avec=["veau"], sans=["crème"], max_min=180)
```

## Architecture

```
navigateur (generateur-recettes.html)
   │  GET  /api/search?q=…   /api/liste?url=…   /api/base   /api/ping
   │  POST /api/recipe?url=…   (importe et enregistre ; en-tête X-Recettes)
   ▼
serveur_recettes.py  (127.0.0.1:8765)
   │  urllib → site source, 1,5 s minimum entre deux requêtes
   │  eFarmz/*.pdf → pdf_recettes.py (pdfplumber, facultatif)
   └─ fusionne chaque recette dans recettes.json
```

Le serveur est nécessaire parce que les sites de recettes n'autorisent pas les appels
cross-origin (CORS) depuis une page web.

## Sources

| Site | Recherche par mot-clé | URL d'une recette | URL d'une page de sélection |
|---|---|---|---|
| Marmiton | ✅ recherche libre | ✅ | ✅ |
| PtitChef | ✅ pages thématiques (`lasagnes`, `quiche`…) | ✅ | ✅ |
| Ricardo | — | ✅ | ✅ (chroniques) |
| Cuisine AZ, Jamie Oliver, 750g | — | ✅ | ✅ |
| Autres domaines de `SITES` | — | ✅ | — |

Une **page de sélection** est une page qui liste plusieurs recettes (chronique Ricardo,
page thématique, catégorie…). Colle son URL dans le champ « URL » de la fenêtre d'import :
ses recettes s'affichent à cocher, comme pour une recherche. Le format des URL de recettes
de chaque site est défini dans `MOTIFS_RECETTE`.

Jamie Oliver interdit l'accès automatisé à ses pages de recherche (`robots.txt`).
La recherche du site Ricardo passe par son API, elle aussi interdite aux robots, et son
plan de site (`sitemap.xml`) ne répond pas (erreur 504 après 90 s, constatée le 9 octobre 2026) :
Ricardo s'utilise donc par URL (recette ou chronique).

Pour vérifier que les sources répondent encore (après une mise à jour d'un site) :

```bash
python tester_sources.py            # ou : python tester_sources.py quiche
```

## Navigateurs

La page utilise `<dialog>`, `:focus-visible` et `aspect-ratio`, ce qui suppose un navigateur récent :
Chrome / Edge 99+, Firefox 98+, Safari 15.4+ (minimum déduit des fonctions utilisées). Les tests de
l'interface tournent en CI sur Chromium, Firefox et WebKit (le moteur de Safari), dans leur version
actuelle. Sous Safari sur Mac, la touche Tab n'atteint les boutons que si l'option « Tab met en
évidence chaque élément » est activée (Réglages Safari › Avancé) : c'est un réglage du navigateur.

Pour Safari, le parcours *page en ligne → serveur local* n'est pas couvert par les tests (voir la
note dans « Version en ligne ») ; la page servie par le serveur (`http://localhost:8765/`) l'est.

## Importer des PDF de fiches recettes (eFarmz)

La source **eFarmz (PDF)** de la fenêtre d'import lit les PDF que tu as déposés dans le dossier
**`eFarmz/`**, créé à côté de `serveur_recettes.py` (donc à côté de `recettes.json`). Aucune connexion à un site : tout
se passe sur ton appareil. (Une récupération automatique depuis ton compte pourra venir plus tard.)

1. Dépose tes PDF dans `eFarmz/` (sur Termux : `cp /storage/emulated/0/Download/v375.pdf eFarmz/`).
2. 🌐 Importer → source **eFarmz (PDF)** → choisis le nombre de personnes (colonne « 1p … 6p » du tableau) →
   **Lire les PDF**. Un filtre (titre ou nom de fichier) est facultatif.
3. Le journal montre l'extraction, PDF par PDF puis recette par recette (`✓ Nom (p.2) — 10 ingrédients, 6 étapes, photo p.1`),
   avec les ⚠ à vérifier. Chaque recette a sa miniature et un aperçu déroulant (ingrédients, étapes).
4. Coche une ou plusieurs recettes (ou tout) → **Importer la sélection** : elles sont enregistrées dans `recettes.json`
   avec leur photo et s'affichent dans l'application.

Une page de détail est reconnue à son tableau de quantités (« 1p … 6p ») ; la photo est la plus grande image de la page,
ou de la page photo qui la précède (`PHOTO_PAGE` dans `pdf_recettes.py`). Les photos sont réduites (400 px, JPEG) et
stockées dans le JSON : compte 20 à 60 Ko par recette, et surveille la limite de stockage du navigateur (≈ 5 Mo) si ta
base devient grande. Les PDF scannés (images sans texte) ne sont pas lus : l'OCR n'est pas pris en charge.

Cette source demande une dépendance **facultative** : `pip install pdfplumber` (le reste de l'application n'en a pas besoin).
Sans elle, la source répond « Extraction PDF indisponible ». Sur Termux, l'installation de pdfplumber peut être
difficile (dépendances compilées) : dans ce cas, convertis tes PDF avec `python pdf_recettes.py fichier.pdf` sur un
ordinateur (ou Colab) et charge le JSON produit avec « 📂 Charger JSON ».

## Tests

```bash
python -m unittest discover -s tests     # hors ligne : parseurs JSON-LD, listes de recettes, sources,
                                          # durées, Host, fichiers servis, redirections, base JSON,
                                          # extraction de PDF (si pdfplumber est installé)
```

Les **tests de l'interface** (`tests/test_interface.py`, 25 tests) pilotent un vrai Chromium contre le vrai
serveur (seules l'extraction d'une recette et la recherche sont simulées) et cliquent sur chaque bouton :
Importer (recherche, URL, page de sélection), Exporter (téléchargements), Courses (copie dans le
presse-papiers), favoris, fiche recette, filtres, tri, Surprends-moi, Vider, fermeture des fenêtres, plus
le clavier, la pagination, les fichiers volumineux, le stockage plein, un nom d'hôte personnalisé et la
compatibilité avec un ancien serveur. Ils sont ignorés si Playwright n'est pas installé :

```bash
pip install playwright && playwright install chromium firefox webkit
python -m unittest tests.test_interface -v     # RECETTES_NAVIGATEUR=firefox ou webkit (Safari) ; défaut : chromium
                                               # RECETTES_CHROMIUM=/chemin/chromium pour un Chromium existant
```

Ces tests et une vérification `pyflakes` tournent automatiquement sur GitHub Actions
(`.github/workflows/ci.yml`, Python 3.9 et 3.13) à chaque push sur `main` et à chaque pull request.

## Ajouter un site

- **Import par URL** : ajouter son domaine à `SITES` dans `serveur_recettes.py`. Fonctionne
  si le site publie un bloc JSON-LD `Recipe` (cas de la plupart des grands sites).
- **Recherche** : écrire une fonction `chercher(q, n)` qui renvoie `[{"url", "titre"}]`,
  l'ajouter au dictionnaire `SOURCES`, puis lancer `tester_sources.py`.

Le serveur respecte le `robots.txt` de chaque site : une page interdite aux robots est
refusée avec un message explicite au lieu d'être téléchargée. Il s'identifie honnêtement
(`User-Agent : Mozilla/5.0 (compatible; RecettesPerso/1.0; +…)`) et applique les règles visant
`RecettesPerso`, sinon celles de `*`. Le `robots.txt` est relu toutes les heures ; s'il est
injoignable ou en erreur 5xx, l'accès est refusé par prudence (RFC 9309) et réessayé à la requête
suivante. Si un site refuse cet identifiant, `RECETTES_USER_AGENT="Mozilla/5.0 …"` le remplace.

## Versions et releases

Le projet suit le [versionnage sémantique](https://semver.org/lang/fr/) (`MAJEUR.MINEUR.CORRECTIF`).
La version courante s'affiche dans l'en-tête de la page, dans l'infobulle de l'état du serveur,
au lancement du serveur et avec `python serveur_recettes.py --version`. Les changements de chaque
version sont dans [CHANGELOG.md](CHANGELOG.md) ; les releases sont sur la page *Releases* du dépôt.

**Publier une version** (par exemple 1.1.0) :

1. Dans une pull request : changer `VERSION` dans `serveur_recettes.py` **et** dans
   `generateur-recettes.html` (deux endroits : `const VERSION` et le `<small class="version">`),
   puis ajouter dans `CHANGELOG.md` la section `## [1.1.0] - AAAA-MM-JJ` (en renommant le contenu
   de `[Non publié]`) et le lien en bas de fichier. Les tests (`tests/test_version.py`) vérifient
   que tout est cohérent.
2. Une fois la PR fusionnée, créer le tag sur `main` :

   ```bash
   git checkout main && git pull
   git tag -a v1.1.0 -m "Version 1.1.0"
   git push origin v1.1.0
   ```

3. GitHub Actions (`.github/workflows/release.yml`) vérifie que le tag correspond à `VERSION`,
   lance les tests puis crée la release avec les notes de `CHANGELOG.md`.
   Si la release existe déjà (créée à la main via *Draft a new release* sur le site, qui crée aussi
   le tag), le workflow la laisse telle quelle et ne signale pas d'erreur.

`/api/ping` annonce aussi `api`, le numéro de protocole entre la page et le serveur (distinct de la
version de l'application) : la page en ligne s'en sert pour rester compatible avec un serveur plus ancien.

## Usage responsable

Projet à usage **personnel**. Les recettes extraites restent la propriété de leurs sites
d'origine : `recettes.json` et les exports sont exclus du dépôt (`.gitignore`)
et ne doivent pas être redistribués. Respecter les conditions d'utilisation de chaque
site et garder un volume de requêtes modeste.

## Licence

MIT — voir [LICENSE](LICENSE). La licence couvre le code, pas le contenu des recettes.
