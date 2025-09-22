#!/usr/bin/env python3
# fs_mcp_local.py — MCP mínimo de Filesystem por JSON-RPC (stdin/stdout)
import sys, os, orjson, traceback
from pathlib import Path
from typing import Dict, Any

def ok(mid, result):   return {"jsonrpc": "2.0", "id": mid, "result": result}
def err(mid, code, msg, data=None):
    e = {"code": code, "message": msg}
    if data is not None: e["data"] = data
    return {"jsonrpc": "2.0", "id": mid, "error": e}

def tools_list():
    return {
        "tools": [
            {"name":"writeFile","description":"Escribe texto en archivo","input_schema":{"type":"object","properties":{"path":{"type":"string"},"text":{"type":"string"},"append":{"type":"boolean"}},"required":["path","text"]}},
            {"name":"readFile","description":"Lee archivo (texto)","input_schema":{"type":"object","properties":{"path":{"type":"string"},"max_bytes":{"type":"integer"}},"required":["path"]}},
            {"name":"makeDir","description":"Crea directorio (parents=True)","input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},
            {"name":"listDir","description":"Lista contenido de un dir","input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},
            {"name":"remove","description":"Elimina archivo o directorio vacío","input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},
        ]
    }

def call_tool(name: str, args: Dict[str, Any]):
    p = Path(args.get("path","")).expanduser().resolve()
    if name == "writeFile":
        text = args["text"]
        append = bool(args.get("append", False))
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with p.open(mode, encoding="utf-8") as f:
            f.write(text)
        return {"ok": True, "path": str(p), "bytes": len(text)}
    elif name == "readFile":
        max_bytes = int(args.get("max_bytes", 1024*1024))
        if not p.exists() or not p.is_file(): raise FileNotFoundError(str(p))
        data = p.read_text(encoding="utf-8")[:max_bytes]
        return {"ok": True, "path": str(p), "text": data, "bytes": len(data)}
    elif name == "makeDir":
        p.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": str(p)}
    elif name == "listDir":
        if not p.exists() or not p.is_dir(): raise NotADirectoryError(str(p))
        items = []
        for e in sorted(p.iterdir()):
            items.append({"name": e.name, "is_dir": e.is_dir(), "size": e.stat().st_size if e.is_file() else None})
        return {"ok": True, "path": str(p), "items": items}
    elif name == "remove":
        if p.is_file(): p.unlink()
        elif p.is_dir(): p.rmdir()  # solo si está vacío
        else: raise FileNotFoundError(str(p))
        return {"ok": True, "path": str(p)}
    else:
        raise ValueError(f"tool not found: {name}")

def main():
    # Loop JSON-RPC
    while True:
        line = sys.stdin.buffer.readline()
        if not line: break
        try:
            msg = orjson.loads(line)
            mid = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {}) or {}
            if method == "initialize":
                resp = ok(mid, {"serverName":"fs-mcp-local","protocol":"jsonrpc2"})
            elif method == "tools/list":
                resp = ok(mid, tools_list())
            elif method == "tools/call":
                name = params.get("name"); args = params.get("args",{}) or {}
                result = call_tool(name, args)
                resp = ok(mid, result)
            elif method == "shutdown":
                resp = ok(mid, {"ok": True})
            else:
                resp = err(mid, -32601, f"Method not found: {method}")
        except Exception as e:
            tb = traceback.format_exc()
            resp = err(msg.get("id") if 'msg' in locals() else None, -32000, str(e), {"trace": tb})
        sys.stdout.buffer.write(orjson.dumps(resp) + b"\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
