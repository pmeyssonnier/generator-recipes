#!/usr/bin/env bash
# macOS : double-clic dans le Finder (ouvre le Terminal). Même chose que lancer-recettes.sh.
exec "$(dirname "$0")/lancer-recettes.sh" "$@"
