#!/Users/alexblankenberg/.venvs/recipe-import/bin/python
"""
recipe_grid.py: generate Cooking-for-Engineers-style process grid tables.

Spec format (YAML):

    setup:                       # optional full-width header rows
      - Butter and flour an 8x8-in pan
      - Preheat oven to 350°F (170°C)
    steps:                       # nested tree; leaves are ingredients,
      op: bake 350°F 30 to 40 min    # ops merge everything beneath them
      of:
        - op: fold in
          of:
            - op: mix
              of:
                - op: melt
                  of: ["4 oz (115 g) unsalted butter"]
                - 1 cup (200 g) sugar
            - 2 large (100 g) eggs
        - 1/2 cup (80 g) all-purpose flour

Usage:
  recipe_grid.py --input spec.yaml          # print HTML table to stdout
  recipe_grid.py --apply "Recipes/x.md"     # convert the file's ```recipe-grid
                                            # fenced block (or stored comment)
                                            # into an embedded styled table
"""

import argparse
import html
import re
import sys
from pathlib import Path

import yaml


# ------------------------------------------------------------------ layout

def natural_width(node):
    if isinstance(node, str):
        return 1
    children = node.get("of", [])
    return 1 + max(natural_width(c) for c in children)


def count_rows(node):
    if isinstance(node, str):
        return 1
    return sum(count_rows(c) for c in node.get("of", []))


def render(node, width):
    """Return rows, each row a list of cell dicts filling `width` columns."""
    if isinstance(node, str):
        return [[{"text": node, "rowspan": 1, "colspan": width, "cls": "rg-ing"}]]
    children = node.get("of", [])
    rows = []
    for c in children:
        rows.extend(render(c, width - 1))
    op_cell = {"text": str(node.get("op", "")), "rowspan": len(rows),
               "colspan": 1, "cls": "rg-op"}
    rows[0].append(op_cell)
    return rows


def spec_to_html(spec):
    tree = spec.get("steps")
    if tree is None:
        raise ValueError("spec needs a 'steps' tree")
    _validate(tree)
    width = natural_width(tree)
    out = ['<table class="recipe-grid">']
    for s in spec.get("setup", []) or []:
        out.append(f'  <tr><td class="rg-setup" colspan="{width}">{html.escape(str(s))}</td></tr>')
    for row in render(tree, width):
        cells = []
        for c in row:
            attrs = []
            if c["rowspan"] > 1:
                attrs.append(f'rowspan="{c["rowspan"]}"')
            if c["colspan"] > 1:
                attrs.append(f'colspan="{c["colspan"]}"')
            attrs.append(f'class="{c["cls"]}"')
            cells.append(f'<td {" ".join(attrs)}>{html.escape(c["text"])}</td>')
        out.append("  <tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def _validate(node, depth=0):
    if depth > 12:
        raise ValueError("tree too deep")
    if isinstance(node, str):
        return
    if not isinstance(node, dict) or "op" not in node or "of" not in node:
        raise ValueError(f"invalid node (need op/of or string): {node!r}")
    if not isinstance(node["of"], list) or not node["of"]:
        raise ValueError(f"'of' must be a non-empty list at: {node.get('op')}")
    for c in node["of"]:
        _validate(c, depth + 1)


# ------------------------------------------------------------------ file embedding

FENCE_RE = re.compile(r"```recipe-grid\n(.*?)```", re.DOTALL)
STORED_RE = re.compile(
    r"%%recipe-grid-spec\n(.*?)%%\n*<table class=\"recipe-grid\">.*?</table>",
    re.DOTALL)
LEGACY_RE = re.compile(
    r"<!-- recipe-grid-spec\n(.*?)-->\n*<table class=\"recipe-grid\">.*?</table>",
    re.DOTALL)


def apply_to_file(path):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    m = FENCE_RE.search(text)
    stored = False
    if not m:
        m = STORED_RE.search(text) or LEGACY_RE.search(text)
        stored = True
    if not m:
        sys.exit("No ```recipe-grid fenced block or stored grid found in file.")
    spec = yaml.safe_load(m.group(1))
    table = spec_to_html(spec)
    replacement = "%%recipe-grid-spec\n" + m.group(1).rstrip() + "\n%%\n\n" + table
    new = text[:m.start()] + replacement + text[m.end():]
    p.write_text(new, encoding="utf-8")
    print(f"{'Regenerated' if stored else 'Converted'} grid in {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="YAML spec file (prints HTML)")
    ap.add_argument("--apply", help="markdown file containing a ```recipe-grid block or stored grid")
    args = ap.parse_args()
    if args.input:
        print(spec_to_html(yaml.safe_load(Path(args.input).read_text(encoding="utf-8"))))
    elif args.apply:
        apply_to_file(args.apply)
    else:
        ap.error("provide --input or --apply")


if __name__ == "__main__":
    main()
