# Journal des changements

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet suit le
[versionnage sémantique](https://semver.org/lang/fr/) : **MAJEUR** pour une rupture de compatibilité
(format de `recettes.json`, API du serveur), **MINEUR** pour une nouveauté compatible, **CORRECTIF**
pour une correction. La version est définie dans `serveur_recettes.py` (`VERSION`) et rappelée dans
`generateur-recettes.html`. Voir « Publier une version » dans le README.

## [Non publié]

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

[Non publié]: https://github.com/pmeyssonnier/generator-recipes/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/pmeyssonnier/generator-recipes/releases/tag/v1.0.0
