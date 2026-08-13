#!/Users/alexblankenberg/.venvs/recipe-import/bin/python
"""
recipe_import.py: import recipes into the Obsidian vault via local Ollama.

Input:  --input <URL | file path | -> (stdin), or --batch <file of URLs>
Output: taxonomy-conformant markdown filed into the vault per
        recipe_vault_taxonomy.csv (read at runtime; edit the CSV, not this script).

Default is preview mode: shows generated markdown + destination, asks before
writing. --yes skips confirmation.
"""

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests
import yaml

VAULT = Path("/Users/alexblankenberg/Documents/Blanks' Restaurant")
RECIPES = VAULT / "Recipes"
TAXONOMY_CSV = VAULT / "recipe_vault_taxonomy.csv"
OLLAMA_URL = "http://localhost:11434"
MODEL = "gpt-oss:20b"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

REQUIRED_FIELDS = ["tags", "difficulty"]  # always required
ORDERED_FIELDS = ["tags", "prep_time", "cook_time", "total_time", "yield", "difficulty"]
FORBIDDEN_TAGS = {"untested", "tested", "refined", "mastered", "homebrews", "homebrew"}

CATEGORY_FOLDERS = ["Appetizers", "Mains", "Sides", "Desserts", "Snacks",
                    "Drinks/Cocktails", "Drinks/Non-Alcoholic", "Staples"]

FEW_SHOT = '''---
tags: [mexican, latin-american, dip, sauce, broiled, vegan, gluten-free, party, make-ahead]
prep_time: 10 mins
cook_time: 10 mins
total_time: 20 mins
yield: 8 servings
difficulty: easy
---

# Charred Tomatillo Dip

**Source:** https://example.com/tomatillo-dip

## Ingredients

- 450 g tomatillos, husked and rinsed
- 4 garlic cloves, unpeeled
- 1 jalapeño or serrano pepper
- 1 lime, juiced
- 1 tsp salt

## Instructions

1. Char the tomatillos, garlic, and pepper under a broiler until blackened in spots, about 8 to 10 minutes.
2. Peel the garlic, stem the pepper, and blend everything with lime juice and salt to preferred texture.
3. Taste, adjust, and refrigerate until serving.

## Notes

- Improves as it sits. Can be made 1 to 2 days ahead.
- Keeps in the fridge for 3 to 4 days.
'''


# ---------------------------------------------------------------- taxonomy

def load_taxonomy():
    if not TAXONOMY_CSV.exists():
        sys.exit(f"Taxonomy CSV not found at {TAXONOMY_CSV}")
    rows = list(csv.DictReader(TAXONOMY_CSV.open(encoding="utf-8")))
    tags = [r for r in rows if r["type"] == "tag"]
    valid_tags = {r["value"] for r in tags
                  if r["dimension"] not in ("meta",)}
    allowed_tags = valid_tags - FORBIDDEN_TAGS
    return rows, tags, allowed_tags


