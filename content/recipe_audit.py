#!/usr/bin/env python3
"""Read-only vault audit: tag rules, dietary contradictions, grid validity, boilerplate notes.
Run from the vault root: python3 recipe_audit.py. Some checks (time format, no-source) are advisory."""
import re, csv, sys, yaml
from pathlib import Path
sys.path.insert(0, ".")
import recipe_import as ri, recipe_grid as rg

ROOT = Path("Recipes")
rows = list(csv.DictReader(open("recipe_vault_taxonomy.csv", encoding="utf-8")))
tagdim = {r["value"]: r["dimension"] for r in rows if r["type"] == "tag"}
SUBREGION = {"cantonese":"chinese","sichuan":"chinese","sicilian":"italian","roman":"italian","northern-thai":"thai",
             "southern-us":"american","louisiana":"american","cajun-creole":"american","tex-mex":"american",
             "provencal":"french","birria":"mexican","oaxacan":"mexican"}
FOLDER_CUISINE = {"American":"american","Armenian":"armenian","Chinese":"chinese","Thai":"thai","Indian":"indian",
  "Peruvian":"peruvian","Turkish":"turkish","British":"british","Cuban":"cuban","French":"french","Italian":"italian",
  "Japanese":"japanese","Korean":"korean","Lebanese":"lebanese","Levantine":"levantine","Mexican":"mexican",
  "Palestinian":"palestinian","Spanish":"spanish","Greek":"greek","Filipino":"filipino"}
FIELDS = ["tags","prep_time","cook_time","total_time","yield","difficulty"]
BOILER = re.compile(r"1 to 2 days ahead|up to [23] months|example\.com|Improves as it sits|3 to 4 days", re.I)

class Dup(Exception): pass
class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(k) for k, _ in node.value]
        if len(keys) != len(set(keys)):
            raise Dup(f"duplicate keys {sorted(k for k in keys if keys.count(k) > 1)}")
        return super().construct_mapping(node, deep)

def mins(s):
    if not s: return None
    h = re.search(r"(\d+(?:\.\d+)?)\s*hour", s); m = re.search(r"(\d+)\s*min", s)
    if not h and not m: return None
    return (float(h.group(1))*60 if h else 0) + (int(m.group(1)) if m else 0)

