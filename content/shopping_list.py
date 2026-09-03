#!/Users/alexblankenberg/.venvs/recipe-import/bin/python
"""
shopping_list.py: build an aggregated shopping list from vault recipes.

Input:  one or more recipes by path or fuzzy filename match.
Output: a grouped markdown checklist written ONLY to
        Recipes/private/Shopping Lists/ (never published by the Quartz sync).

Default is preview mode: shows the list, asks before writing. --yes skips
confirmation. --clipboard copies the plain checklist via pbcopy.

Scaling:
  --scale "butter chicken=2"        multiply that recipe's quantities by 2
  --servings "butter chicken=9"     scale from the recipe's yield (e.g. 6 -> 9)
  --guests 8                        scale every recipe with a parseable yield
                                    to serve 8

All parsing and arithmetic is deterministic; no LLM calls.
"""

import argparse
import datetime
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

VAULT = Path("/Users/alexblankenberg/Documents/Blanks' Restaurant")
RECIPES = VAULT / "Recipes"
LISTS_DIR = RECIPES / "private" / "Shopping Lists"
MAX_DEPTH = 3

# ---------------------------------------------------------------- quantities

UNICODE_FRACTIONS = {
    "¼": Fraction(1, 4), "½": Fraction(1, 2), "¾": Fraction(3, 4),
    "⅓": Fraction(1, 3), "⅔": Fraction(2, 3),
    "⅛": Fraction(1, 8), "⅜": Fraction(3, 8),
    "⅝": Fraction(5, 8), "⅞": Fraction(7, 8),
    "⅕": Fraction(1, 5), "⅖": Fraction(2, 5),
    "⅗": Fraction(3, 5), "⅘": Fraction(4, 5), "⅙": Fraction(1, 6),
}

# alias -> (canonical, family, factor to family base unit)
# families: vol (base ml), mass (base g), count-ish units have family None
UNIT_ALIASES = {
    "teaspoon": ("tsp", "vol", Fraction(4929, 1000)),
    "teaspoons": ("tsp", "vol", Fraction(4929, 1000)),
    "tsp": ("tsp", "vol", Fraction(4929, 1000)),
    "tablespoon": ("tbsp", "vol", Fraction(14787, 1000)),
    "tablespoons": ("tbsp", "vol", Fraction(14787, 1000)),
    "tbsp": ("tbsp", "vol", Fraction(14787, 1000)),
    "cup": ("cup", "vol", Fraction(23659, 100)),
    "cups": ("cup", "vol", Fraction(23659, 100)),
    "ml": ("ml", "vol", Fraction(1)),
    "milliliter": ("ml", "vol", Fraction(1)),
    "milliliters": ("ml", "vol", Fraction(1)),
    "l": ("l", "vol", Fraction(1000)),
    "liter": ("l", "vol", Fraction(1000)),
    "liters": ("l", "vol", Fraction(1000)),
    "litre": ("l", "vol", Fraction(1000)),
    "litres": ("l", "vol", Fraction(1000)),
    "ounce": ("oz", "mass", Fraction(28349, 1000)),
    "ounces": ("oz", "mass", Fraction(28349, 1000)),
    "oz": ("oz", "mass", Fraction(28349, 1000)),
    "pound": ("lb", "mass", Fraction(45359, 100)),
    "pounds": ("lb", "mass", Fraction(45359, 100)),
    "lb": ("lb", "mass", Fraction(45359, 100)),
    "lbs": ("lb", "mass", Fraction(45359, 100)),
    "g": ("g", "mass", Fraction(1)),
    "gram": ("g", "mass", Fraction(1)),
    "grams": ("g", "mass", Fraction(1)),
    "kg": ("kg", "mass", Fraction(1000)),
    "kilogram": ("kg", "mass", Fraction(1000)),
    "kilograms": ("kg", "mass", Fraction(1000)),
    "clove": ("clove", None, None),
    "cloves": ("clove", None, None),
    "bunch": ("bunch", None, None),
    "bunches": ("bunch", None, None),
    "stick": ("stick", None, None),
    "sticks": ("stick", None, None),
    "can": ("can", None, None),
    "cans": ("can", None, None),
    "sprig": ("sprig", None, None),
    "sprigs": ("sprig", None, None),
    "pinch": ("pinch", None, None),
    "pinches": ("pinch", None, None),
    "head": ("head", None, None),
    "heads": ("head", None, None),
    "recipe": ("recipe", None, None),
    "recipes": ("recipe", None, None),
}