def build_system_prompt(rows, tags):
    dims = {}
    for r in tags:
        dims.setdefault(r["dimension"], []).append(r)

    lines = [
        "You convert raw recipe content into a markdown recipe file for a personal vault.",
        "Follow every rule exactly. Output ONLY the markdown file content, no commentary, no code fences.",
        "",
        "## FRONTMATTER SPECIFICATION",
    ]
    for r in rows:
        if r["type"] == "frontmatter":
            lines.append(f"- {r['value']}: {r['claude_code_rules']}")
    lines += [
        "",
        "## TAG TAXONOMY (the ONLY tags you may use)",
    ]
    for dim, rs in dims.items():
        if dim in ("mastery", "provenance", "meta"):
            continue
        lines.append(f"### {dim}")
        for r in rs:
            lines.append(f"- {r['value']}: {r['description']}. {r['claude_code_rules']}")
    meta_rules = [r for r in tags if r["dimension"] == "meta"]
    lines.append("### tagging rules")
    for r in meta_rules:
        lines.append(f"- {r['claude_code_rules']}")
    lines += [
        "- Region tags derive automatically from cuisine tags (see each region row).",
        "  The mediterranean tag is an overlay that stacks with european or middle-eastern per its rule.",
        "- ABSOLUTE PROHIBITION: never apply these tags: untested, tested, refined, mastered, homebrews, homebrew.",
        "",
        "## FORMAT RULES",
    ]
    for r in rows:
        if r["type"] == "format":
            lines.append(f"- {r['claude_code_rules']}")
    lines += [
        "- Frontmatter fields appear in this exact order: tags, prep_time, cook_time, total_time, yield, difficulty.",
        "- Time values must match times stated in the recipe content, including ranges. Never invent times; omit a field the content does not state.",
        "- The H1 title is title case and follows the naming convention.",
        "- Body structure: H1, a Source line when a URL is given, then Ingredients, Instructions (numbered), Notes. Do NOT write a description or introduction line; the vault owner writes those by hand.",
        "- No em dashes (the character —) anywhere in the output.",
        "",
        "## EXAMPLE OUTPUT (format anchor)",
        "The example below shows FORMAT only. Never copy its text, notes, times, or tags",
        "into your output; every line you produce must come from the provided recipe content.",
        FEW_SHOT,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- extraction

def extract_from_url(url):
    html = requests.get(url, headers=UA, timeout=30).text
    try:
        from recipe_scrapers import scrape_html
        s = scrape_html(html, org_url=url, supported_only=False)
        parts = [f"TITLE: {s.title()}"]
        for name, fn in [("AUTHOR", "author"), ("YIELD", "yields"),
                         ("PREP_TIME_MIN", "prep_time"), ("COOK_TIME_MIN", "cook_time"),
                         ("TOTAL_TIME_MIN", "total_time"), ("CUISINE", "cuisine"),
                         ("DESCRIPTION", "description")]:
            try:
                v = getattr(s, fn)()
                if v:
                    parts.append(f"{name}: {v}")
            except Exception:
                pass
        try:
            parts.append("INGREDIENTS:\n" + "\n".join(f"- {i}" for i in s.ingredients()))
        except Exception:
            pass
        try:
            parts.append("INSTRUCTIONS:\n" + s.instructions())
        except Exception:
            pass
        text = "\n\n".join(parts)
        if len(text) > 200:  # sanity: real content extracted
            return text, "recipe-scrapers"
    except Exception as e:
        print(f"  recipe-scrapers failed ({e}); falling back to trafilatura", file=sys.stderr)
    import trafilatura
    text = trafilatura.extract(html, include_comments=False) or ""
    if len(text) < 100:
        sys.exit("Extraction failed: neither recipe-scrapers nor trafilatura got usable content.")
    return text, "trafilatura"


def get_content(inp):
    if inp == "-":
        return sys.stdin.read(), None
    if re.match(r"https?://", inp):
        text, engine = extract_from_url(inp)
        print(f"  extracted via {engine} ({len(text)} chars)")
        return text, inp
    p = Path(inp)
    if p.exists():
        return p.read_text(encoding="utf-8"), None
    sys.exit(f"Input not recognized as URL, existing file, or '-': {inp}")


# ---------------------------------------------------------------- ollama

def ollama_chat(system, user):
    import time
    print(f"  converting via {MODEL} (typically 1 to 4 minutes, longer on first call "
          "while the model loads)...", flush=True)
    t0 = time.time()
    r = _ollama_request(system, user)
    print(f"  model responded in {time.time() - t0:.0f}s", flush=True)
    return r


def _ollama_request(system, user):
    r = requests.post(f"{OLLAMA_URL}/api/chat", json={
        "model": MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 16384, "num_predict": 3000},
    }, timeout=600)
    r.raise_for_status()
    out = r.json()["message"]["content"].strip()
    out = re.sub(r"\A```(?:markdown|md|yaml)?\s*\n", "", out)
    out = re.sub(r"\n```\s*\Z", "", out)
    out = re.sub(r"\s*—\s*", ", ", out)  # auto-repair em dashes rather than failing
    return out.strip() + "\n"


