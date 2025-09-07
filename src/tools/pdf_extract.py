from typing import Dict, Any
import pdfplumber
from ..util.io import read_bytes_safe
from ..sandbox import must_be_allowed

tool_spec = {
    "name": "pdf_extract",
    "description": "Extrae texto y tablas de un PDF local",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "pages": {"type": "array", "items": {"type": "integer"}}
        },
        "required": ["path"]
    },
    "output_schema": {"type": "object"}
}

def _tables_to_json(tbl):
    return {"rows": tbl.extract()}

def run(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args["path"]
    pages = args.get("pages")
    # dispara validaciones y límites
    _ = read_bytes_safe(path)
    pdf_path = str(must_be_allowed(path))

    out_text = []
    out_tables = []
    with pdfplumber.open(pdf_path) as pdf:
        page_iter = (pdf.pages[i-1] for i in pages) if pages else pdf.pages
        for p in page_iter:
            out_text.append(p.extract_text() or "")
            for table in (p.extract_tables() or []):
                out_tables.append({"rows": table})
    return {
        "text": "\n".join(out_text).strip(),
        "tables": out_tables,
        "meta": {"path": pdf_path}
    }
