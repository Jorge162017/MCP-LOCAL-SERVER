# demo.py — CLIENTE
import os
import sys
import orjson
import subprocess
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent

def _send(proc, payload: dict):
    # Enviar una línea JSON-RPC y leer una respuesta
    proc.stdin.write(orjson.dumps(payload) + b"\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        # Intenta leer algo de stderr para ayudar a depurar
        try:
            err = proc.stderr.read().decode() if proc.stderr else ""
        except Exception:
            err = ""
        raise RuntimeError(f"El servidor MCP no respondió (STDOUT vacío). {err}")
    return orjson.loads(line)

def rpc_call(proc, method: str, params: dict | None = None, mid: int = 1):
    payload = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        payload["params"] = params
    return _send(proc, payload)

def call_tool(proc, name: str, args: dict, mid: int):
    return rpc_call(proc, "tools/call", {"name": name, "args": args}, mid)

if __name__ == "__main__":
    # Asegurar entorno y working dir para el subproceso
    env = {**os.environ, "PYTHONPATH": str(PROJ_ROOT)}
    p = subprocess.Popen(
        [sys.executable, "main.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,   # útil para depurar si algo truena
        cwd=str(PROJ_ROOT),
        env=env,
        text=False,               # trabajamos en binario (orjson)
        bufsize=0
    )

    # 1) listar tools
    res = rpc_call(p, "tools/list", mid=1)
    tools = {t["name"] for t in res["result"]["tools"]}
    print("Tools registrados:", tools)

    r_pdf = None
    r_profile = None
    r_ts = None

    # 2) pdf_extract
    pdf_path = "samples/informe.pdf"
    if Path(pdf_path).exists():
        resp_pdf = call_tool(p, "pdf_extract", {"path": pdf_path}, mid=2)
        if "error" in resp_pdf:
            print("[pdf_extract][ERROR]", resp_pdf["error"].get("message"))
        else:
            r_pdf = resp_pdf["result"]
            print(f"[pdf_extract] chars={len(r_pdf.get('text',''))} tables={len(r_pdf.get('tables',[]))}")
            print((r_pdf.get("text","")[:300] + "...").replace("\n", " "), "\n")
    else:
        print(f"[pdf_extract] archivo no encontrado: {pdf_path}")

    # 3) data_profile
    csv_path = "samples/datos.csv"
    if "data_profile" in tools and Path(csv_path).exists():
        resp_prof = call_tool(p, "data_profile", {"path": csv_path, "limit_rows": 50000}, mid=3)
        if "error" in resp_prof:
            print("[data_profile][ERROR]", resp_prof["error"].get("message"))
        else:
            r_profile = resp_prof["result"]
            meta = r_profile["meta"]
            print(f"[data_profile] rows={meta['rows']} cols={meta['cols']} mem={meta['memory_bytes']}B")
            print("preview:", r_profile["preview"])
    else:
        print("[data_profile] tool no registrado o CSV no existe")

    # 4) ts_forecast (pronóstico sobre 'produccion' usando 'fecha' como índice)
    if "ts_forecast" in tools and Path(csv_path).exists():
        args = {"path": csv_path, "column": "produccion", "horizon": 6, "date_col": "fecha", "freq": "D"}
        resp_ts = call_tool(p, "ts_forecast", args, mid=4)
        if "error" in resp_ts:
            print("[ts_forecast][ERROR]", resp_ts["error"].get("message"))
        else:
            r_ts = resp_ts["result"]
            print(f"[ts_forecast] modelo={r_ts['model']} rows_used={r_ts['meta']['rows_used']}")
            print("predicciones:", r_ts["forecast"][:3], "...")
    else:
        print("[ts_forecast] tool no registrado o CSV no existe")

    # 5) llm_chat (usa el system prompt global del server)
    if "llm_chat" in tools:
        resp_llm = call_tool(
            p,
            "llm_chat",
            {
                "prompt": "Resume en 1 línea qué hace este servidor MCP.",
                "temperature": 0.1,
                "max_tokens": 60
                # No enviamos 'system' -> tomará prompts/system_llm.txt automáticamente
            },
            mid=5
        )
        if "error" in resp_llm:
            print("[llm_chat][ERROR]", resp_llm["error"].get("message"))
        else:
            print("[llm_chat]", resp_llm["result"].get("text", ""))
    else:
        print("[llm_chat] tool no registrado.")

    # 6) report_generate (HTML) con tabla y gráfico)
    if "report_generate" in tools:
        sections = []
        sections.append("# Resumen\nReporte de prueba generado desde el MCP Server local.")

        # Resumen PDF
        if r_pdf:
            sections.append(
                f"**PDF:** Se procesó `{pdf_path}` y se extrajeron ~{len(r_pdf.get('text',''))} "
                f"caracteres y {len(r_pdf.get('tables',[]))} tabla(s)."
            )
        else:
            sections.append("**PDF:** No se generó salida de `pdf_extract`.")

        # Tabla con preview de datos
        if r_profile:
            meta = r_profile.get("meta", {})
            sections.append(
                f"**Datos:** Archivo `{csv_path}` con **{meta.get('rows',0)} filas** y **{meta.get('cols',0)} columnas**."
            )
            sections.append({
                "type": "table",
                "title": "Vista previa (primeras filas)",
                "records": r_profile.get("preview", [])
            })
        else:
            sections.append("**Datos:** No se generó salida de `data_profile`.")

        # Gráfico del pronóstico
        if r_ts:
            sections.append({
                "type": "chart_forecast",
                "title": "Pronóstico de 'produccion'",
                "forecast": r_ts.get("forecast", [])
            })
        else:
            sections.append("**Pronóstico:** No se generó salida de `ts_forecast`.")

        resp_rep = call_tool(
            p,
            "report_generate",
            {"title": "Reporte de Ejemplo – MCP (Local)", "sections": sections, "format": "pdf"},
            mid=6,
        )
        if "error" in resp_rep:
            print("[report_generate][ERROR]", resp_rep["error"].get("message"))
        else:
            rr = resp_rep["result"]
            print(f"[report_generate] listo → {rr['artifactPath']}")
    else:
        print("[report_generate] tool no registrado.")

    # Terminar proceso servidor
    try:
        rpc_call(p, "shutdown", mid=999)
    except Exception:
        pass
    p.terminate()