# ---------------------------------------------------------------- validation

def split_frontmatter(md):
    m = re.match(r"\A---\n(.*?)\n---\n?(.*)\Z", md, re.DOTALL)
    if not m:
        return None, md
    return m.group(1), m.group(2)


def validate(md, allowed_tags, source_url):
    errors = []
    fm_text, body = split_frontmatter(md)
    fm = None
    if fm_text is None:
        errors.append("Missing YAML frontmatter block delimited by --- lines.")
    else:
        try:
            fm = yaml.safe_load(fm_text)
            if not isinstance(fm, dict):
                errors.append("Frontmatter did not parse as a YAML mapping.")
                fm = None
        except yaml.YAMLError as e:
            errors.append(f"Frontmatter is not valid YAML: {e}")
    if fm:
        for f in ("tags", "difficulty"):
            if f not in fm:
                errors.append(f"Required frontmatter field missing: {f}")
        present_times = [f for f in ("prep_time", "cook_time", "total_time", "yield") if f in fm]
        if not present_times:
            errors.append("At least one of prep_time/cook_time/total_time/yield should be present "
                          "when the source states any time or yield.")
        keys = [k for k in fm.keys() if k in ORDERED_FIELDS]
        if keys != [k for k in ORDERED_FIELDS if k in keys]:
            errors.append(f"Frontmatter fields out of order. Required order: {ORDERED_FIELDS}")
        if str(fm.get("difficulty")) not in ("easy", "medium", "hard"):
            errors.append("difficulty must be one of: easy, medium, hard")
        tags = fm.get("tags") or []
        if not isinstance(tags, list) or not tags:
            errors.append("tags must be a non-empty YAML list")
        else:
            bad = [t for t in tags if t in FORBIDDEN_TAGS]
            if bad:
                errors.append(f"Forbidden tags present (mastery/provenance): {bad}")
            unknown = [t for t in tags if t not in allowed_tags and t not in FORBIDDEN_TAGS]
            if unknown:
                errors.append(f"Tags not in taxonomy: {unknown}")
    if "—" in md:
        errors.append("Em dash present in output. Em dashes are banned everywhere.")
    if not re.search(r"^# .+$", body or md, re.MULTILINE):
        errors.append("Missing H1 title line.")
    if source_url and source_url not in md:
        errors.append(f"Missing Source line containing the URL {source_url}")
    return errors, fm


# ---------------------------------------------------------------- filing

def existing_cuisine_folder(category_dir, tags):
    """Return deepest existing cuisine/dish folder matching the tags, else category root."""
    if not category_dir.exists():
        return category_dir
    subs = {d.name.lower(): d for d in category_dir.iterdir() if d.is_dir()}
    # fusion nesting: check one level down too (e.g. American/British)
    for t in tags:
        if t in subs:
            deeper = {d.name.lower(): d for d in subs[t].iterdir() if d.is_dir()}
            for t2 in tags:
                if t2 != t and t2 in deeper:
                    return deeper[t2]
            return subs[t]
    return category_dir


def choose_destination(fm):
    tags = set(fm.get("tags") or [])
    staple_type = {"marinade", "infusion", "syrup", "brine", "stock", "bread"}
    staple_use = {"sauce", "condiment", "garnish", "ingredient"}
    drink_place = {"cocktail-hour", "aperitif", "digestif", "dessertif", "session"}
    drink_class = {"punch", "martini", "margarita", "smash", "sour", "spritz"}

    if tags & staple_type or tags & staple_use:
        cat = RECIPES / "Staples"
    elif tags & drink_place or tags & drink_class:
        cat = RECIPES / ("Drinks/Non-Alcoholic" if "non-alcoholic" in tags else "Drinks/Cocktails")
    elif "non-alcoholic" in tags:
        cat = RECIPES / "Drinks/Non-Alcoholic"
    elif "main" in tags:
        cat = RECIPES / "Mains"
    elif "dessert" in tags:
        cat = RECIPES / "Desserts"
    elif "appetizer" in tags and "soup" not in tags:
        cat = RECIPES / "Appetizers"
    elif "snack" in tags:
        cat = RECIPES / "Snacks"
    elif "side" in tags:
        cat = RECIPES / "Sides"
    else:
        cat = RECIPES / "Mains"
    return existing_cuisine_folder(cat, [t.lower() for t in (fm.get("tags") or [])])


