# src/tools/report_generate.py
from __future__ import annotations
from typing import Any, Dict, List
from pathlib import Path
import datetime as dt
import re
import html

# ----------------- Def MCP -----------------
def tool_def():
    return {
        "name": "report_generate",
        "description": "Genera un reporte en HTML/MD/PDF con secciones de texto, tablas y gráficos.",
        "args_schema": {
            "type": "object",
            "properties": {
                "title":   {"type": "string"},
                # sections admite:
                # - string (texto/markdown-lite/HTML)
                # - {"type":"table","title":str,"records":[{...}, ...]}
                # - {"type":"chart_forecast","title":str,"forecast":[{"t":iso,"yhat":float,"lo":float,"hi":float}, ...]}
                # - {"type":"html","content":str}
                "sections":{"type": "array", "items": {"type": ["string", "object"]}},
                "format":  {"type": "string", "enum": ["html","md","pdf"], "default": "html"},
                "out_dir": {"type": "string", "description": "Carpeta destino (default: reports/)"}
            },
            "required": ["title","sections"]
        }
    }

# Retrocompat si tu registry buscaba tool_spec
tool_spec = tool_def()

# ----------------- Helpers -----------------
def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\- ]+", "", s)
    s = re.sub(r"\s+", "-", s)
    return s or "reporte"

BASE_CSS = """
:root {
  --text: #111; --muted: #555; --bg: #fff; --card: #fafafa;
  --border: #e5e7eb; --heading: #0f172a; --accent: #2563eb;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, Arial, sans-serif;
       margin: 24px; color: var(--text); background: var(--bg); }
h1 { font-size: 22px; margin: 8px 0 2px; color: var(--heading); }
h2 { font-size: 16px; margin: 12px 0 8px; color: var(--heading); }
header { margin-bottom: 12px; }
.date { color: var(--muted); font-size: 12px; }
.section { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin: 10px 0; }
.hr { height: 1px; background: var(--border); margin: 10px 0; }
.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.table th, .table td { border: 1px solid var(--border); padding: 6px 8px; text-align: left; }
.table th { background: #f6f7f9; font-weight: 600; }
img { max-width: 100%; display: block; margin: 6px 0; }
small.note { color: var(--muted); }
"""

def _render_text_section(raw: str) -> str:
    s = (raw or "").strip()
    # Si parece HTML, insértalo tal cual
    if "<" in s and ">" in s and ("</" in s or "/>" in s):
        return f"<section class='section'>{s}</section>"
    # Markdown-lite tipo "# Título"
    if s.startswith("# "):
        head, body = s.split("\n", 1) if "\n" in s else (s, "")
        title = html.escape(head[2:].strip())
        body_html = html.escape(body).replace("\n", "<br/>")
        return f"<section class='section'><h2>{title}</h2><div>{body_html}</div></section>"
    # Texto plano
    return f"<section class='section'><div>{html.escape(s).replace('\\n','<br/>')}</div></section>"

def _table_from_records(records: List[dict], title: str | None = None) -> str:
    if not records:
        return "<section class='section'><div><em>Tabla vacía</em></div></section>"
    # columnas = unión ordenada por aparición
    cols: List[str] = []
    for r in records:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    thead = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    rows = []
    for r in records:
        tds = "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols)
        rows.append(f"<tr>{tds}</tr>")
    title_html = f"<h2>{html.escape(title)}</h2>" if title else ""
    return f"""
    <section class="section">
      {title_html}
      <table class="table">
        <thead><tr>{thead}</tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    """

def _chart_forecast_section(forecast: List[dict], title: str, out_dir: Path, slug: str, ts: str) -> str:
    if not forecast:
        return "<section class='section'><div><em>No hay datos de pronóstico</em></div></section>"
    # Matplotlib en modo headless
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [f.get("t") for f in forecast]
    ys = [float(f.get("yhat", 0.0)) for f in forecast]
    lo = [float(f.get("lo", f.get("yhat", 0.0))) for f in forecast]
    hi = [float(f.get("hi", f.get("yhat", 0.0))) for f in forecast]

    fig, ax = plt.subplots(figsize=(7.5, 3.5))
    ax.plot(xs, ys, label="Pronóstico (yhat)")
    try:
        ax.fill_between(xs, lo, hi, alpha=0.2, label="IC 95%")
    except Exception:
        pass
    ax.set_title(title)
    ax.set_xlabel("t")
    ax.set_ylabel("valor")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    # Guardar PNG en out_dir
    img_path = out_dir / f"{slug}_{ts}_forecast.png"
    fig.savefig(img_path, bbox_inches="tight", dpi=160)
    plt.close(fig)
    # Referenciar por nombre relativo (base_url en PDF permitirá resolverlo)
    return f"<section class='section'><h2>{html.escape(title)}</h2><img src=\"{img_path.name}\" alt=\"Pronóstico\"/></section>"

