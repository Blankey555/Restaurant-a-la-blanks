#!/bin/zsh
# Publish the vault to GitHub Pages, refusing if iCloud has left the vault in a bad state.
#   ./publish.sh "commit message"
set -e
VAULT="$(readlink content)"
[ -d "$VAULT" ] || { echo "content symlink does not resolve: $VAULT"; exit 1; }
bad=$(find "$VAULT" \( -name "*.icloud" -o -name "* 2.md" -o -name "* 2" -o -iname "*conflict*" \) -not -path "*/.obsidian/*" 2>/dev/null)
if [ -n "$bad" ]; then
  echo "Refusing to publish: iCloud placeholders or conflict copies in the vault:"
  echo "$bad" | sed 's/^/  /'
  echo "Fix them (Keep Downloaded / resolve the conflict) and rerun."
  exit 1
fi
[ -n "$1" ] || { echo "usage: ./publish.sh \"commit message\""; exit 1; }
exec npx quartz sync --pull=false -m "$1"
