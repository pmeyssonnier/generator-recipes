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
| Import | Recherche par mot-clé sur Marmiton, ou import par URL depuis les sites de la liste `SITES` |
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

## Tests

```bash
python -m unittest discover -s tests     # hors ligne : parseurs JSON-LD, listes de recettes, sources,
                                          # durées, Host, fichiers servis, redirections, base JSON
```

Les **tests de l'interface** (`tests/test_interface.py`, 22 tests) pilotent un vrai Chromium contre le vrai
serveur (seules l'extraction d'une recette et la recherche sont simulées) et cliquent sur chaque bouton :
Importer (recherche, URL, page de sélection), Exporter (téléchargements), Courses (copie dans le
presse-papiers), favoris, fiche recette, filtres, tri, Surprends-moi, Vider, fermeture des fenêtres, plus
le clavier, la pagination, les fichiers volumineux, le stockage plein, un nom d'hôte personnalisé et la
compatibilité avec un ancien serveur. Ils sont ignorés si Playwright n'est pas installé :

```bash
pip install playwright && playwright install chromium
python -m unittest tests.test_interface -v     # RECETTES_CHROMIUM=/chemin/chromium pour un Chromium existant
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

## Usage responsable

Projet à usage **personnel**. Les recettes extraites restent la propriété de leurs sites
d'origine : `recettes.json` et les exports sont exclus du dépôt (`.gitignore`)
et ne doivent pas être redistribués. Respecter les conditions d'utilisation de chaque
site et garder un volume de requêtes modeste.

## Licence

MIT — voir [LICENSE](LICENSE). La licence couvre le code, pas le contenu des recettes.