NUMBER_TOKEN = re.compile(
    r"^\s*(\d+\s+\d+/\d+"          # mixed: 1 1/2
    r"|\d+/\d+"                    # fraction: 1/2
    r"|\d+(?:\.\d+)?"              # int or decimal
    r")"
)


def parse_number(tok):
    tok = tok.strip()
    m = re.match(r"^(\d+)\s+(\d+)/(\d+)$", tok)
    if m:
        return Fraction(int(m.group(1))) + Fraction(int(m.group(2)), int(m.group(3)))
    if "/" in tok:
        num, den = tok.split("/")
        return Fraction(int(num), int(den))
    return Fraction(str(float(tok))).limit_denominator(1000)


def parse_quantity(text):
    """Return (lo, hi, unit, rest) or None if no leading quantity parses.

    lo/hi are Fractions (equal unless a range). unit is canonical or None.
    """
    work = text
    # rewrite unicode fractions as ascii so "1 ½" and "1½" parse as mixed numbers
    for ch, frac in UNICODE_FRACTIONS.items():
        work = work.replace(ch, f" {frac.numerator}/{frac.denominator} ")
    work = re.sub(r"\s+", " ", work).strip()
    m = NUMBER_TOKEN.match(work)
    if not m:
        return None
    lo = parse_number(m.group(1))
    rest = work[m.end():].lstrip()
    hi = lo
    rm = re.match(r"^(?:to|-|–)\s*", rest)
    if rm:
        after = rest[rm.end():]
        m2 = NUMBER_TOKEN.match(after)
        if m2:
            hi = parse_number(m2.group(1))
            rest = after[m2.end():].lstrip()
    # unit?
    unit = None
    um = re.match(r"^([A-Za-z]+)\.?\s+", rest + " ")
    if um and um.group(1).lower() in UNIT_ALIASES:
        unit = UNIT_ALIASES[um.group(1).lower()][0]
        rest = rest[um.end():].lstrip() if um.end() <= len(rest) else ""
    return lo, hi, unit, rest.strip()


def fmt_frac(f):
    f = f.limit_denominator(16)
    if f.denominator == 1:
        return str(f.numerator)
    whole, remainder = divmod(f.numerator, f.denominator)
    if whole:
        return f"{whole} {remainder}/{f.denominator}"
    return f"{f.numerator}/{f.denominator}"


PLURAL_UNITS = {"cup", "clove", "stick", "can", "bunch", "sprig", "pinch",
                "head", "recipe"}


def fmt_qty(lo, hi, unit):
    s = fmt_frac(lo) if lo == hi else f"{fmt_frac(lo)} to {fmt_frac(hi)}"
    if unit:
        if unit in PLURAL_UNITS and hi > 1:
            unit += "s"
        return f"{s} {unit}"
    return s


def best_unit(family, base_amount):
    """Pick a readable unit for a summed base amount."""
    if family == "vol":
        ladder = [("cup", Fraction(23659, 100)), ("tbsp", Fraction(14787, 1000)),
                  ("tsp", Fraction(4929, 1000))]
    elif family == "mass":
        ladder = [("kg", Fraction(1000)), ("lb", Fraction(45359, 100)),
                  ("oz", Fraction(28349, 1000)), ("g", Fraction(1))]
    else:
        return None
    for unit, factor in ladder:
        if base_amount / factor >= 1:
            return unit, factor
    return ladder[-1]


# ---------------------------------------------------------------- recipe files

def all_recipe_files():
    return sorted(p for p in RECIPES.rglob("*.md"))


