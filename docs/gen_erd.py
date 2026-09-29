"""Generate a rich, landscape ERD from the LIVE claims.db schema.

Columns, types, PK/FK flags and the relationship set are all read from the
database via PRAGMA. Boxes are grouped into zones with relationship verbs, a
legend and schema stats. Writes erd-real.html; render with headless Chrome
(command printed at the end).

    python3 docs/gen_erd.py
"""

from __future__ import annotations

import html
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent / "data" / "claims.db"
W, H = 1800, 1240
ACCENT, PKBG, DOT = "#4f46e5", "#eef2ff", "#eef2ff"

TABLES = ["policies", "policy_perils", "policy_coverages", "policy_sublimits",
          "claims", "documents", "decisions", "rule_results", "fraud_signals", "human_reviews"]

POS = {
    "policies": (60, 190), "policy_perils": (60, 720),
    "policy_coverages": (60, 890), "policy_sublimits": (60, 1030),
    "claims": (440, 190), "documents": (810, 190),
    "decisions": (810, 560), "rule_results": (1180, 560),
    "fraud_signals": (1180, 900), "human_reviews": (1510, 560),
}

ZONES = [
    (28, 150, 300, 1060, "Policy", "rgba(79,70,229,.06)", "rgba(79,70,229,.35)"),
    (400, 150, 650, 370, "Claim intake", "rgba(14,165,233,.06)", "rgba(14,165,233,.35)"),
    (770, 520, 1000, 690, "Decision &amp; audit", "rgba(124,58,237,.06)", "rgba(124,58,237,.35)"),
]

# (svg path, [cardinality labels], verb label)
LINES = [
    ("M300,270 H440", [(312, 262, "1"), (420, 262, "&#8734;")], (348, 250, "insures")),
    ("M45,690 H30 V1100 M30,800 H60 M30,960 H60 M30,1095 H60",
     [(20, 810, "&#8734;"), (20, 970, "&#8734;"), (20, 1105, "&#8734;")], None),
    ("M690,260 H810", [(702, 252, "1"), (790, 252, "&#8734;")], (720, 242, "attaches")),
    ("M560,660 V690 H810", [(568, 700, "1"), (790, 700, "&#8734;")], (600, 690, "assessed by")),
    ("M1050,690 H1180", [(1062, 682, "1"), (1160, 682, "&#8734;")], (1075, 672, "applies")),
    ("M1050,860 H1180", [(1062, 852, "1"), (1160, 852, "&#8734;")], (1075, 842, "flags")),
    ("M930,560 V515 H1630 V560", [(1620, 552, "&#8734;")], (1300, 505, "reviewed by")),
]


def introspect(db, tables):
    con = sqlite3.connect(db)
    out, nfk = {}, 0
    for t in tables:
        cols = [(r[1], r[2], bool(r[5])) for r in con.execute(f"PRAGMA table_info({t})")]
        fks = {r[3] for r in con.execute(f"PRAGMA foreign_key_list({t})")}
        nfk += len(list(con.execute(f"PRAGMA foreign_key_list({t})")))
        out[t] = {"cols": cols, "fks": fks}
    con.close()
    ncols = sum(len(v["cols"]) for v in out.values())
    return out, ncols, nfk


def card(name, meta, x, y):
    lis = []
    for cname, ctype, pk in meta["cols"]:
        badge = ('<span class="k pk">PK</span>' if pk
                 else ('<span class="k fk">FK</span>' if cname in meta["fks"] else ""))
        lis.append(f'<li>{badge}<span class="nm">{html.escape(cname)}</span>'
                   f'<span class="ty">{html.escape((ctype or "").lower())}</span></li>')
    return (f'<div class="entity" style="left:{x}px; top:{y}px;">'
            f'<div class="h">{html.escape(name)}</div><ul>{"".join(lis)}</ul></div>')


