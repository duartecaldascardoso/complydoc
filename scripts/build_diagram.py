"""Generate the complydoc architecture diagram, light and dark, from one geometry."""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / ".github" / "images"

LIGHT = dict(
    slug="complydoc-architecture",
    paper="#f5f5f5", paper2="#ececec", ink="#22272e", muted="#4f5d75", soft="#7a8399",
    rule="rgba(34,39,46,0.12)", zone_fill="rgba(34,39,46,0.02)", zone_stroke="rgba(34,39,46,0.10)",
    zone_label="rgba(34,39,46,0.40)", store_fill="rgba(34,39,46,0.05)",
    input_fill="rgba(79,93,117,0.10)", accent="#1a7f4b", accent_tint="rgba(26,127,75,0.08)",
    accent_stroke="rgba(26,127,75,0.55)", accent_wash="rgba(26,127,75,0.04)",
)
DARK = dict(
    slug="complydoc-architecture-dark",
    paper="#22272e", paper2="#2c323b", ink="#f5f5f5", muted="#bfc0c0", soft="#8e98ac",
    rule="rgba(245,245,245,0.14)", zone_fill="rgba(245,245,245,0.03)",
    zone_stroke="rgba(245,245,245,0.12)", zone_label="rgba(245,245,245,0.45)",
    store_fill="rgba(245,245,245,0.06)", input_fill="rgba(191,192,192,0.10)",
    accent="#2fa96a", accent_tint="rgba(47,169,106,0.14)",
    accent_stroke="rgba(47,169,106,0.60)", accent_wash="rgba(47,169,106,0.05)",
)

SANS = "'Geist', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'Geist Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"


def node(t, x, y, w, h, tag, name, sub, kind="step", tag_w=32):
    """One box: paper mask, styled rect, rectangular type tag, name, sublabel."""
    if kind == "focal":
        fill, stroke, tag_col = t["accent_tint"], t["accent"], t["accent"]
    elif kind == "store":
        fill, stroke, tag_col = t["store_fill"], t["muted"], t["muted"]
    elif kind == "input":
        fill, stroke, tag_col = t["input_fill"], t["soft"], t["soft"]
    else:
        fill, stroke, tag_col = ("#ffffff" if t["slug"].endswith("dark") is False else t["paper2"]), t["ink"], t["ink"]

    cx, cy = x + w / 2, y + h / 2
    return f"""
  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{t['paper']}"/>
  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1"/>
  <rect x="{x + 12}" y="{y + 10}" width="{tag_w}" height="12" rx="2" fill="none" stroke="{tag_col}" stroke-opacity="0.40" stroke-width="0.8"/>
  <text x="{x + 12 + tag_w / 2}" y="{y + 19}" fill="{tag_col}" fill-opacity="0.85" font-size="7" font-family="{MONO}" text-anchor="middle" letter-spacing="0.08em">{tag}</text>
  <text x="{cx}" y="{cy + 8}" fill="{t['ink']}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{name}</text>
  <text x="{cx}" y="{cy + 24}" fill="{t['soft']}" font-size="9" font-family="{MONO}" text-anchor="middle">{sub}</text>"""