def find_recipe(query, files):
    """Resolve a path or fuzzy name. Returns (path, None) or (None, candidates)."""
    p = Path(query)
    if p.suffix == ".md" and p.exists():
        return p.resolve(), None
    q = query.lower()
    exact = [f for f in files if f.stem.lower() == q]
    if len(exact) == 1:
        return exact[0], None
    subs = [f for f in files if q in f.stem.lower()]
    if len(subs) == 1:
        return subs[0], None
    if not subs:
        words = q.split()
        subs = [f for f in files if all(w in f.stem.lower() for w in words)]
        if len(subs) == 1:
            return subs[0], None
    return None, subs


def resolve_wikilink(name, files):
    name = name.split("|")[0].split("#")[0].strip()
    path, _ = find_recipe(name, files)
    return path


def short_name(path):
    """Recipe display name, trimmed at a parenthetical."""
    return re.sub(r"\s*\(.*\)$", "", path.stem).strip()


def parse_servings(path):
    """Leading integer of the yield: frontmatter line, if any."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^yield:\s*(?:about\s+)?(\d+)(?:\s+to\s+\d+)?\s+servings?",
                  text, re.MULTILINE | re.IGNORECASE)
    return int(m.group(1)) if m else None


def extract_ingredient_lines(path):
    """Yield (line_text, is_optional) from the ## Ingredients section only."""
    lines = path.read_text(encoding="utf-8").splitlines()
    in_section = False
    for line in lines:
        if re.match(r"^##\s+Ingredients\s*$", line):
            in_section = True
            continue
        if in_section and re.match(r"^##\s+", line):
            break
        if not in_section:
            continue
        m = re.match(r"^\s*[-*]\s+(.*\S)\s*$", line)
        if not m:
            continue
        item = m.group(1)
        low = item.lower()
        optional = ("optional" in low or "for serving" in low or "for garnish" in low)
        yield item, optional


# ---------------------------------------------------------------- normalization

STRIP_WORDS = {
    "fresh", "freshly", "squeezed", "ground", "large", "medium", "small",
    "medium-size", "medium-sized", "large-size", "boneless", "skinless",
    "unsalted", "full-fat", "plain", "extra-virgin", "sweet", "whole",
    "finely", "roughly", "coarsely", "thinly",
}


KEY_REMAP = {
    "garlic clove": "garlic",
    "clove garlic": "garlic",
}


def canonical_name(rest):
    """Normalize the post-quantity text to an aggregation key."""
    name = rest
    name = re.sub(r"\[\[([^\]]+)\]\]", r"\1", name)
    name = re.sub(r"\([^)]*\)", " ", name)
    name = re.split(r"\b(?:plus|or)\b", name, maxsplit=1)[0]
    parts = [p for p in name.split(",") if p.strip()]
    name = parts[0] if parts else name
    stripped = [w for w in re.sub(r"[^A-Za-zÀ-ſ\s-]", " ", name).lower().split()
                if w not in STRIP_WORDS]
    # if the first comma segment was all descriptors, fold in the next segment
    if not stripped and len(parts) > 1:
        name = parts[0] + " " + parts[1]
        stripped = [w for w in re.sub(r"[^A-Za-zÀ-ſ\s-]", " ", name).lower().split()
                    if w not in STRIP_WORDS]
    if not stripped:
        stripped = re.sub(r"[^A-Za-zÀ-ſ\s-]", " ", name).lower().split()
    key = " ".join(stripped).strip()
    # light singularization for the key only
    if key.endswith("oes"):
        key = key[:-2]
    elif key.endswith("s") and not key.endswith("ss") and len(key) > 3:
        key = key[:-1]
    return KEY_REMAP.get(key, key)


def display_name(rest):
    name = re.sub(r"\[\[([^\]]+)\]\]", r"\1", rest)
    parts = [p.strip() for p in name.split(",") if p.strip()]
    if not parts:
        return name.strip()
    first_words = re.sub(r"[^A-Za-zÀ-ſ\s-]", " ", parts[0]).lower().split()
    if first_words and all(w in STRIP_WORDS for w in first_words) and len(parts) > 1:
        return f"{parts[0]}, {parts[1]}"
    return parts[0]