CSS = """<style>
 :root {{ --accent:{accent}; --pkbg:{pkbg}; --dot:{dot}; }}
 *{{box-sizing:border-box;margin:0;padding:0;}} html,body{{width:{W}px;height:{H}px;}}
 body{{font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;color:#0f172a;background:#fff;position:relative;}}
 .bg{{position:absolute;inset:0;background-image:radial-gradient(var(--dot) 1.4px,transparent 1.4px);background-size:26px 26px;opacity:.55;}}
 header{{position:absolute;top:28px;left:44px;z-index:5;}} h1{{font-size:28px;letter-spacing:-.02em;}} h1 .tag{{color:var(--accent);}}
 .sub{{color:#64748b;font-size:14px;margin-top:5px;}}
 .legend{{position:absolute;top:34px;right:46px;z-index:5;display:flex;gap:16px;align-items:center;font-size:12.5px;color:#475569;}}
 .legend .k{{font-size:9px;font-weight:700;padding:1px 5px;border-radius:4px;margin-right:5px;}}
 .legend .swatch{{display:inline-flex;align-items:center;}}
 .pk{{background:var(--pkbg);color:var(--accent);}} .fk{{background:#f1f5f9;color:#64748b;}}
 .zone{{position:absolute;z-index:0;border:1.5px dashed;border-radius:16px;}}
 .zone-label{{position:absolute;z-index:1;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#475569;}}
 svg.lines{{position:absolute;inset:0;z-index:1;}}
 .entity{{position:absolute;z-index:2;width:240px;background:#fff;border:1px solid #e2e8f0;border-radius:12px;box-shadow:0 6px 20px rgba(15,23,42,.08);overflow:hidden;}}
 .entity .h{{background:var(--accent);color:#fff;font-weight:700;font-size:14px;padding:9px 13px;}}
 .entity ul{{list-style:none;padding:6px 0;}}
 .entity li{{font-size:11.5px;padding:2.5px 13px;display:flex;align-items:center;gap:7px;color:#334155;}}
 .entity li .nm{{flex:1;}} .entity li .ty{{color:#94a3b8;font-size:9.5px;}}
 .entity li .k{{font-size:8.5px;font-weight:700;padding:1px 5px;border-radius:4px;}}
 .rel{{fill:#64748b;font-size:12px;font-weight:700;}}
 .verb{{fill:#4f46e5;font-size:11.5px;font-style:italic;}}
</style>"""


def main():
    data, ncols, nfk = introspect(DB, TABLES)
    zones = "".join(
        f'<div class="zone" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;'
        f'background:{fill};border-color:{bc};"></div>'
        f'<div class="zone-label" style="left:{x+16}px;top:{y+12}px;">{lbl}</div>'
        for (x, y, w, h, lbl, fill, bc) in ZONES)
    cards = "".join(card(t, data[t], *POS[t]) for t in TABLES)
    svg = ""
    for path, labels, verb in LINES:
        svg += f'<path d="{path}" stroke="#94a3b8" stroke-width="2" fill="none"/>'
        for lx, ly, tx in labels:
            svg += f'<text class="rel" x="{lx}" y="{ly}">{tx}</text>'
        if verb:
            svg += f'<text class="verb" x="{verb[0]}" y="{verb[1]}">{verb[2]}</text>'
    legend = (
        '<div class="legend">'
        '<span class="swatch"><span class="k pk">PK</span>primary key</span>'
        '<span class="swatch"><span class="k fk">FK</span>foreign key</span>'
        '<span>1 &mdash;&mdash; &#8734; one&#8209;to&#8209;many</span></div>')
    page = ("<!doctype html><html><head><meta charset='utf-8'>"
            + CSS.format(accent=ACCENT, pkbg=PKBG, dot=DOT, W=W, H=H)
            + "</head><body><div class='bg'></div>"
            "<header><h1>Insurance Claim Triage <span class='tag'>&mdash; database schema</span></h1>"
            f"<div class='sub'>Auto-generated from the live SQLite schema (claims.db) &middot; "
            f"{len(TABLES)} tables &middot; {ncols} columns &middot; {nfk} relationships.</div></header>"
            + legend
            + f"<svg class='lines' width='{W}' height='{H}'>{svg}</svg>{zones}{cards}</body></html>")
    (HERE / "erd-real.html").write_text(page)
    print(f"wrote erd-real.html ({len(TABLES)} tables, {ncols} cols, {nfk} rels)\nRender:")
    print(f'  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless '
          f'--disable-gpu --hide-scrollbars --force-device-scale-factor=2 '
          f'--window-size={W},{H} --screenshot="{HERE}/erd-real.png" "file://{HERE}/erd-real.html"')


if __name__ == "__main__":
    main()
