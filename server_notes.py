#!/usr/bin/env python3
# MCP Notes Server — HTTP JSON-RPC en /rpc (Starlette + Uvicorn)
from __future__ import annotations
import os, time, sqlite3, traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.requests import Request
from starlette.middleware.cors import CORSMiddleware

DB_PATH = Path(os.getenv("NOTES_DB", "notes.db")).resolve()
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "").strip()  # opcional

# ─────────────────────────── DB ───────────────────────────
def db_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    conn = db_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          text TEXT NOT NULL,
          tags TEXT DEFAULT '',
          created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        )
    """)
    conn.commit()
    conn.close()

db_init()

# ─────────────────────── JSON-RPC helpers ───────────────────────
def ok(mid, result): return {"jsonrpc":"2.0","id":mid,"result":result}
def err(mid, code, message, data=None):
    e={"code":code,"message":message}
    if data is not None: e["data"]=data
    return {"jsonrpc":"2.0","id":mid,"error":e}

def tool_text(text: str) -> Dict[str, Any]:
    return {"content":[{"type":"text","text":text}]}

def tool_data(data: Any) -> Dict[str, Any]:
    return {"content":[{"type":"json","data":data}]}

TOOLS: List[Dict[str, Any]] = [
    {
        "name":"notes_add",
        "description":"Agrega una nota de texto (tags opcional, coma separada).",
        "inputSchema":{
            "type":"object",
            "properties":{
                "text":{"type":"string"},
                "tags":{"type":"string","description":"ej: trabajo,ideas"}
            },
            "required":["text"]
        }
    },
    {
        "name":"notes_list",
        "description":"Lista notas; filtra por q (texto) o tag.",
        "inputSchema":{
            "type":"object",
            "properties":{
                "q":{"type":"string"},
                "tag":{"type":"string"}
            }
        }
    },
    {
        "name":"notes_delete",
        "description":"Elimina una nota por id.",
        "inputSchema":{
            "type":"object",
            "properties":{"id":{"type":"integer"}},
            "required":["id"]
        }
    },
    {
        "name":"notes_clear",
        "description":"Borra todas las notas.",
        "inputSchema":{"type":"object","properties":{}}
    },
    {
        "name":"notes_stats",
        "description":"Devuelve conteos y tags más comunes.",
        "inputSchema":{"type":"object","properties":{}}
    },
    {
        "name":"notes_export_md",
        "description":"Exporta todas las notas a Markdown.",
        "inputSchema":{"type":"object","properties":{}}
    },
]

# ─────────────────────── Tools impl ───────────────────────
def do_notes_add(args: Dict[str, Any]):
    text = (args.get("text") or "").strip()
    tags = (args.get("tags") or "").strip()
    if not text: return tool_text("Error: 'text' vacío")
    conn = db_conn()
    cur = conn.execute("INSERT INTO notes(text,tags) VALUES (?,?)", (text,tags))
    conn.commit()
    nid = cur.lastrowid
    conn.close()
    return tool_data({"id":nid, "text":text, "tags":tags})

def do_notes_list(args: Dict[str, Any]):
    q = (args.get("q") or "").strip()
    tag = (args.get("tag") or "").strip()
    sql = "SELECT id,text,tags,created_at FROM notes"
    params=[]
    cond=[]
    if q:
        cond.append("text LIKE ?"); params.append(f"%{q}%")
    if tag:
        cond.append("(tags LIKE ? OR ','||tags||',' LIKE ?)"); params += [f"%{tag}%", f"%,{tag},%"]
    if cond: sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY id DESC"
    conn = db_conn(); rows = conn.execute(sql, params).fetchall(); conn.close()
    data = [dict(r) for r in rows]
    return tool_data(data)

def do_notes_delete(args: Dict[str, Any]):
    nid = args.get("id")
    if not isinstance(nid, int): return tool_text("Error: 'id' debe ser integer")
    conn = db_conn(); conn.execute("DELETE FROM notes WHERE id=?", (nid,)); conn.commit(); conn.close()
    return tool_text(f"Nota {nid} eliminada")

def do_notes_clear(_):
    conn = db_conn(); conn.execute("DELETE FROM notes"); conn.commit(); conn.close()
    return tool_text("Todas las notas eliminadas")

def do_notes_stats(_):
    conn = db_conn()
    total = conn.execute("SELECT COUNT(*) c FROM notes").fetchone()["c"]
    tag_counts = {}
    for r in conn.execute("SELECT tags FROM notes").fetchall():
        tags = (r["tags"] or "").strip()
        if not tags: continue
        for t in [x.strip() for x in tags.split(",") if x.strip()]:
            tag_counts[t] = tag_counts.get(t,0)+1
    conn.close()
    return tool_data({"total":total, "tags":tag_counts})

def do_notes_export_md(_):
    conn=db_conn()
    rows = conn.execute("SELECT id,text,tags,created_at FROM notes ORDER BY id").fetchall()
    conn.close()
    lines=["# Notes export\n"]
    for r in rows:
        tags = f" _[{r['tags']}_] " if r["tags"] else ""
        lines.append(f"## #{r['id']} — {r['created_at']}{tags}\n\n{r['text']}\n")
    return tool_text("\n".join(lines))

HANDLERS = {
    "notes_add": do_notes_add,
    "notes_list": do_notes_list,
    "notes_delete": do_notes_delete,
    "notes_clear": do_notes_clear,
    "notes_stats": do_notes_stats,
    "notes_export_md": do_notes_export_md,
}

# ───────────────────── HTTP handlers ─────────────────────
async def rpc(request: Request):
    # Auth opcional
    if AUTH_TOKEN:
        auth = request.headers.get("authorization","")
        if not auth.startswith("Bearer ") or auth.split(" ",1)[1].strip()!=AUTH_TOKEN:
            return JSONResponse(err(None,-32001,"Unauthorized"), status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(err(None,-32700,"Parse error"), status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse(err(None,-32600,"Invalid Request"), status_code=400)

    mid   = payload.get("id")
    meth  = payload.get("method")
    params= payload.get("params") or {}

    t0=time.perf_counter()
    try:
        if not isinstance(params, dict):
            return JSONResponse(err(mid,-32602,"Invalid params: expected object"), status_code=400)

        if meth=="initialize":
            return JSONResponse(ok(mid, {"serverName":"mcp-notes","protocol":"jsonrpc2"}))

        elif meth=="tools/list":
            return JSONResponse(ok(mid, {"tools": TOOLS}))

        elif meth=="tools/call":
            name = params.get("name")
            if not name: return JSONResponse(err(mid,-32602,"Missing 'name'"), status_code=400)
            args = params.get("args") or params.get("arguments") or {}
            fn = HANDLERS.get(name)
            if not fn: return JSONResponse(err(mid,-32601,f"Tool not found: {name}"), status_code=404)
            try:
                result = fn(args)
                return JSONResponse(ok(mid, result))
            except Exception as e:
                tb = traceback.format_exc()
                return JSONResponse(err(mid,-32000,str(e),{"trace":tb}), status_code=500)

        elif meth=="shutdown":
            return JSONResponse(ok(mid, {"ok":True}))

        else:
            return JSONResponse(err(mid,-32601,f"Method not found: {meth}"), status_code=404)

    finally:
        dur=round((time.perf_counter()-t0)*1000,3)
        print({"ts":time.strftime("%Y-%m-%dT%H:%M:%S"),"method":meth,"ms":dur,"params":list(params) if isinstance(params,dict) else "?"}, flush=True)

async def health(_): return PlainTextResponse("ok")

routes=[
    Route("/rpc", rpc, methods=["POST"]),
    Route("/health", health, methods=["GET"]),
]
app = Starlette(routes=routes)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