def svg(t: dict) -> str:
    slug = t["slug"]
    a = t["accent"]
    return f"""<svg viewBox="0 0 1000 600" role="img" aria-labelledby="{slug}-title {slug}-desc" xmlns="http://www.w3.org/2000/svg">
  <title id="{slug}-title">complydoc pipeline architecture</title>
  <desc id="{slug}-desc">A folder of documents passes through discovery and a format-specific ingest layer into three independent analysis components — cost, difficulty and sensitive data — which are driven by YAML config and emit a diffable JSON report and a self-contained HTML report. The whole pipeline sits inside a network guard boundary, so no document content can leave the machine.</desc>
  <defs>
    <marker id="{slug}-arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="{t['muted']}"/>
    </marker>
    <marker id="{slug}-arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="{a}"/>
    </marker>
  </defs>

  <rect width="100%" height="100%" fill="{t['paper']}"/>

  <!-- Network guard boundary: drawn first, behind everything -->
  <rect x="24" y="72" width="940" height="440" rx="8" fill="{t['accent_wash']}" stroke="{t['accent_stroke']}" stroke-width="1" stroke-dasharray="4,4"/>
  <rect x="44" y="64" width="96" height="16" rx="2" fill="{t['paper']}"/>
  <text x="52" y="76" fill="{a}" font-size="8" font-family="{MONO}" letter-spacing="0.14em">NETWORK GUARD</text>

  <!-- Analysis zone -->
  <rect x="560" y="112" width="208" height="296" rx="8" fill="{t['zone_fill']}" stroke="{t['zone_stroke']}" stroke-width="0.8"/>
  <rect x="596" y="104" width="136" height="16" rx="2" fill="{t['paper']}"/>
  <text x="664" y="116" fill="{t['zone_label']}" font-size="7" font-family="{MONO}" text-anchor="middle" letter-spacing="0.14em">ANALYSIS · INDEPENDENT</text>

  <!-- Arrows, drawn before boxes -->
  <line x1="184" y1="272" x2="216" y2="272" stroke="{t['muted']}" stroke-width="1.2" marker-end="url(#{slug}-arrow)"/>
  <line x1="352" y1="272" x2="384" y2="272" stroke="{t['muted']}" stroke-width="1.2" marker-end="url(#{slug}-arrow)"/>

  <path d="M 528,252 H 544 Q 552,252 552,244 V 184 Q 552,176 560,176 H 576" fill="none" stroke="{t['muted']}" stroke-width="1.2" marker-end="url(#{slug}-arrow)"/>
  <line x1="528" y1="272" x2="576" y2="272" stroke="{t['muted']}" stroke-width="1.2" marker-end="url(#{slug}-arrow)"/>
  <path d="M 528,292 H 544 Q 552,292 552,300 V 360 Q 552,368 560,368 H 576" fill="none" stroke="{t['muted']}" stroke-width="1.2" marker-end="url(#{slug}-arrow)"/>

  <line x1="664" y1="448" x2="664" y2="408" stroke="{t['muted']}" stroke-width="1.2" stroke-dasharray="4,3" marker-end="url(#{slug}-arrow)"/>
  <rect x="676" y="420" width="84" height="12" rx="2" fill="{t['paper']}"/>
  <text x="680" y="429" fill="{t['soft']}" font-size="8" font-family="{MONO}" letter-spacing="0.06em">THRESHOLDS</text>

  <line x1="768" y1="240" x2="804" y2="240" stroke="{t['muted']}" stroke-width="1.2" marker-end="url(#{slug}-arrow)"/>
  <path d="M 768,300 H 778 Q 786,300 786,308 V 328 Q 786,336 794,336 H 804" fill="none" stroke="{t['muted']}" stroke-width="1.2" marker-end="url(#{slug}-arrow)"/>

  <!-- Nodes -->
{node(t, 48, 240, 136, 64, "INPUT", "documents/", "pdf · img · docx · xlsx", "input", 36)}
{node(t, 216, 240, 136, 64, "WALK", "Discovery", "skips unopenable", "step", 32)}
{node(t, 384, 240, 144, 64, "LOAD", "Ingest", "per-format loaders", "step", 32)}
{node(t, 576, 144, 176, 64, "01", "Cost", "tokens, pages, price", "step", 20)}
{node(t, 576, 240, 176, 64, "02", "Difficulty", "18 measured signals", "step", 20)}
{node(t, 576, 336, 176, 64, "03", "Sensitive", "masked by default", "focal", 20)}
{node(t, 576, 448, 176, 52, "YAML", "Config", "prices · weights · patterns", "store", 32)}
{node(t, 804, 208, 136, 64, "JSON", "report.json", "machine readable", "store", 32)}
{node(t, 804, 304, 136, 64, "HTML", "report.html", "self-contained", "store", 32)}

  <!-- Legend -->
  <line x1="24" y1="544" x2="976" y2="544" stroke="{t['rule']}" stroke-width="0.8"/>
  <text x="24" y="566" fill="{t['muted']}" font-size="8" font-family="{MONO}" letter-spacing="0.14em">LEGEND</text>

  <rect x="112" y="556" width="14" height="12" rx="2" fill="{t['accent_tint']}" stroke="{a}" stroke-width="1"/>
  <text x="134" y="566" fill="{t['soft']}" font-size="8" font-family="{MONO}">MASKED VALUES</text>

  <rect x="356" y="556" width="14" height="12" rx="2" fill="{t['accent_wash']}" stroke="{t['accent_stroke']}" stroke-width="1" stroke-dasharray="3,3"/>
  <text x="378" y="566" fill="{t['soft']}" font-size="8" font-family="{MONO}">NO OUTBOUND SOCKET</text>

  <rect x="592" y="556" width="14" height="12" rx="2" fill="{'#ffffff' if not t['slug'].endswith('dark') else t['paper2']}" stroke="{t['ink']}" stroke-width="1"/>
  <text x="614" y="566" fill="{t['soft']}" font-size="8" font-family="{MONO}">PIPELINE STAGE</text>

  <rect x="792" y="556" width="14" height="12" rx="2" fill="{t['store_fill']}" stroke="{t['muted']}" stroke-width="1"/>
  <text x="814" y="566" fill="{t['soft']}" font-size="8" font-family="{MONO}">CONFIG AND OUTPUT</text>
</svg>"""