# ---------------------------------------------------------------- store sections

SECTIONS = [
    ("Produce", ["onion", "garlic", "ginger", "tomato", "lemon", "lime", "chile",
                 "chili", "jalapeno", "jalapeño", "pepper", "carrot", "potato",
                 "cauliflower", "eggplant", "cucumber", "parsley", "cilantro",
                 "mint", "basil", "scallion", "shallot", "lettuce", "spinach",
                 "kale", "mushroom", "avocado", "apple", "banana", "orange",
                 "celery", "herb", "tomatillo", "zucchini", "squash", "cabbage",
                 "radish", "beet", "leek", "fennel", "dill", "thyme", "rosemary",
                 "sage", "grape", "berr", "mango", "pomegranate"]),
    ("Meat & Seafood", ["chicken", "beef", "pork", "lamb", "turkey", "duck",
                        "sausage", "bacon", "fish", "salmon", "tuna", "shrimp",
                        "prawn", "anchov", "steak", "veal", "ground meat"]),
    ("Dairy & Eggs", ["yogurt", "butter", "cream", "milk", "cheese", "egg",
                      "labneh", "feta", "parmesan", "mozzarella", "ghee",
                      "creme fraiche", "sour cream"]),
    ("Spices", ["paprika", "cumin", "coriander", "turmeric", "allspice",
                "cinnamon", "cardamom", "clove", "bay lea", "bay leaf",
                "garam masala", "sazón", "sazon", "za'atar", "zaatar",
                "sumac", "nutmeg", "oregano", "chili powder", "cayenne",
                "curry powder", "peppercorn", "black pepper", "white pepper",
                "seasoning", "spice", "fennel seed", "mustard seed",
                "sesame seed", "caraway", "star anise", "vanilla"]),
    ("Frozen", ["frozen", "ice cream", "puff pastry", "phyllo", "filo"]),
    ("Alcohol", ["wine", "beer", "vodka", "gin", "rum", "whiskey", "whisky",
                 "bourbon", "tequila", "brandy", "vermouth", "liqueur", "sake",
                 "mezcal", "arak"]),
    ("Pantry", ["oil", "rice", "flour", "sugar", "vinegar", "stock", "broth",
                "pasta", "noodle", "vermicelli", "lentil", "bean", "chickpea",
                "tahini", "tomato paste", "canned", "almond", "pine nut",
                "walnut", "pistachio", "cashew", "peanut", "honey", "molasses",
                "syrup", "soy sauce", "fish sauce", "bread", "pita", "couscous",
                "bulgur", "freekeh", "oat", "cornstarch", "baking", "yeast",
                "chocolate", "cocoa", "coconut", "raisin", "date", "apricot",
                "salt"]),
]


SECTION_OVERRIDES = [
    ("stock", "Pantry"), ("broth", "Pantry"), ("tomato paste", "Pantry"),
    ("black pepper", "Spices"), ("white pepper", "Spices"),
]


def store_section(key):
    for word, section in SECTION_OVERRIDES:
        if word in key:
            return section
    for section, words in SECTIONS:
        for w in words:
            if w in key:
                return section
    return "Other"


SECTION_ORDER = ["Produce", "Meat & Seafood", "Dairy & Eggs", "Pantry",
                 "Spices", "Frozen", "Alcohol", "Other", "Optional"]


# ---------------------------------------------------------------- aggregation

