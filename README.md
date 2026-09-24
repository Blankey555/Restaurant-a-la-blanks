# Blanks' Restaurant

Source for **[blankey555.github.io/Restaurant-a-la-blanks](https://blankey555.github.io/Restaurant-a-la-blanks/)**, a public recipe site built with [Quartz v5](https://quartz.jzhao.xyz/).

## How it fits together

```
Obsidian vault  ──sync-content.sh──▶  content/  ──git push──▶  GitHub Actions  ──▶  GitHub Pages
(source of truth)                     (copy)                   (npx quartz build)
```

- **The recipes are written in the Obsidian vault** at `~/Documents/Blanks' Restaurant`, which is also its own private repo ([Blankey555/blanks-restaurant](https://github.com/Blankey555/blanks-restaurant)).
- **`content/` is a copy** of that vault, made by `sync-content.sh`. Don't edit files in `content/` directly: the next sync overwrites them.
- **Every push to `main` deploys the site** via [.github/workflows/deploy.yaml](.github/workflows/deploy.yaml). After deploying, the workflow also regenerates redirect stubs in [Blankey555/blankey555.github.io](https://github.com/Blankey555/blankey555.github.io), so root-domain URLs forward to this site. That step uses the `ROOT_SITE_DEPLOY_KEY` secret.

## Publishing changes

```bash
./sync-content.sh            # copy the vault into content/ and show what changed
./sync-content.sh --publish  # same, then commit and push (deploys the site)
```

`sync-content.sh` never copies these vault folders:

| Excluded | Why |
|---|---|
| `Recipes/private/` | Personal recipes and shopping lists. Quartz's `ignorePatterns` also skips `private` as a second guard. |
| `Agony & Annihilation/` | A separate writing project, not part of the site |
| `.obsidian/`, `.claude/`, `.git/`, `__pycache__/` | Tooling |
| `README.md` (vault root) | The vault repo's own README |

## Layout

| Path | What it is |
|---|---|
| `content/` | Site pages (synced from the vault). `content/index.md` is the home page. |
| `content/Recipes/<Course>/<Cuisine>/` | One markdown file per recipe |
| `content/*.py`, `recipe_vault_taxonomy.csv` | The vault's recipe tooling, published along with it. See the vault README. |
| `quartz.config.yaml` | Site title, base URL, theme, plugins, ignore patterns |
| `quartz/` | Quartz framework source (upstream: [jackyzha0/quartz](https://github.com/jackyzha0/quartz)) |

## Local preview

```bash
npm ci
npx quartz build --serve   # http://localhost:8080
```