def page(t: dict) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>complydoc — pipeline architecture</title>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  body {{ margin:0; background:{t['paper']}; color:{t['ink']};
    font-family:'Geist',sans-serif; padding:3rem 2rem; }}
  .wrap {{ max-width:1080px; margin:0 auto; }}
  .eyebrow {{ font-family:'Geist Mono',monospace; font-size:8px; letter-spacing:0.14em;
    text-transform:uppercase; color:{t['soft']}; margin:0 0 0.5rem; }}
  h1 {{ font-family:'Instrument Serif',serif; font-weight:400; font-size:1.75rem;
    margin:0 0 0.25rem; }}
  .sub {{ color:{t['muted']}; font-size:0.875rem; margin:0 0 2rem; max-width:64ch; }}
  svg {{ width:100%; height:auto; display:block; }}
</style>
</head>
<body>
<div class="wrap">
  <p class="eyebrow">complydoc</p>
  <h1>Pipeline</h1>
  <p class="sub">Files are read locally by per-format loaders, then passed to three analysis
  components that run independently. Each run writes a JSON report and an HTML report.</p>
  {svg(t)}
</div>
</body>
</html>"""


_FONT_DEFS = (
    "<defs>\n    <style>@import url('https://fonts.googleapis.com/css2?"
    "family=Instrument+Serif:ital@0;1&amp;family=Geist:wght@400;500;600&amp;"
    "family=Geist+Mono:wght@400;500;600&amp;display=swap');</style>\n  "
)


def export_svg(html_path: Path) -> Path:
    """Pull the diagram out as a standalone SVG for the README.

    GitHub renders an <img>-referenced SVG with webfonts blocked, so the font
    stacks in the diagram fall back to system faces. The @import is here for
    browsers that open the file directly.
    """
    import re
    import xml.dom.minidom

    html = html_path.read_text(encoding="utf-8")
    match = re.search(r"<svg\b.*?</svg>", html, re.DOTALL)
    if match is None:
        raise SystemExit(f"no <svg> found in {html_path}")
    svg = match.group(0).replace("<defs>", _FONT_DEFS, 1)
    out = html_path.with_suffix(".svg")
    out.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + svg + "\n", encoding="utf-8")
    # A bare & would make the file unparseable as XML and it would not render.
    xml.dom.minidom.parse(str(out))
    return out


for theme in (LIGHT, DARK):
    path = OUT / f"{theme['slug']}.html"
    path.write_text(page(theme), encoding="utf-8")
    svg_path = export_svg(path)
    print(f"wrote {path.name} and {svg_path.name}")
