# Journal des changements

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet suit le
[versionnage sémantique](https://semver.org/lang/fr/) : **MAJEUR** pour une rupture de compatibilité
(format de `recettes.json`, API du serveur), **MINEUR** pour une nouveauté compatible, **CORRECTIF**
pour une correction. La version est définie dans `serveur_recettes.py` (`VERSION`) et rappelée dans
`generateur-recettes.html`. Voir « Publier une version » dans le README.

## [Non publié]

### Ajouté
- Filtres regroupés en **accordéons** (Ingrédients, Temps et note, Source et catégorie, Tri et favoris) : ouverts sur grand écran, **repliés au démarrage sur téléphone** pour laisser la place aux recettes ; dépliables au clic et au clavier.

## [1.5.2] - 2026-10-15

### Corrigé
- JSON importé, base du navigateur ou du serveur : chaque recette est **validée et normalisée** avant de toucher à l'état de la page
  (nom en texte obligatoire, listes d'ingrédients/étapes en tableaux de textes bornés, nombres lus, champs internes `_…` écartés). Les entrées
  inutilisables sont ignorées et signalées (« N entrée(s) ignorée(s) ») au lieu de faire planter la page ; un stockage navigateur corrompu
  ne la bloque plus.
- Statut du serveur : contraste du texte vert relevé (4,4 → 5,7 : seuil WCAG AA 4,5).

### Modifié
- Accessibilité : « 📂 Charger JSON » est un vrai bouton (atteignable au clavier) ; les étiquettes de filtre « avec / sans » sont des boutons
  (Entrée pour les retirer, le focus revient au champ) ; les messages (toasts, état du serveur, journal d'import) sont annoncés par les lecteurs
  d'écran (`role="status"` / `role="log"`) ; les champs de la fenêtre d'import ont un nom accessible.

## [1.5.1] - 2026-10-15

### Ajouté
- `python serveur_recettes.py --maj [vX.Y.Z|main]` : met à jour le serveur, la page et le module PDF depuis la dernière release GitHub
  (tout ou rien, `recettes.json` jamais touché). Les lanceurs `lancer-recettes.bat` (Windows) et `lancer-recettes.sh` / `.command` l'appellent
  à chaque lancement quand le dossier n'est pas un clone git (archive `.zip`) ; avec git, ils font `git pull` comme avant.

### Corrigé
- Mise à jour (`--maj`, `Recettes-maj` sous Termux) : plus de **retour en arrière** automatique. Si la version installée est plus récente que la
  dernière release publiée (par exemple installée depuis `main`), rien n'est remplacé ; une version demandée à la main reste possible.
- Mise à jour réellement « tout ou rien » : les fichiers téléchargés sont vérifiés (Python valide, numéro de version cohérent, page HTML) avant
  tout remplacement, puis remplacés avec sauvegarde ; en cas de panne au milieu, les fichiers d'origine sont restaurés.
- Favoris et courses d'une fiche de PDF : suivent la page du PDF (comme le ré-import) et non plus le titre ; ceux enregistrés sous l'ancienne
  clé sont repris automatiquement. Une seule règle d'identité dans la page.
- `tester_sources.py` ne plante plus sur la source eFarmz (dossier local) : elle est ignorée.
- Identifiant de PDF mal formé : HTTP 400 ; PDF ou page absents : HTTP 404 (au lieu de 500).
- `outils/construire_archive.py` ferme ses fichiers.

## [1.5.0] - 2026-10-13

### Ajouté
- Filtre **Source** (Marmiton, PtitChef, eFarmz, 750g…) à côté du filtre Catégorie.

### Modifié
- Filtre **Catégorie** : les variantes sont regroupées (« Entrée » = « Entrées », « Dessert » = « Desserts » = « Desert », « Plat » = « Plats principaux »…),
  une recette qui a plusieurs catégories apparaît dans chacune.
- « eFarmz » n'est plus une catégorie (c'est une source) : les recettes eFarmz, déjà importées ou nouvelles, sont classées
  (entrée, plat principal, dessert, accompagnement, sauce, boisson, apéritif) d'après leur titre et leurs ingrédients, comme les autres.

## [1.4.0] - 2026-10-13

### Ajouté
- **`recettes-vX.Y.Z.exe`** (Windows) joint à chaque release : un seul fichier, sans Python à installer (PyInstaller ; Python, `pdfplumber`
  et la page embarqués). La base `recettes.json` et le dossier `eFarmz/` sont créés à côté du `.exe`. Construit et essayé en CI sous Windows
  (`outils/construire_exe.py`, `outils/essai_exe.py`).

### Corrigé
- Le serveur ne plante plus à l'affichage d'un caractère que la console ne sait pas écrire (console Windows, sortie redirigée).

## [1.3.1] - 2026-10-13

### Modifié
- Windows : `lancer-recettes.bat` installe Python au premier lancement s'il est absent (via `winget`, après confirmation) puis
  l'extraction de PDF (`pdfplumber`, une seule fois, repère `.dependances-ok`) ; les lancements suivants démarrent directement l'appli.
  Sans `winget`, il affiche comme avant le lien de téléchargement de Python. Mode d'emploi de l'archive mis à jour.

## [1.3.0] - 2026-10-13

### Ajouté
- Archive **`recettes-vX.Y.Z.zip`** jointe à chaque release pour distribuer l'appli sur PC (Windows, macOS, Linux) : serveur, page,
  extraction de PDF, lanceurs (`.bat`, `.command`, `.sh`) et `LISEZMOI.txt`. Script `outils/construire_archive.py`, étape ajoutée à `release.yml`.

### Corrigé
- Nombres mixtes en exposant (« 1 1/2 », « 2 1/4 ») : l'espace entre l'entier et la fraction est conservé (« 1 1/2 » et non « 11/2 » à la copie). Les fractions seules (« 1/2 gousse ») restent telles quelles.

## [1.2.1] - 2026-10-10

### Corrigé
- Source eFarmz (PDF) : une quantité comme « 1 » suivi de « 1/2 » en petit, lue « 11/2 », devient « 1 1/2 ».

### Modifié
- Les nombres mixtes (« 1 1/2 ») s'affichent avec la fraction en petit, en exposant, dans la fiche et dans les résultats d'import.

## [1.2.0] - 2026-10-10

### Ajouté
- Bouton **🗑 Supprimer** dans la fiche d'une recette : après confirmation, la recette est retirée de `recettes.json` (nouvelle
  route `POST /api/supprimer`, avec l'en-tête `X-Recettes`) puis du navigateur, favoris et courses compris. Sans serveur, ou avec un
  serveur ancien, elle n'est retirée que du navigateur et l'appli le signale. Une base illisible n'est jamais modifiée.

### Corrigé
- Réimporter une page de PDF (eFarmz) remplace la recette déjà importée de cette page, même si son titre a changé
  (une ancienne version erronée n'est plus dupliquée à côté de la correcte), dans la base du serveur comme dans l'interface.
  Les recettes sans URL qui ne viennent pas d'un PDF restent distinguées par leur nom. La détection « déjà en base » des
  recettes de PDF se fait par page de PDF.

### Modifié
- Termux : `Recettes-maj` télécharge par défaut la **dernière release publiée** (et non une version écrite en dur), et met à jour
  les scripts `Recettes` et `Recettes-maj` installés dans `~/.shortcuts`. `RECETTES_VERSION` reste possible pour imposer une version.

## [1.1.1] - 2026-10-10

### Corrigé
- Source eFarmz (PDF) : certains PDF (planche découpée en deux, `CropBox` plus petite que la page) gardent hors de la
  zone visible un double du contenu : la photo choisie s'affichait noire, les étapes et le titre étaient doublés.
  Seule la zone visible est lue, et une photo vide est écartée.
- Un ingrédient sans quantité n'affiche plus son unité (« Sucre (càc) » → « Sucre »), et le texte qui suit le tableau
  (code QR…) n'est plus ajouté au dernier ingrédient.

## [1.1.0] - 2026-10-10

### Ajouté
- Source **eFarmz (PDF)** dans la fenêtre d'import : lit les PDF de fiches recettes déposés dans le dossier `eFarmz/`
  (quantités pour N personnes, durées, ingrédients, étapes, photo), montre l'extraction étape par étape avec
  miniatures et alertes, puis importe la sélection avec sa photo. Module `pdf_recettes.py`
  (utilisable seul : `python pdf_recettes.py fichier.pdf`) ; dépendance facultative : `pdfplumber`.
- Scripts Termux (`termux/`) : `Recettes` (lancement), `Recettes-maj` (mise à jour du serveur et de la page,
  sans toucher à la base) et un installateur pour le widget Termux:Widget et les commandes `recettes` / `recettes-maj`.
- L'interface accepte les images intégrées (`data:image/jpeg|png|webp|gif;base64`), par exemple la photo extraite
  d'un PDF de recettes ; tout autre `data:` (SVG, HTML…) reste refusé.

### Modifié
- Le workflow de release laisse telle quelle une release déjà créée à la main au lieu d'échouer.

## [1.0.0] - 2026-10-10

Première version publiée.

### Fonctionnalités
- Carnet de recettes dans un navigateur : filtres (texte, ingrédients avec / sans, temps, note,
  catégorie, favoris), tri, 🎲 « Surprends-moi », fiche recette, liste de courses, export JSON.
- Import depuis Marmiton et PtitChef (recherche), et par URL depuis les sites de la liste `SITES`
  (recette, ou page de sélection : chronique, page thématique…).
- Serveur Python local sans dépendance (`serveur_recettes.py`), lanceur Windows
  (`lancer-recettes.bat`), page en ligne sur GitHub Pages utilisant le serveur local pour l'import.
- Script Google Colab pour l'import en lot, qui réutilise le code du serveur.
- Affichage par pages de 48 recettes (« Afficher plus »).
- `--version` et numéro de version affichés (page, serveur, `/api/ping`).

### Sécurité
- Le serveur ne sert que la page HTML (ni `.git/`, ni code source, ni base JSON).
- Origines autorisées restreintes, en-tête `Host` vérifié (protection contre le DNS rebinding),
  `RECETTES_HOTES` pour un nom d'hôte personnalisé.
- Redirections suivies à la main et revalidées (site autorisé, pas de retour en `http`, `robots.txt`).
- Import d'une recette en `POST` avec l'en-tête `X-Recettes` ; les `GET` ne modifient jamais rien.
- Le serveur s'identifie (`RecettesPerso`) et respecte le `robots.txt` : relu toutes les heures,
  accès refusé si injoignable ou en erreur 5xx.
- Pages téléchargées limitées à 5 Mo (bombe gzip comprise), cache borné.
- `/api/ping` ne révèle que le nom du fichier de la base ; erreurs internes génériques côté client.
- Interface : politique CSP, seules les URL `http(s)` acceptées pour les liens et images importés,
  images sans transmission du référent.
- Fichiers JSON importés limités à 25 Mo ; alerte si le stockage du navigateur est plein.

### Fiabilité
- Un `recettes.json` corrompu n'est jamais écrasé : il est conservé sous
  `recettes.json.corrompu-AAAAMMJJ-HHMMSS`.
- La base s'appelle `recettes.json` ; l'ancien `recettes_marmiton.json` est renommé automatiquement.
- Mode réseau local avec nom d'hôte personnalisé : l'interface appelle bien le serveur qui la sert.
- La page en ligne reste compatible avec un serveur local plus ancien (« serveur ancien »).
- Corrections : durées `PT0S` / `PT45S` (ne donnent plus « 0 minute »), favoris et courses
  distincts pour les recettes sans URL, chargement de plusieurs fichiers JSON d'un coup,
  paramètre `n` invalide (400 au lieu de 500).

### Performance
- Import 26 fois plus rapide (636 → 24 ms par recette avec 1 500 recettes en base).
- Chargement et re-rendu avec plusieurs milliers de recettes : 2,3 s → 0,2 s et ~1 s → ~23 ms.

### Accessibilité
- Cartes utilisables au clavier, boutons nommés (`aria-label`, `aria-pressed`), focus conservé
  après un re-rendu et rendu à la carte à la fermeture de la fiche.

### Qualité
- Plus de 90 tests : parseurs, serveur, script Colab (hors ligne) et 22 tests de l'interface dans un vrai
  Chromium (Playwright) qui cliquent sur chaque bouton principal.
- Intégration continue (GitHub Actions) : `pyflakes`, tests sur Python 3.9 et 3.13, tests de
  l'interface ; création automatique d'une release à chaque tag `vX.Y.Z`.

### Retiré
- Recherche Ricardo (plan du site en erreur 504) : Ricardo reste utilisable par URL.
- Outils de lecture des plans de site et d'extraction de mots-clés, devenus inutiles.

[Non publié]: https://github.com/pmeyssonnier/generator-recipes/compare/v1.5.2...HEAD
[1.5.2]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.5.2
[1.5.1]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.5.1
[1.5.0]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.5.0
[1.4.0]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.4.0
[1.3.1]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.3.1
[1.3.0]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.3.0
[1.2.1]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.2.1
[1.2.0]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.2.0
[1.1.1]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.1.1
[1.1.0]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.1.0
[1.0.0]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.0.0
