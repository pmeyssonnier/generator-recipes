#!/data/data/com.termux/files/usr/bin/bash
# Installe les raccourcis du générateur de recettes dans Termux :
#   ~/.shortcuts/Recettes       lance le serveur       (visible dans le widget Termux:Widget)
#   ~/.shortcuts/Recettes-maj   met à jour serveur et page
# et les commandes « recettes » et « recettes-maj » (alias dans ~/.bashrc).
# Usage : curl -fsSL https://raw.githubusercontent.com/pmeyssonnier/generator-recipes/main/termux/installer.sh | bash
set -e
REF="${RECETTES_REF:-main}"
BASE="${RECETTES_BASE_URL:-https://raw.githubusercontent.com/pmeyssonnier/generator-recipes/$REF/termux}"
DEST="${RECETTES_RACCOURCIS:-$HOME/.shortcuts}"
mkdir -p "$DEST"
trap 'rm -f "$DEST/Recettes.tmp" "$DEST/Recettes-maj.tmp"' EXIT
for f in Recettes Recettes-maj; do
  curl -fsSL "$BASE/$f" -o "$DEST/$f.tmp"        # en cas d'échec, les raccourcis existants restent intacts
  mv "$DEST/$f.tmp" "$DEST/$f"
  chmod +x "$DEST/$f"
done
ajouter_alias() {                                  # sans doublon si on relance l'installateur
  grep -qF "alias $1=" "$HOME/.bashrc" 2>/dev/null || echo "alias $1='bash $DEST/$2'" >> "$HOME/.bashrc"
}
ajouter_alias recettes Recettes
ajouter_alias recettes-maj Recettes-maj
echo "✓ Raccourcis installés dans $DEST"
echo "  • Widget  : installe Termux:Widget, puis ajoute un « Termux shortcut » sur l'écran d'accueil"
echo "  • Commandes : ferme et rouvre Termux, puis tape  recettes  ou  recettes-maj"
