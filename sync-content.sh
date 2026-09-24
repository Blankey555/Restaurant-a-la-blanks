#!/bin/bash
# Copy the Obsidian vault into content/ so the public site repo has real files.
# The vault is the source of truth; never edit content/ directly.
# Usage: ./sync-content.sh            (sync + show what changed)
#        ./sync-content.sh --publish  (sync, commit, and push to deploy the site)
set -euo pipefail

VAULT="$HOME/Documents/Blanks' Restaurant"
SITE="$(cd "$(dirname "$0")" && pwd)"

[ -d "$VAULT" ] || { echo "Vault not found: $VAULT" >&2; exit 1; }
[ -L "$SITE/content" ] && rm "$SITE/content"

# Anything listed here never reaches the public site.
rsync -a --delete \
  --exclude '.git/' --exclude '.gitignore' \
  --exclude '.obsidian/' --exclude '.claude/' \
  --exclude '__pycache__/' --exclude '.DS_Store' \
  --exclude 'Agony & Annihilation/' \
  --exclude 'Recipes/private/' \
  "$VAULT/" "$SITE/content/"

cd "$SITE"
git add -A content
if git diff --cached --quiet -- content; then
  echo "content/ already matches the vault."
  exit 0
fi
git diff --cached --stat -- content

if [ "${1:-}" = "--publish" ]; then
  git commit -m "Sync content from vault"
  git push
else
  echo
  echo "Staged. Review, then: git commit -m 'Sync content from vault' && git push"
fi