def find_collision(filename):
    for p in RECIPES.rglob("*.md"):
        if unicodedata.normalize("NFC", p.name).lower() == unicodedata.normalize("NFC", filename).lower():
            return p
    return None


def title_from_md(md):
    m = re.search(r"^# (.+)$", md, re.MULTILINE)
    return m.group(1).strip() if m else None


BOLD_META_RE = re.compile(
    r"^\*\*(Serves|Time|Prep|Cook|Rest|Total Time|Active Time|Yield|Makes|Servings|Bake Time)\s*:",
    re.IGNORECASE)
EXAMPLE_BLEED = {
    "- Improves as it sits. Can be made 1 to 2 days ahead.",
    "- Keeps in the fridge for 3 to 4 days.",
}


def strip_duplicated_header(md):
    """Remove the body H1 (the filename carries the title) and any bold
    metadata lines duplicating frontmatter; drop notes copied verbatim
    from the few-shot example."""
    out = []
    for l in md.splitlines():
        s = l.strip()
        if s.startswith("# ") and not s.startswith("## "):
            continue
        if BOLD_META_RE.match(s) and not s.startswith("**Source:"):
            continue
        if s in EXAMPLE_BLEED:
            continue
        if re.match(r"\*[^*].*\*$", s):  # model-written blurb; owner writes these
            continue
        out.append(l)
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


# ---------------------------------------------------------------- pipeline

GRID_PROMPT = """Derive a process-grid spec for the recipe below. Output ONLY YAML, no commentary, no code fences.

Format:
setup:            # optional list of prep lines (oven preheat, pan prep); omit if none
  - <line>
steps:            # a nested tree: leaves are ingredient strings (with quantities),
  op: <final operation>          # ops describe what is done to everything beneath
  of:
    - op: <earlier operation>
      of:
        - <ingredient>
        - <ingredient>
    - <ingredient added at the later stage>

Rules:
- Every ingredient appears exactly once as a leaf, in the order used.
- Ops are short imperative phrases with key times/temps (e.g. "bake 350F 30 to 40 min").
- Ingredients grouped under the same op are combined by that op; parent ops merge their children in order.
- Maximum nesting depth 6. No em dashes anywhere.
"""


def try_generate_grid(content, md):
    import recipe_grid
    user = GRID_PROMPT + "\n--- RECIPE ---\n" + content[:8000]
    for attempt, extra in enumerate(["", None]):
        raw = ollama_chat("You convert recipes into structured process-grid YAML specs.",
                          user if extra is None or attempt == 0 else user)
        raw = re.sub(r"\A```(?:yaml)?\s*\n|\n```\s*\Z", "", raw.strip())
        try:
            spec = yaml.safe_load(raw)
            if not isinstance(spec, dict):
                raise ValueError("spec is not a mapping")
            table = recipe_grid.spec_to_html(spec)
            block = ("## At a Glance\n\n%%recipe-grid-spec\n" + raw.strip()
                     + "\n%%\n\n" + table + "\n\n")
            if "## Ingredients" in md:
                return md.replace("## Ingredients", block + "## Ingredients", 1)
            return md + "\n" + block
        except Exception as e:
            err = str(e)
            print(f"  grid attempt {attempt + 1} invalid: {err}")
            user = user + f"\n\nYour previous output failed: {err}\nOutput corrected YAML only."
    print("  grid generation failed twice; importing recipe without a grid.")
    return md


