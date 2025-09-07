tool_spec = {
    "name": "report_generate",
    "description": "Compila un reporte en HTML/PDF a partir de secciones Markdown",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "sections": {"type": "array", "items": {"type": "string"}},
            "format": {"type": "string", "enum": ["html", "pdf", "md"]}
        },
        "required": ["title", "sections"]
    },
    "output_schema": {"type": "object"}
}

def run(args):
    # TODO: concatenar MD, render a HTML con <pre> simple o markdown lib;
    # opcional: export PDF con weasyprint si está disponible.
    return {"status": "todo", "hint": "render markdown → HTML/PDF"}