class Entry:
    """One parsed ingredient occurrence."""

    def __init__(self, raw, source, scale, optional):
        self.raw = raw
        self.source = source
        self.optional = optional
        parsed = parse_quantity(raw)
        if parsed and parsed[3]:
            lo, hi, unit, rest = parsed
            # "2 garlic cloves" carries its unit after the noun; treat as cloves
            if unit is None and re.match(r"^garlic cloves?\b", rest, re.IGNORECASE):
                unit = "clove"
            self.lo, self.hi = lo * scale, hi * scale
            self.unit = unit
            self.rest = rest
            self.key = canonical_name(rest)
            self.display = display_name(rest)
            self.parsed = True
        else:
            self.parsed = False
            self.key = canonical_name(raw)
            self.display = display_name(raw)
            if scale != 1 and parsed is None:
                self.raw = f"{raw} (x{fmt_frac(Fraction(scale).limit_denominator(100))})"

    def family(self):
        if not self.parsed or self.unit is None:
            return self.unit
        return UNIT_ALIASES.get(self.unit, (None, None, None))[1] or self.unit


def collect_recipe(path, files, scale, entries, seen, depth=0, via=None):
    if path in seen:
        return
    seen.add(path)
    source = short_name(path) if via is None else f"{short_name(path)} via {via}"
    for raw, optional in extract_ingredient_lines(path):
        wl = re.search(r"\[\[([^\]]+)\]\]", raw)
        if wl:
            target = resolve_wikilink(wl.group(1), files)
            if target and depth < MAX_DEPTH:
                sub_scale = scale
                q = parse_quantity(raw)
                if q and q[2] == "recipe":
                    sub_scale = scale * q[0]
                collect_recipe(target, files, sub_scale, entries, seen,
                               depth + 1, via=short_name(path))
                continue
        entries.append(Entry(raw, source, scale, optional))


def aggregate(entries):
    """Group entries by (key, optional-flag); sum what sums, keep the rest verbatim."""
    groups = {}
    for e in entries:
        groups.setdefault((e.key, e.optional), []).append(e)
    items = []
    for (key, optional), group in sorted(groups.items()):
        sources = []
        for e in group:
            if e.source not in sources:
                sources.append(e.source)
        display = min((e.display for e in group), key=len)
        summed, leftovers = try_sum(group)
        items.append({
            "key": key, "optional": optional, "display": display,
            "total": summed, "leftovers": leftovers, "sources": sources,
        })
    return items


def try_sum(group):
    """Sum compatible parsed quantities. Returns (total_str_or_None, leftover_raws)."""
    parsed = [e for e in group if e.parsed]
    leftovers = []
    for e in group:
        if not e.parsed and e.raw not in leftovers:
            leftovers.append(e.raw)
    if not parsed:
        return None, leftovers
    fams = {}
    for e in parsed:
        fams.setdefault(e.family(), []).append(e)
    totals = []
    for fam, es in fams.items():
        if fam in ("vol", "mass"):
            units = {e.unit for e in es}
            if len(units) == 1:
                # every line used the same unit; keep it as written
                unit = units.pop()
                totals.append(fmt_qty(sum(e.lo for e in es),
                                      sum(e.hi for e in es), unit))
                continue
            base_lo = sum(e.lo * UNIT_ALIASES[e.unit][2] for e in es)
            base_hi = sum(e.hi * UNIT_ALIASES[e.unit][2] for e in es)
            unit, factor = best_unit(fam, base_hi)
            totals.append(fmt_qty(base_lo / factor, base_hi / factor, unit))
        else:
            units = {e.unit for e in es}
            if len(units) == 1:
                lo = sum(e.lo for e in es)
                hi = sum(e.hi for e in es)
                totals.append(fmt_qty(lo, hi, units.pop()))
            else:
                leftovers.extend(e.raw for e in es)
    if not totals:
        return None, leftovers
    return " + ".join(totals), leftovers


# ---------------------------------------------------------------- output