def process_one(inp, system_prompt, allowed_tags, auto_yes, want_grid=False):
    print(f"\n=== {inp} ===")
    content, source_url = get_content(inp)

    user = "Convert the following recipe content into a vault recipe file.\n"
    if source_url:
        user += f"SOURCE URL (include as a Source line): {source_url}\n"
    user += "\n--- RECIPE CONTENT ---\n" + content[:12000]

    md = ollama_chat(system_prompt, user)
    errors, fm = validate(md, allowed_tags, source_url)
    if errors:
        print("  validation failed, retrying once with errors appended:")
        for e in errors:
            print(f"    - {e}")
        retry_user = (user + "\n\n--- YOUR PREVIOUS OUTPUT FAILED VALIDATION ---\n"
                      + md + "\n--- ERRORS TO FIX ---\n"
                      + "\n".join(f"- {e}" for e in errors)
                      + "\nRegenerate the complete corrected file.")
        md = ollama_chat(system_prompt, retry_user)
        errors, fm = validate(md, allowed_tags, source_url)
        if errors:
            print("\nVALIDATION FAILED AFTER RETRY. Raw output below; nothing written.\n")
            print(md)
            print("\nErrors:")
            for e in errors:
                print(f"  - {e}")
            return False

    if want_grid:
        md = try_generate_grid(content, md)

    title = title_from_md(md) or "Untitled Recipe"
    md = strip_duplicated_header(md)
    filename = f"{title}.md"
    dest_dir = choose_destination(fm)
    dest = dest_dir / filename

    collision = find_collision(filename)
    if collision:
        print(f"\nCOLLISION: {filename} already exists at {collision}")
        print("Nothing written. Rename or remove the existing file, or adjust the new title.")
        return False

    print("\n" + "=" * 70)
    print(md)
    print("=" * 70)
    print(f"DESTINATION: {dest}")

    if not auto_yes:
        try:  # discard any Enter presses buffered while the model was working
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass
        ans = input("\nWrite this file? [y/N] ").strip().lower()
        if ans != "y":
            print("Skipped.")
            return False
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(md, encoding="utf-8")
    print(f"WROTE: {dest}")
    return True


def main():
    global MODEL
    ap = argparse.ArgumentParser(description="Import recipes into the vault via local Ollama.")
    ap.add_argument("--input", help="URL, file path, or '-' for stdin")
    ap.add_argument("--batch", help="file containing URLs, one per line")
    ap.add_argument("--yes", action="store_true", help="skip confirmation prompts")
    ap.add_argument("--grid", action="store_true",
                    help="also generate a process-grid table (At a Glance section)")
    ap.add_argument("--model", default=None, help=f"override model (default {MODEL})")
    args = ap.parse_args()

    if args.model:
        MODEL = args.model
    if not args.input and not args.batch:
        ap.error("provide --input or --batch")

    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    except requests.ConnectionError:
        sys.exit("Ollama is not running at localhost:11434. Start it with: ollama serve")

    rows, tags, allowed_tags = load_taxonomy()
    system_prompt = build_system_prompt(rows, tags)

    inputs = []
    if args.input:
        inputs.append(args.input)
    if args.batch:
        raw = Path(args.batch).read_text(encoding="utf-8", errors="replace")
        # Extract URLs by pattern so plain lists, RTF, and HTML exports all work.
        urls = re.findall(r"https?://[^\s\"'<>{}\\]+", raw)
        seen = set()
        for u in urls:
            u = u.rstrip(".,;)")
            if u not in seen:
                seen.add(u)
                inputs.append(u)
        if not inputs:
            sys.exit(f"No URLs found in {args.batch}")

    results = [process_one(i, system_prompt, allowed_tags, args.yes, args.grid) for i in inputs]
    print(f"\nDone: {sum(results)}/{len(results)} written.")


if __name__ == "__main__":
    main()
