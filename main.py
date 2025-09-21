# main.py
import sys
import os
import asyncio
import orjson
import traceback
import time
from pathlib import Path
from dotenv import load_dotenv

# --- Carga .env y asegura sys.path ---
load_dotenv()
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Registry unificado (pdf_extract, data_profile, ts_forecast, report_generate, llm_chat)
from src.util.registry import build_registry
REGISTRY = build_registry()

print("[mcp-local] server ready", file=sys.stderr)

# --------- Config logging ----------
REPORTS_DIR = Path(os.getenv("REPORTS_DIR") or (ROOT / "reports"))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = Path(os.getenv("MCP_LOG_PATH") or (REPORTS_DIR / "mcp.log.jsonl"))
LOG_MAX_BYTES = int(os.getenv("MCP_LOG_MAX_BYTES", "5242880"))  # 5MB aprox.

def _json_default(obj):
    import datetime, numpy as np
    try:
        import pandas as pd
    except Exception:
        pd = None

    if pd is not None and isinstance(obj, pd.Timestamp):
        return obj.to_pydatetime().isoformat()
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    return str(obj)

def _rotate_log_if_needed(path: Path):
    try:
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            backup = path.with_suffix(path.suffix + ".1")
            if backup.exists():
                backup.unlink(missing_ok=True)
            path.rename(backup)
    except Exception:
        # nunca dejes caer el server por un problema de log
        pass

def _redact(value):
    """
    Redacta valores potencialmente sensibles.
    - Si es string largo, lo acorta.
    - Si parece ruta de archivo, la deja (útil para auditar), pero acorta strings >1k.
    - No serializa binarios.
    """
    try:
        if isinstance(value, (bytes, bytearray)):
            return f"<{type(value).__name__}:{len(value)} bytes>"
        if isinstance(value, str) and len(value) > 1000:
            return value[:1000] + "…"
        if isinstance(value, dict):
            return {k: _redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_redact(v) for v in value]
        return value
    except Exception:
        return "<unserializable>"

def log_event(event: dict):
    """
    Escribe una línea JSON por evento:
    {
      ts, method, ok, duration_ms, tool, args, result_size, error
    }
    """
    try:
        _rotate_log_if_needed(LOG_PATH)
        with LOG_PATH.open("ab") as f:
            f.write(orjson.dumps(event, default=_json_default))
            f.write(b"\n")
    except Exception:
        # no interrumpas el flujo por logging
        pass

# ---- Helpers JSON-RPC 2.0 ----
def ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}

def err(mid, code, message, data=None):
    e = {"code": code, "message": message}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": mid, "error": e}

# ---- Lectura asíncrona de STDIN ----
async def ainput():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sys.stdin.buffer.readline)

async def main():
    while True:
        raw = await ainput()
        if not raw:
            break
        if raw.strip() == b"":
            continue

        t0 = time.perf_counter()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")

        try:
            try:
                msg = orjson.loads(raw)
            except Exception:
                resp = err(None, -32700, "Parse error")
                sys.stdout.buffer.write(orjson.dumps(resp) + b"\n")
                sys.stdout.flush()
                # logea parse error
                log_event({
                    "ts": now_iso,
                    "method": "<parse>",
                    "ok": False,
                    "duration_ms": round((time.perf_counter()-t0)*1000, 3),
                    "error": "Parse error"
                })
                continue

            mid = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {}) or {}

            # ---- Dispatch ----
            if not isinstance(params, dict):
                resp = err(mid, -32602, "Invalid params: expected object")
                okflag = False
                result_for_log = None
                error_for_log = "Invalid params"
            elif method == "initialize":
                result = {"serverName": "mcp-local", "protocol": "jsonrpc2"}
                resp = ok(mid, result)
                okflag = True
                result_for_log = result
                error_for_log = None
            elif method == "tools/list":
                result = REGISTRY.list_tools()
                resp = ok(mid, result)
                okflag = True
                result_for_log = result
                error_for_log = None
            elif method == "tools/call":
                name = params.get("name")
                if not name:
                    resp = err(mid, -32602, "Missing 'name' in params")
                    okflag = False
                    result_for_log = None
                    error_for_log = "Missing 'name'"
                else:
                    args = params.get("args", {}) or {}
                    try:
                        call_result = await REGISTRY.call(name, args)
                        resp = ok(mid, call_result)
                        okflag = True
                        result_for_log = call_result
                        error_for_log = None
                    except Exception as call_e:
                        tb = traceback.format_exc()
                        resp = err(mid, -32000, str(call_e), {"trace": tb})
                        okflag = False
                        result_for_log = None
                        error_for_log = str(call_e)
            elif method == "shutdown":
                result = {"ok": True}
                resp = ok(mid, result)
                okflag = True
                result_for_log = result
                error_for_log = None
            else:
                resp = err(mid, -32601, f"Method not found: {method}")
                okflag = False
                result_for_log = None
                error_for_log = "Method not found"

        except Exception as e:
            tb = traceback.format_exc()
            resp = err(msg.get("id") if 'msg' in locals() else None, -32000, str(e), {"trace": tb})
            okflag = False
            result_for_log = None
            error_for_log = str(e)

        # ---- Responder ----
        sys.stdout.buffer.write(orjson.dumps(resp, default=_json_default) + b"\n")
        sys.stdout.flush()

        # ---- Logging ----
        dur_ms = round((time.perf_counter() - t0) * 1000, 3)
        event = {
            "ts": now_iso,
            "method": method if 'method' in locals() else "<unknown>",
            "ok": okflag,
            "duration_ms": dur_ms,
        }

        # detalles útiles y redactados
        if 'params' in locals() and isinstance(params, dict):
            # para tools/call deja nombre de tool y args redacted
            if method == "tools/call":
                event["tool"] = params.get("name")
                event["args"] = _redact(params.get("args", {}))
            else:
                event["params"] = _redact(params)

        if okflag and result_for_log is not None:
            try:
                blob = orjson.dumps(result_for_log, default=_json_default)
                event["result_size"] = len(blob)
            except Exception:
                event["result_size"] = None

        if not okflag and error_for_log:
            event["error"] = error_for_log

        log_event(event)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