out = {}
for p in sorted(ROOT.rglob("*.md")):
    if "private" in p.parts: continue
    rel = str(p.relative_to(ROOT)); issues = []
    md = p.read_text(encoding="utf-8")
    fm_txt, body = ri.split_frontmatter(md)
    if fm_txt is None:
        out[rel] = ["NO FRONTMATTER"]; continue
    try: fm = yaml.safe_load(fm_txt) or {}
    except Exception as e: out[rel] = [f"frontmatter yaml error: {e}"]; continue
    keys = list(fm.keys())
    order = [k for k in FIELDS if k in keys]
    if [k for k in keys if k in FIELDS] != order: issues.append(f"field order {keys}")
    extra = [k for k in keys if k not in FIELDS]
    if extra: issues.append(f"unknown fields {extra}")
    tags = fm.get("tags") or []
    if not isinstance(tags, list): issues.append(f"tags not a list: {tags!r}"); tags = []
    if len(tags) != len(set(tags)): issues.append("duplicate tags")
    unknown = [t for t in tags if t not in tagdim]
    if unknown: issues.append(f"unknown tags {unknown}")
    cat = p.relative_to(ROOT).parts[0]
    folder_parts = p.relative_to(ROOT).parts[1:-1]
    fc = [FOLDER_CUISINE[x] for x in folder_parts if x in FOLDER_CUISINE]
    for c in fc:
        if c not in tags: issues.append(f"folder cuisine {c} missing from tags")
    cuisines = [t for t in tags if tagdim.get(t) == "cuisine" and t != "fusion"]
    subs = [t for t in tags if tagdim.get(t) == "sub-region"]
    if not cuisines and not subs: issues.append("no cuisine tag")
    for s in subs:
        if SUBREGION[s] not in tags: issues.append(f"sub-region {s} without {SUBREGION[s]}")
    for c in cuisines:
        for r in ri.REGION_MAP.get(c, []):
            if r not in tags: issues.append(f"missing region {r} for {c}")
    regions = [t for t in tags if tagdim.get(t) == "region"]
    for r in regions:
        if not any(r in ri.REGION_MAP.get(c, []) for c in cuisines): issues.append(f"region {r} has no cuisine")
    if "main" in tags and cat == "Mains": issues.append("main tag inside Mains")
    if "side" in tags and cat == "Sides": issues.append("side tag inside Sides")
    if "dessert" in tags and cat == "Desserts": issues.append("dessert tag inside Desserts")
    if "appetizer" in tags and cat == "Appetizers": issues.append("appetizer tag inside Appetizers")
    if "snack" in tags and cat == "Snacks": issues.append("snack tag inside Snacks")
    for t in tags:
        d = tagdim.get(t)
        if d == "drink_placement" and cat != "Drinks": issues.append(f"drink tag {t} outside Drinks")
        if d in ("staples_use","staples_type") and cat != "Staples": issues.append(f"staples tag {t} outside Staples")
    if cat == "Drinks":
        if "cocktail" in tags and "Non-Alcoholic" in folder_parts: issues.append("cocktail tag in Non-Alcoholic")
        if not any(tagdim.get(t)=="drink_placement" for t in tags): issues.append("drink without placement tag")
    if cat == "Staples" and not any(tagdim.get(t) in ("staples_use","staples_type") for t in tags): issues.append("staple without staples_use/type tag")
    mast = [t for t in tags if tagdim.get(t) == "mastery"]
    if not mast: issues.append("no mastery tag")
    if len(mast) > 1: issues.append(f"multiple mastery tags {mast}")
    ing = body
    im = re.search(r"## Ingredients(.*?)(\n## |\Z)", body, re.S)
    if im: ing = im.group(1)
    else: issues.append("no ## Ingredients section")
    if not re.search(r"## Instructions", body): issues.append("no ## Instructions section")
    for tag, rx, why in [("vegan", ri.ANIMAL_RE, "animal"), ("vegetarian", ri.MEAT_RE, "meat"),
                         ("gluten-free", ri.GLUTEN_RE, "gluten"), ("non-alcoholic", ri.BOOZE_RE, "booze")]:
        if tag in tags and rx.search(ing): issues.append(f"{tag} but ingredients mention {rx.search(ing).group(0)!r}")
    if "vegan" in tags and "vegetarian" not in tags: issues.append("vegan without vegetarian")
    for t in ("gf-adaptable","vegan-adaptable"):
        if t in tags and not re.search(r"gluten|vegan|plant|dairy-free|substitut|swap|instead", body, re.I): issues.append(f"{t} with no substitution text")
    if "make-ahead" in tags and not re.search(r"ahead|advance|store|keeps|refrigerat|fridge|overnight", body, re.I): issues.append("make-ahead with no storage text")
    if "freezer-friendly" in tags and not re.search(r"freez", body, re.I): issues.append("freezer-friendly with no freezer text")
    if "spicy" not in tags and re.search(r"\b(chili crunch|bird'?s eye|habanero|serrano|gochujang|doubanjiang|sriracha)\b", ing, re.I): issues.append("possibly spicy (no spicy tag)")
    if "—" in md: issues.append("em dash")
    if BOILER.search(body): issues.append(f"boilerplate note: {BOILER.search(body).group(0)!r}")
    if re.search(r"^# ", body, re.M): issues.append("body H1")
    if not re.search(r"\*\*Source:\*\*", body) and "homebrew" not in tags and "homebrews" not in tags: issues.append("no Source line and not homebrew")
    pt, ct, tt = mins(str(fm.get("prep_time",""))), mins(str(fm.get("cook_time",""))), mins(str(fm.get("total_time","")))
    if pt is not None and ct is not None and tt is not None and tt + 0.5 < pt + ct: issues.append(f"total {tt} < prep {pt} + cook {ct}")
    for k in ("prep_time","cook_time","total_time"):
        v = fm.get(k)
        if v is not None and not re.match(r"^(about )?\d+(\.\d+)?( to \d+(\.\d+)?)? ?(mins?|minutes|hours?)( \d+ mins?)?$", str(v)): issues.append(f"{k} format {v!r}")
    if "difficulty" in fm and fm["difficulty"] not in ("easy","medium","hard"): issues.append(f"difficulty {fm['difficulty']!r}")
    # grid
    m = rg.FENCE_RE.search(md)
    if m: issues.append("unconverted ```recipe-grid fence")
    m = rg.STORED_RE.search(md); leg = rg.LEGACY_RE.search(md)
    if leg: issues.append("legacy <!-- grid spec")
    if not m and not leg: issues.append("no grid")
    else:
        spec_txt = (m or leg).group(1)
        try:
            yaml.load(spec_txt, Loader=StrictLoader)
            spec = yaml.safe_load(spec_txt)
            html = rg.spec_to_html(spec)
            tm = re.search(r'<table class="recipe-grid">.*?</table>', md, re.S)
            if not tm: issues.append("spec but no table")
            elif tm.group(0).strip() != html.strip(): issues.append("table stale vs spec")
        except Dup as e: issues.append(f"GRID {e}")
        except Exception as e: issues.append(f"grid spec error: {type(e).__name__}: {e}")
    if issues: out[rel] = issues

for rel, iss in out.items():
    print(f"\n{rel}")
    for i in iss: print(f"   - {i}")
print(f"\n{len(out)} files with issues of {sum(1 for _ in ROOT.rglob('*.md'))}")
