#!/usr/bin/env bash
# Lance le générateur de recettes (serveur local + navigateur) sous Linux ou macOS.
# Options transmises au serveur, par exemple : ./lancer-recettes.sh --lan
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else
  echo "Python 3 introuvable. Installe-le depuis https://www.python.org/downloads/ puis relance ce fichier."
  read -r -p "Entrée pour fermer" || true
  exit 1
fi
"$PY" serveur_recettes.py "$@"
echo
read -r -p "Serveur arrêté. Entrée pour fermer" || true
