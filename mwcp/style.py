"""Look shared by the HTML pages mwcp writes (performance report, clique view).

Solver colors, the light/dark theme and the hover tooltip live here, so a solver has the same
color everywhere and every page follows the viewer's light/dark setting the same way.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

# Categorical palette (light, dark): fixed slot order, validated for adjacent marks.
PALETTE = [("#257de0", "#338ced"), ("#f47230", "#e76624"), ("#00b894", "#00a888"),
           ("#f2a600", "#d28e05"), ("#ee7fac", "#e24d8b"), ("#008a17", "#0aac23"),
           ("#6a4ce2", "#9887ef"), ("#ec4647", "#eb6263")]
OTHER = ("#8c8c8c", "#7a7a7a")   # a 9th+ solver is never given a generated hue


def _known() -> List[str]:
    try:
        from .solvers import REGISTRY
        return list(REGISTRY)
    except Exception:  # pragma: no cover - pages must render without the solver package
        return []


def solver_order(names: Sequence[str]) -> List[str]:
    """Distinct names, registry solvers first in registry order."""
    seen = list(dict.fromkeys(names))
    known = _known()
    return [s for s in known if s in seen] + [s for s in seen if s not in known]


def solver_colors(solvers: Sequence[str]) -> Dict[str, Tuple[str, str]]:
    """Each solver keeps its registry slot, so a solver is the same color on every page."""
    known = _known()
    order = known + [s for s in solvers if s not in known]
    return {s: (PALETTE[order.index(s)] if order.index(s) < len(PALETTE) else OTHER) for s in solvers}


_LIGHT = "--surface:#fff;--text:#191919;--text2:#666;--grid:#e6e6e6;--limit:#999;--edge:#d0d0d0;--node:#b8b8b8"
_DARK = "--surface:#191919;--text:#efefef;--text2:#9c9c9c;--grid:#2e2e2e;--limit:#777;--edge:#3a3a3a;--node:#5c5c5c"


def dark(rules: Sequence[Tuple[str, str]]) -> str:
    """CSS for dark mode: applies under OS dark mode unless the page is stamped light, and
    whenever it is stamped dark. `rules` are (selector inside .viz-root, declarations)."""
    def scoped(prefix: str) -> str:
        return "".join(f"{prefix} .viz-root {sel}{{{decl}}}" for sel, decl in rules)
    return ('@media (prefers-color-scheme:dark){' + scoped(':root:where(:not([data-theme="light"]))') + '}'
            + scoped(':root[data-theme="dark"]'))


THEME_CSS = (
    ".viz-root{color-scheme:light;" + _LIGHT + ";"
    'font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--text);background:var(--surface);'
    "max-width:820px;margin:0 auto;padding:24px}"
    '@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;'
    + _DARK + '}}:root[data-theme="dark"] .viz-root{color-scheme:dark;' + _DARK + "}"
    """
html,body{margin:0;background:var(--surface,#fff)}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 2px}
.sub,.foot{color:var(--text2);margin:0 0 12px}.foot{font-size:13px;margin-top:4px}
svg{width:100%;height:auto;display:block;overflow:visible}
svg text{font-size:12px;fill:var(--text)}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--text);border:1px solid var(--grid);
  border-radius:6px;padding:6px 9px;font-size:12px;white-space:pre;box-shadow:0 2px 8px rgba(0,0,0,.15);
  display:none;z-index:9}
details{margin-top:28px}summary{cursor:pointer;color:var(--text2)}
table{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:3px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--text2);font-weight:600}
""")

# Hover/focus tooltip: any element with class "mark" and a data-tip attribute.
TIP_JS = """
const tip=document.getElementById('tip');
function showTip(text,x,y){tip.textContent=text;tip.style.display='block';
  const w=tip.offsetWidth,h=tip.offsetHeight;
  tip.style.left=Math.min(x+14,innerWidth-w-8)+'px';tip.style.top=Math.max(8,Math.min(y+14,innerHeight-h-8))+'px';}
function hideTip(){tip.style.display='none';}
function bindTips(root){root.querySelectorAll('.mark').forEach(el=>{
  el.addEventListener('mousemove',e=>showTip(el.dataset.tip,e.clientX,e.clientY));
  el.addEventListener('mouseleave',hideTip);
  el.addEventListener('focus',()=>{const r=el.getBoundingClientRect();showTip(el.dataset.tip,r.left+r.width/3,r.top);});
  el.addEventListener('blur',hideTip);});}
"""


def page(title: str, css: str, body: str, js: str = "") -> str:
    import html
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{THEME_CSS}{css}</style></head><body>"
            f"<div class=\"viz-root\">{body}</div><div id=\"tip\" role=\"tooltip\"></div>"
            f"<script>{TIP_JS}{js}</script></body></html>\n")
