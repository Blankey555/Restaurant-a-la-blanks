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
# The repo tracks real copies of the vault (CI cannot see iCloud) while the
# working tree has a symlink, so git would always report every content file as
# deleted. Hide that with assume-unchanged, lifting it only while syncing so
# that changed recipes are still picked up.
tidy() { git ls-files -z content | xargs -0 git update-index --assume-unchanged 2>/dev/null; grep -qx content .git/info/exclude 2>/dev/null || echo content >> .git/info/exclude; }
untidy() { git ls-files -z content | xargs -0 git update-index --no-assume-unchanged 2>/dev/null; }
if [ "$1" = "--tidy" ]; then tidy; echo "git status will now ignore the content symlink mismatch"; exit 0; fi
[ -n "$1" ] || { echo "usage: ./publish.sh \"commit message\"   (or ./publish.sh --tidy)"; exit 1; }
untidy
npx quartz sync --pull=false -m "$1"; rc=$?
tidy
exit $rc
