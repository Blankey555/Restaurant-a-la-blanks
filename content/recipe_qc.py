#!/usr/bin/env python3
"""Cross-check quantities between each recipe's grid, ingredient list, and instructions.
Run from the vault root. Hits are leads, not verdicts: split amounts ("remaining 3/4 cup"),
scoop sizes, and water are expected to show up."""
import re, sys
from pathlib import Path
sys.path.insert(0, "."); import recipe_grid as rg, yaml
FR = {"¼":" 1/4","½":" 1/2","¾":" 3/4","⅓":" 1/3","⅔":" 2/3","⅛":" 1/8","⅜":" 3/8","⅝":" 5/8","⅞":" 7/8"}
def normtext(s):
    for k,v in FR.items(): s = s.replace(k, v)
    return re.sub(r"\s+", " ", s)
UNIT = r"(?:cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|kg|ml|l|cloves?|sprigs?|sheets?|cans?|tins?|slices?|heads?|bunch(?:es)?|stalks?|eggs?|sticks?)"
QTY = re.compile(r"(\d+(?:[./]\d+)?(?:\s+\d/\d)?)\s*(" + UNIT + r")\b", re.I)
def norm_unit(u):
    u=u.lower()
    for k,v in {"tablespoon":"tbsp","teaspoon":"tsp","ounce":"oz","pound":"lb","lbs":"lb","gram":"g"}.items():
        if u.startswith(k): return v
    return u.rstrip("s") if u not in ("oz","tbsp","tsp","ml","g","kg","l") else u
def frac(s):
    try:
        s=s.strip()
        if " " in s: a,b=s.split(); return float(a)+eval(b)
        return float(eval(s)) if "/" in s else float(s)
    except Exception: return None
def qtys(text):
    out=set()
    for m in QTY.finditer(normtext(text)):
        v=frac(m.group(1)); u=norm_unit(m.group(2))
        if v is not None: out.add((round(v,3),u))
    return out
def leaves(node, acc):
    if isinstance(node,str): acc.append(node)
    elif isinstance(node,dict):
        for c in node.get("of",[]): leaves(c,acc)
    elif isinstance(node,list):
        for c in node: leaves(c,acc)
hits={}
for p in sorted(Path("Recipes").rglob("*.md")):
    if "private" in p.parts: continue
    md=p.read_text(encoding="utf-8"); issues=[]
    secs=re.split(r"^(#{2,4} .*)$", md, flags=re.M); ing=""; instr=""; mode=None; lvl=0
    for i in range(1,len(secs)-1,2):
        h=secs[i]; body=secs[i+1]; L=len(h)-len(h.lstrip("#")); hl=h.lower()
        if "ingredient" in hl: mode="ing"; lvl=L
        elif "instruction" in hl or "method" in hl: mode="instr"; lvl=L
        elif L<=lvl: mode=None
        if mode=="ing": ing+=body
        elif mode=="instr": instr+=body
    ingq=qtys(ing)
    m=rg.STORED_RE.search(md)
    if m:
        L=[]; leaves(yaml.safe_load(m.group(1)).get("steps"),L)
        for leaf in L:
            for q in qtys(leaf):
                if q not in ingq: issues.append(f"GRID {q[0]:g} {q[1]}  <- {leaf[:80]!r}")
    for q in qtys(instr):
        if q not in ingq: issues.append(f"INSTR {q[0]:g} {q[1]}")
    if issues: hits[str(p)]=issues
for k,v in hits.items():
    print("\n"+k); [print("   -",i) for i in v]
print(f"\n{len(hits)} files flagged")
