# demo.py
import orjson, subprocess, sys
from pathlib import Path

def _send(proc, payload):
    proc.stdin.write(orjson.dumps(payload) + b"\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("El servidor MCP no respondió (STDOUT vacío).")
    return orjson.loads(line)

def rpc_call(proc, method, params=None, mid=1):
    payload = {"id": mid, "method": method}
    if params is not None:
        payload["params"] = params
    return _send(proc, payload)

def call_tool(proc, name, args, mid):
    return rpc_call(proc, "tools/call", {"name": name, "args": args}, mid)

if __name__ == "__main__":
    p = subprocess.Popen([sys.executable, "main.py"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    # 1) listar tools
    res = rpc_call(p, "tools/list", mid=1)
    tools = {t["name"] for t in res["result"]["tools"]}
    print("Tools registrados:", tools)

    # 2) pdf_extract
    pdf_path = "samples/informe.pdf"
    if Path(pdf_path).exists():
        resp = call_tool(p, "pdf_extract", {"path": pdf_path}, mid=2)
        if "error" in resp:
            print("[pdf_extract][ERROR]", resp["error"].get("message"))
        else:
            r = resp["result"]
            print(f"[pdf_extract] chars={len(r.get('text',''))} tables={len(r.get('tables',[]))}")
            print((r.get("text","")[:300] + "...").replace("\n", " "), "\n")
    else:
        print(f"[pdf_extract] archivo no encontrado: {pdf_path}")

    # 3) data_profile
    csv_path = "samples/datos.csv"
    if "data_profile" in tools and Path(csv_path).exists():
        resp = call_tool(p, "data_profile", {"path": csv_path, "limit_rows": 50000}, mid=3)
        if "error" in resp:
            print("[data_profile][ERROR]", resp["error"].get("message"))
        else:
            r = resp["result"]
            meta = r["meta"]
            print(f"[data_profile] rows={meta['rows']} cols={meta['cols']} mem={meta['memory_bytes']}B")
            print("preview:", r["preview"])
    else:
        print("[data_profile] tool no registrado o CSV no existe")

    # 4) ts_forecast (pronóstico sobre 'produccion' usando 'fecha' como índice)
    if "ts_forecast" in tools and Path(csv_path).exists():
        args = {"path": csv_path, "column": "produccion", "horizon": 6, "date_col": "fecha", "freq": "D"}
        resp = call_tool(p, "ts_forecast", args, mid=4)
        if "error" in resp:
            print("[ts_forecast][ERROR]", resp["error"].get("message"))
        else:
            r = resp["result"]
            print(f"[ts_forecast] modelo={r['model']} rows_used={r['meta']['rows_used']}")
            # Muestra las primeras 3 predicciones
            print("predicciones:", r["forecast"][:3], "...")
    else:
        print("[ts_forecast] tool no registrado o CSV no existe")

    # 5) llm_chat (opcional)
    if "llm_chat" in tools:
        resp = call_tool(p, "llm_chat", {"prompt": "Resume en 1 línea qué hace este servidor MCP."}, mid=5)
        if "error" in resp:
            print("[llm_chat][ERROR]", resp["error"].get("message"))
        else:
            print("[llm_chat]", resp["result"].get("text",""))
    else:
        print("[llm_chat] tool no registrado (opcional).")

    p.terminate()
