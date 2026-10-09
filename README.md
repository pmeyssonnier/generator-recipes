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
| Sauvegarde | Automatique dans `recettes_marmiton.json` + stockage du navigateur |
| Filtres | Texte libre, ingrédients avec / sans, temps max, note minimale, catégorie, favoris |
| 🎲 Surprends-moi | 3 recettes tirées au hasard parmi les résultats filtrés |
| Fiche recette | Ingrédients à cocher, étapes, lien vers la source |
| 🛒 Courses | Liste agrégée des ingrédients, copiable |
| 💾 Export | JSON de toute la base, de la sélection ou des favoris |

## Démarrage

```bash
python serveur_recettes.py
```

Le navigateur s'ouvre sur <http://localhost:8765>.

| Option | Effet |
|---|---|
| `--lan` | Accès depuis un autre appareil du même Wi-Fi (l'adresse s'affiche au lancement) |
| `--no-browser` | N'ouvre pas le navigateur |
| `RECETTES_PORT=8766` | Change le port |

Sans serveur, `generateur-recettes.html` s'ouvre aussi en double-clic pour consulter
une base chargée via **📂 Charger JSON** (l'import en ligne demande le serveur).

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

`colab/import_recettes_colab.py` fait la même extraction en lot dans un notebook
et produit un `recettes_marmiton.json` à charger dans l'interface.

## Architecture

```
navigateur (generateur-recettes.html)
   │  /api/search?q=…   /api/recipe?url=…   /api/base   /api/ping
   ▼
serveur_recettes.py  (127.0.0.1:8765)
   │  urllib → site source, 1,5 s minimum entre deux requêtes
   └─ fusionne chaque recette dans recettes_marmiton.json
```

Le serveur est nécessaire parce que les sites de recettes n'autorisent pas les appels
cross-origin (CORS) depuis une page web.

## Ajouter un site

Ajouter son domaine à `SITES` dans `serveur_recettes.py`. L'import par URL fonctionne
si le site publie un bloc JSON-LD `Recipe` (cas de la plupart des grands sites).

## Usage responsable

Projet à usage **personnel**. Les recettes extraites restent la propriété de leurs sites
d'origine : `recettes_marmiton.json` et les exports sont exclus du dépôt (`.gitignore`)
et ne doivent pas être redistribués. Respecter les conditions d'utilisation de chaque
site et garder un volume de requêtes modeste.

## Licence

MIT — voir [LICENSE](LICENSE). La licence couvre le code, pas le contenu des recettes.