def build_markdown(items, recipe_names, date_str):
    lines = [f"# Shopping List {date_str}", "",
             f"Recipes: {', '.join(recipe_names)}", ""]
    by_section = {}
    for it in items:
        section = "Optional" if it["optional"] else store_section(it["key"])
        by_section.setdefault(section, []).append(it)
    for section in SECTION_ORDER:
        if section not in by_section:
            continue
        lines.append(f"## {section}")
        lines.append("")
        for it in by_section[section]:
            src = ", ".join(it["sources"])
            if it["total"] and not it["leftovers"]:
                lines.append(f"- [ ] {it['display']}: {it['total']} ({src})")
            elif it["total"]:
                lines.append(f"- [ ] {it['display']}: {it['total']} ({src})")
                for lv in it["leftovers"]:
                    lines.append(f"    - also: {lv}")
            else:
                if len(it["leftovers"]) == 1:
                    lines.append(f"- [ ] {it['leftovers'][0]} ({src})")
                else:
                    lines.append(f"- [ ] {it['display']} ({src})")
                    for lv in it["leftovers"]:
                        lines.append(f"    - {lv}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_kv_multipliers(pairs, label):
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            sys.exit(f"Bad {label} argument (expected name=value): {pair}")
        name, val = pair.rsplit("=", 1)
        try:
            out[name.strip().lower()] = Fraction(str(float(val)))\
                .limit_denominator(100)
        except ValueError:
            sys.exit(f"Bad {label} value: {val}")
    return out


def main():
    ap = argparse.ArgumentParser(description="Generate a shopping list from vault recipes.")
    ap.add_argument("recipes", nargs="+", help="recipe paths or fuzzy names")
    ap.add_argument("--scale", action="append", metavar="NAME=MULT",
                    help='per-recipe multiplier, e.g. --scale "butter chicken=2"')
    ap.add_argument("--servings", action="append", metavar="NAME=N",
                    help="scale a recipe to N servings using its yield")
    ap.add_argument("--guests", type=int, metavar="N",
                    help="scale every recipe with a parseable yield to serve N")
    ap.add_argument("--yes", action="store_true", help="write without confirming")
    ap.add_argument("--clipboard", action="store_true",
                    help="also copy the plain checklist via pbcopy")
    ap.add_argument("--vault", action="store_true",
                    help="write into Recipes/private/Shopping Lists/ "
                         "instead of the Desktop")
    args = ap.parse_args()

    files = all_recipe_files()
    scale_map = parse_kv_multipliers(args.scale, "--scale")
    servings_map = parse_kv_multipliers(args.servings, "--servings")

    paths = []
    for query in args.recipes:
        path, candidates = find_recipe(query, files)
        if path is None:
            if candidates:
                print(f'Ambiguous recipe "{query}". Candidates:')
                for c in candidates:
                    print(f"  - {c.relative_to(VAULT)}")
                sys.exit("Re-run with a more specific name or a path.")
            sys.exit(f'No recipe found matching "{query}".')
        paths.append((query, path))

    entries = []
    recipe_names = []
    for query, path in paths:
        scale = Fraction(1)
        q = query.lower()
        for name, mult in scale_map.items():
            if name in q or name in path.stem.lower():
                scale *= mult
        target_servings = None
        for name, n in servings_map.items():
            if name in q or name in path.stem.lower():
                target_servings = n
        if target_servings is None and args.guests:
            target_servings = Fraction(args.guests)
        if target_servings is not None:
            base = parse_servings(path)
            if base:
                scale *= target_servings / base
            else:
                print(f"Note: no parseable yield in {path.name}; "
                      f"servings scaling skipped for it.")
        recipe_names.append(short_name(path)
                            + (f" (x{fmt_frac(scale)})" if scale != 1 else ""))
        collect_recipe(path, files, scale, entries, set())

    items = aggregate(entries)
    date_str = datetime.date.today().isoformat()
    md = build_markdown(items, recipe_names, date_str)

    names_part = ", ".join(short_name(p) for _, p in paths)
    out_dir = LISTS_DIR if args.vault else Path.home() / "Desktop"
    out_path = out_dir / f"{date_str} {names_part}.md"

    print(md)
    print(f"Destination: {out_path}")
    if not args.yes:
        answer = input("Write this list? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Not written.")
            if args.clipboard:
                subprocess.run(["pbcopy"], input=md.encode("utf-8"))
                print("Copied to clipboard.")
            return
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote {out_path}")
    if args.clipboard:
        subprocess.run(["pbcopy"], input=md.encode("utf-8"))
        print("Copied to clipboard.")


if __name__ == "__main__":
    main()
