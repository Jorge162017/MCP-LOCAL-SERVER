# main.py
import sys, asyncio, orjson
from src.registry import ToolRegistry
from src.tools import pdf_extract, data_profile, ts_forecast, report_generate  # + llm_chat si lo usas

REGISTRY = ToolRegistry()
REGISTRY.register(pdf_extract.tool_spec, pdf_extract.run)
REGISTRY.register(data_profile.tool_spec, data_profile.run)
REGISTRY.register(ts_forecast.tool_spec, ts_forecast.run)
REGISTRY.register(report_generate.tool_spec, report_generate.run)
# REGISTRY.register(llm_chat.tool_spec, llm_chat.run)

def _json_default(obj):
    # Convierte pandas/numpy/datetime a tipos serializables
    import datetime, numpy as np
    try:
        import pandas as pd  # disponible en tu venv
    except Exception:
        pd = None

    if pd is not None and isinstance(obj, pd.Timestamp):
        return obj.to_pydatetime().isoformat()
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        # orjson serializa datetime nativo, pero por si acaso:
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    # fallback genérico
    return str(obj)

async def ainput():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sys.stdin.buffer.readline)

async def main():
    while True:
        raw = await ainput()
        if not raw:
            break
        try:
            msg = orjson.loads(raw)
            mid = msg.get("id")
            method = msg.get("method")
            if method == "tools/list":
                resp = {"id": mid, "result": REGISTRY.list_tools()}
            elif method == "tools/call":
                params = msg.get("params", {})
                name = params.get("name")
                args = params.get("args", {})
                result = await REGISTRY.call(name, args)
                resp = {"id": mid, "result": result}
            else:
                resp = {"id": mid, "error": {"code": -32601, "message": "Method not found"}}
        except Exception as e:
            # envía error en formato JSON-RPC
            resp = {"id": msg.get("id") if 'msg' in locals() else None,
                    "error": {"code": -32000, "message": str(e)}}
        sys.stdout.buffer.write(orjson.dumps(resp, default=_json_default) + b"\n")
        sys.stdout.flush()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