def _render_section(obj: Any, out_dir: Path, slug: str, ts: str) -> str:
    if isinstance(obj, str):
        return _render_text_section(obj)
    if isinstance(obj, dict):
        typ = obj.get("type")
        if typ == "table":
            return _table_from_records(obj.get("records") or [], obj.get("title"))
        if typ == "chart_forecast":
            return _chart_forecast_section(obj.get("forecast") or [], obj.get("title", "Pronóstico"), out_dir, slug, ts)
        if typ == "html":
            return f"<section class='section'>{obj.get('content','')}</section>"
        # fallback: imprime el dict como <pre>
        return f"<section class='section'><pre>{html.escape(str(obj))}</pre></section>"
    # fallback
    return f"<section class='section'><pre>{html.escape(str(obj))}</pre></section>"

def _build_html_doc(title: str, sections: List[Any], out_dir: Path, slug: str, ts: str) -> str:
    body = "\n".join(_render_section(s, out_dir, slug, ts) for s in sections)
    now = dt.datetime.now().isoformat(timespec="seconds")
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(title)}</title>
  <style>{BASE_CSS}</style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <div class="date">{now}</div>
  </header>
  <div class="hr"></div>
  {body}
  <footer><small class="note">Reporte generado localmente.</small></footer>
</body>
</html>"""

# ----------------- Runner MCP -----------------
def run(args: Dict[str, Any]) -> Dict[str, Any]:
    title: str = args["title"]
    sections: List[Any] = args.get("sections") or []
    fmt: str = (args.get("format") or "html").lower()
    out_dir = Path(args.get("out_dir") or (Path.cwd() / "reports"))
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(title)

    # Markdown (simple): concatenar strings y serializar otros objetos
    if fmt == "md":
        md_path = out_dir / f"{slug}_{ts}.md"
        md_body_parts: List[str] = []
        for s in sections:
            if isinstance(s, str):
                md_body_parts.append(s)
            elif isinstance(s, dict) and s.get("type") == "table":
                # Tabla simple en markdown
                recs = s.get("records") or []
                if recs:
                    cols = list(recs[0].keys())
                    header = "| " + " | ".join(cols) + " |"
                    sep    = "| " + " | ".join(["---"] * len(cols)) + " |"
                    rows   = ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in recs]
                    if s.get("title"):
                        md_body_parts.append(f"## {s['title']}")
                    md_body_parts += [header, sep] + rows
                else:
                    md_body_parts.append("_Tabla vacía_")
            else:
                md_body_parts.append(str(s))
        md_body = "\n\n".join(md_body_parts)
        md_path.write_text(md_body, encoding="utf-8")
        return {"artifactPath": str(md_path), "preview": md_body[:500], "meta": {"format": "md", "bytes": md_path.stat().st_size}}

    # HTML base (siempre lo generamos; además se usa como origen para PDF)
    html_doc = _build_html_doc(title, sections, out_dir, slug, ts)

    if fmt == "pdf":
        # PDF con WeasyPrint (usa base_url=out_dir para resolver PNGs del chart)
        try:
            from weasyprint import HTML, CSS  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "WeasyPrint no está instalado o faltan dependencias del sistema. "
                "Instala con `pip install weasyprint` y en macOS `brew install pango cairo gdk-pixbuf libffi`. "
                f"Detalle: {e}"
            )
        pdf_path = out_dir / f"{slug}_{ts}.pdf"
        HTML(string=html_doc, base_url=str(out_dir)).write_pdf(pdf_path, stylesheets=[CSS(string=BASE_CSS)])
        return {"artifactPath": str(pdf_path), "preview": f"{title} (PDF)", "meta": {"format": "pdf", "bytes": pdf_path.stat().st_size}}

    # HTML (por defecto o fallback)
    html_path = out_dir / f"{slug}_{ts}.html"
    html_path.write_text(html_doc, encoding="utf-8")
    return {"artifactPath": str(html_path), "preview": "OK", "meta": {"format": "html", "bytes": html_path.stat().st_size}}
