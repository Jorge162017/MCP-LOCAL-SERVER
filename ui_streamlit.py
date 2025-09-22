#!/usr/bin/env python3
# ui_streamlit.py — Streamlit UI para MCP local + HTTP remotos + Filesystem (MCP) + Git (MCP)
from __future__ import annotations
import os, sys, time, subprocess, shlex, asyncio, json, re
from pathlib import Path
from typing import List, Optional, Dict, Any

import streamlit as st
import orjson
import aiohttp

# ── .env ──────────────────────────────────────────────────────────────────────
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(filename=".env", usecwd=True), override=False)

# ── Groq (import tolerante) ───────────────────────────────────────────────────
try:
    from groq import Groq  # type: ignore
except Exception:
    Groq = None  # type: ignore

# ── FSClient (MCP stdio con server_cmd + sync helpers) ────────────────────────
from fs_mcp_local import FSClient


# ───────────────────────── util paths ─────────────────────────────────────────
def _find_project_root(start: Path) -> Path:
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / "main.py").exists() and (cand / "src").exists():
            return cand
    return start.parent

PROJ_ROOT = _find_project_root(Path(__file__))

# ───────────────────────── NL Helpers (FS) ────────────────────────────────────
def parse_fs_command_es(texto: str) -> List[Dict[str, Any]]:
    t = (texto or "").strip()
    tl = t.lower()
    actions: List[Dict[str, Any]] = []

    m = re.search(r'\b(listar|lista|muestra|mostrar|muéstrame)\b(?:\s+(?:el\s+directorio|carpeta))?\s*(.+)$', tl, re.I)
    if m:
        ruta = (m.group(2) or ".").strip() or "."
        return [{"op": "list", "path": ruta}]

    m = re.search(r'\b(lee|leer|abrir|abre)\b\s+(.+)$', tl, re.I)
    if m:
        return [{"op": "read", "path": m.group(2).strip()}]

    dir_name = None
    m = re.search(r'(?:carpeta|directorio)\s+(?:llamada|llamado|de\s+nombre|con\s+nombre)\s+["“]([^"”]+)["”]', t, re.I)
    if m: dir_name = m.group(1).strip()
    if not dir_name:
        m = re.search(r'(?:carpeta|directorio)\s+(?:llamada|llamado|de\s+nombre|con\s+nombre)\s+([^\s"“”]+)', t, re.I)
        if m: dir_name = m.group(1).strip()
    if not dir_name:
        m = re.search(r'(?:carpeta|directorio)\s+(?!llamada\b|llamado\b|con\s+nombre\b|de\s+nombre\b)["“]?([^\s"”]+)["”]?', t, re.I)
        if m: dir_name = m.group(1).strip()

    file_name = None
    m = re.search(r'(?:archivo|fichero)\s+["“]([^"”]+)["”]', t, re.I)
    if m:
        file_name = m.group(1).strip()
    else:
        m = re.search(r'(?:archivo|fichero)\s+([a-z0-9_\-./][^\s"]*)', t, re.I)
        if m: file_name = m.group(1).strip()

    m_cont = re.search(r'(?:que\s+diga|con\s+contenido)\s+(.+)$', t, re.I)
    content = (m_cont.group(1).strip() if m_cont else "hola")

    if dir_name:
        actions.append({"op": "mkdir", "path": dir_name})

    if file_name:
        write_path = f"{dir_name.rstrip('/')}/{file_name}" if dir_name and not file_name.startswith(dir_name.rstrip('/') + '/') else file_name
        actions.append({"op": "write", "path": write_path, "content": content})

    if actions:
        return actions

    # ← línea corregida
    m = re.search(r'\bescribe\b\s+([a-z0-9_\-./][^\s"]*)', tl, re.I)
    if m:
        return [{"op": "write", "path": m.group(1).strip(), "content": "hola"}]

    return [{"op": "unknown"}]



# ───────────────────────── Router NL → tools (LOCAL/HTTP) ─────────────────────
_SLASH = re.compile(r'^/(\w+)\b(.*)$', re.IGNORECASE)

def _parse_kv(s: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in re.finditer(r'(\w+)\s*=\s*"(.*?)"', s):
        out[m.group(1)] = m.group(2)
    for m in re.finditer(r'(\w+)\s*=\s*([^\s"]+)', s):
        k, v = m.group(1), m.group(2)
        if k in out:  # ya vino quoted
            continue
        if v.lower() in {"true", "false"}:
            out[k] = (v.lower() == "true")
        elif v.isdigit():
            out[k] = int(v)
        else:
            out[k] = v
    return out

def _safe_split_sections(s: str) -> list[str]:
    return [p.strip() for p in s.split(";") if p.strip()]

def route_mcp_intent_es(text: str) -> tuple[str, dict] | None:
    t = text.strip()
    m = _SLASH.match(t)
    if m:
        cmd, rest = m.group(1).lower(), m.group(2)
        args = _parse_kv(rest)
        if cmd == "pdf":
            args.setdefault("pages", "all")
            if "tables" in args and "extract_tables" not in args:
                args["extract_tables"] = bool(args.pop("tables"))
            return ("pdf_extract", args)
        if cmd == "profile":
            return ("data_profile", args)
        if cmd == "forecast":
            args.setdefault("date_col", "date")
            if "value" in args and "value_col" not in args:
                args["value_col"] = args.pop("value")
            args.setdefault("value_col", "value")
            args.setdefault("horizon", 6)
            args.setdefault("freq", "M")
            args.setdefault("model", "auto")
            return ("ts_forecast", args)
        if cmd == "report":
            args.setdefault("title", "Reporte")
            if "sections" in args and isinstance(args["sections"], str):
                args["sections"] = _safe_split_sections(args["sections"])
            args.setdefault("sections", ["Resumen", "Resultados", "Conclusiones"])
            args.setdefault("format", "pdf")
            return ("report_generate", args)
        return None

    t_low = t.lower()

    # pdf_extract
    if re.search(r'(extrae|saca|obt[eé]n).*(texto|tablas).*pdf', t_low):
        mpath = re.search(r'"([^"]+\.pdf)"|(?:de\s+)([^\s"“”]+\.pdf)', t, re.IGNORECASE)
        path = (mpath.group(1) or mpath.group(2)) if mpath else ""
        extract_tables = "tabla" in t_low
        pages = "all"
        mpages = re.search(r'pag(?:inas|s)?\s*(\d+(?:-\d+)?)', t_low)
        if mpages:
            r = mpages.group(1)
            if "-" in r:
                a, b = r.split("-")
                try:
                    pages = [int(a), int(b)]
                except Exception:
                    pages = "all"
            else:
                try:
                    pages = [int(r)]
                except Exception:
                    pages = "all"
        return ("pdf_extract", {"path": path, "pages": pages, "extract_tables": extract_tables})

    # data_profile
    if re.search(r'(perfil|profil|analiza).*(csv)', t_low):
        mpath = re.search(r'"([^"]+\.csv)"|(?:de\s+)([^\s"“”]+\.csv)', t, re.IGNORECASE)
        path = (mpath.group(1) or mpath.group(2)) if mpath else ""
        return ("data_profile", {"path": path, "sep": ","})

    # ts_forecast
    if re.search(r'(pron[oó]sti|forecast|predic)', t_low):
        mpath = re.search(r'"([^"]+\.csv)"|(?:de\s+)([^\s"“”]+\.csv)', t, re.IGNORECASE)
        path = (mpath.group(1) or mpath.group(2)) if mpath else ""
        args = {"path": path, "date_col": "date", "value_col": "value", "horizon": 6, "freq": "M", "model": "auto"}
        mval = re.search(r'valor\s*=\s*([A-Za-z0-9_]+)', t_low)
        if mval: args["value_col"] = mval.group(1)
        mdat = re.search(r'(fecha|date)\s*=\s*([A-Za-z0-9_]+)', t_low)
        if mdat: args["date_col"] = mdat.group(2)
        mhor = re.search(r'horiz(?:onte)?\s*=\s*(\d+)', t_low)
        if mhor: args["horizon"] = int(mhor.group(1))
        if "diari" in t_low: args["freq"] = "D"
        if "seman" in t_low: args["freq"] = "W"
        if "mensu" in t_low: args["freq"] = "M"
        return ("ts_forecast", args)

    # report_generate
    if re.search(r'(genera|crea|haz).*(reporte|informe)', t_low):
        msecs = re.search(r'secciones?\s*:\s*"([^"]+)"', t, re.IGNORECASE)
        sections = _safe_split_sections(msecs.group(1)) if msecs else ["Resumen ejecutivo", "Resultados", "Conclusiones"]
        fmt = "pdf" if "pdf" in t_low else ("html" if "html" in t_low else "pdf")
        mtit = re.search(r't[íi]tulo\s*:\s*"([^"]+)"', t, re.IGNORECASE)
        title = mtit.group(1) if mtit else "Reporte"
        return ("report_generate", {"title": title, "sections": sections, "format": fmt})

    return None


# ───────────────────────── Git NL helpers ─────────────────────────────────────
def parse_git_command_es(texto: str) -> list[dict]:
    """
    Devuelve una lista de pasos para mcp-server-git SIN default.
    Si no reconoce el mensaje, devuelve lista vacía para permitir fallback a chat.
    """
    t = texto.strip().lower()
    steps: list[dict] = []

    if re.search(r"\b(status|estado)\b", t):
        return [{"tool": "git_status", "args": {}}]
    if re.search(r"\b(ramas|branches)\b", t):
        return [{"tool": "git_branch", "args": {}}]
    if re.search(r"\b(init|inicializa)\b", t):
        return [{"tool": "git_init", "args": {}}]

    m = re.search(r"crea(?:r)?\s+ram[ao]\s+([a-z0-9_\-\/\.]+)(?:\s+(?:desde|from)\s+([a-z0-9_\-\/\.]+))?", t)
    if m:
        name, base = m.group(1), m.group(2)
        args = {"name": name}
        if base: args["base"] = base
        steps.append({"tool": "git_create_branch", "args": args})

    m = re.search(r"(?:cámbiate|cambiar|checkout)\s+(?:a\s+ram[ao]\s+)?([a-z0-9_\-\/\.]+)", t)
    if m:
        steps.append({"tool": "git_checkout", "args": {"name": m.group(1)}})

    if re.search(r"\b(agrega|añade|add)\b.*\b(todo|all)\b", t):
        steps.append({"tool": "git_add", "args": {"paths": ["."]}})
    else:
        m = re.search(r"(?:agrega|añade|add)\s+(.+)", t)
        if m:
            paths = [p for p in re.split(r"\s+", m.group(1).strip()) if p]
            steps.append({"tool": "git_add", "args": {"paths": paths}})

    m = re.search(r"(?:commit|haz\s+commit).*(?:\"([^\"]+)\"|'([^']+)')", t)
    if not m:
        m = re.search(r"(?:commit|haz\s+commit)\s+mensaje\s+(.+)$", t)
    if m:
        msg = (m.group(1) or m.group(2) or m.group(0)).strip()
        steps.append({"tool": "git_commit", "args": {"message": msg}})

    if re.search(r"\b(reset|unstage)\b", t):
        steps.append({"tool": "git_reset", "args": {}})

    m = re.search(r"\b(?:log|historial|commits)\b\s*(\d{1,3})?", t)
    if m:
        n = m.group(1)
        steps.append({"tool": "git_log", "args": {"max_count": int(n)} if n else {"max_count": 10}})

    if re.search(r"\b(sin\s+preparar|unstaged)\b", t):
        steps.append({"tool": "git_diff_unstaged", "args": {}})
    elif re.search(r"\b(staged|en\s+staging)\b", t):
        steps.append({"tool": "git_diff_staged", "args": {}})
    else:
        m = re.search(r"diff\s+([^\s]+)\.\.([^\s]+)", t)
        if m:
            steps.append({"tool": "git_diff", "args": {"ref1": m.group(1), "ref2": m.group(2)}})

    m = re.search(r"(?:muestra|show)\s+(?:commit\s+)?([0-9a-f]{6,40})", t)
    if m:
        steps.append({"tool": "git_show", "args": {"rev": m.group(1)}})

    # NO default aquí: si no hay match, devolver lista vacía para caer al chat
    return steps


# ───────────────────────── JSON-RPC (stdio/local) ─────────────────────────────
def _send(proc, payload: dict):
    proc.stdin.write(orjson.dumps(payload) + b"\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        err = ""
        try:
            err = proc.stderr.read().decode() if proc.stderr else ""
        except Exception:
            pass
        raise RuntimeError(f"Servidor MCP no respondió (STDOUT vacío). {err}")
    return orjson.loads(line)

def rpc_call_stdio(proc, method: str, params: dict | None = None, mid: int = 1):
    payload = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        payload["params"] = params
    return _send(proc, payload)

def call_tool_stdio(proc, name: str, args: dict, mid: int):
    return rpc_call_stdio(proc, "tools/call", {"name": name, "args": args}, mid)

# ───────────────────────── JSON-RPC (HTTP) ────────────────────────────────────
async def http_rpc(url: str, payload: dict, bearer: Optional[str] = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    async with aiohttp.ClientSession(headers=headers) as sess:
        async with sess.post(url, json=payload, timeout=300) as resp:
            text = await resp.text()
            return orjson.loads(text)

# ───────────────────────── Estado ─────────────────────────────────────────────
def _init_state():
    ss = st.session_state
    ss.setdefault("proc", None)
    ss.setdefault("mid", 10)
    ss.setdefault("history", [])
    ss.setdefault("temperature", float(os.getenv("LLM_TEMPERATURE", "0.1")))
    ss.setdefault("max_tokens", int(os.getenv("LLM_MAX_TOKENS", "120")))
    ss.setdefault("rpc_mode", "local")  # local | http1 | http2 | fs | git
    ss.setdefault("remote1_url", "http://127.0.0.1:8787/rpc")
    ss.setdefault("remote1_token", "")
    ss.setdefault("remote2_url", "http://127.0.0.1:8788/rpc")
    ss.setdefault("remote2_token", "")
    ss.setdefault("local_cmd", f"{sys.executable} {str(PROJ_ROOT / 'main.py')}")
    ss.setdefault("local_cwd", str(PROJ_ROOT))
    ss.setdefault("fs_client", None)
    ss.setdefault("fs_root", str(PROJ_ROOT))
    ss.setdefault("fs_started", False)
    ss.setdefault("git_client", None)
    ss.setdefault("git_started", False)
    ss.setdefault("git_root", str(PROJ_ROOT))
    ss.setdefault("git_repo", ss["git_root"])
    ss.setdefault("_groq_client", None)

def S():
    _init_state()
    return st.session_state

# ───────────────────────── Control server local ───────────────────────────────
def _launch_process(cmd_line: str, cwd: str | None) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(PROJ_ROOT)}
    if os.name == "nt":
        popen_args = dict(args=cmd_line, shell=True)
    else:
        try:
            popen_args = dict(args=shlex.split(cmd_line), shell=False)
        except Exception:
            popen_args = dict(args=cmd_line, shell=True)
    return subprocess.Popen(
        **popen_args, cwd=cwd or str(PROJ_ROOT),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=False, bufsize=0, env=env,
    )

def start_server_local():
    s = S()
    if s.proc and s.proc.poll() is None:
        return
    s.proc = _launch_process(s.local_cmd, s.local_cwd)
    time.sleep(0.15)
    try:
        rpc_call_stdio(s.proc, "initialize", {"client": "streamlit-ui"}, mid=0)
    except Exception:
        pass

def stop_server_local():
    s = S()
    if s.proc and s.proc.poll() is None:
        try:
            rpc_call_stdio(s.proc, "shutdown", mid=999)
        except Exception:
            pass
        try:
            s.proc.terminate()
        except Exception:
            pass
    s.proc = None
    s.history = []

def local_running() -> bool:
    s = S()
    return bool(s.proc and s.proc.poll() is None)

# ───────────────────────── Filesystem MCP (SYNC) ──────────────────────────────
def fs_running() -> bool:
    return bool(S().fs_started and S().fs_client)

def start_fs():
    s = S()
    if s.fs_client is None:
        s.fs_client = FSClient(
            root=s.fs_root,
            server_cmd=["npx", "-y", "@modelcontextprotocol/server-filesystem", s.fs_root],
        )
    s.fs_client.start_sync()
    s.fs_started = True

def stop_fs():
    s = S()
    if s.fs_client is None:
        s.fs_started = False
        return
    s.fs_client.stop_sync()
    s.fs_started = False

# ───────────────────────── Git MCP (PYTHON) ───────────────────────────────────
def git_running() -> bool:
    return bool(S().git_started and S().git_client)

def start_git():
    s = S()
    cmd = [sys.executable, "-m", "mcp_server_git", "--repository", s.git_repo]
    if s.git_client is None:
        s.git_client = FSClient(root=s.git_repo, server_cmd=cmd)
    s.git_client.start_sync()
    s.git_started = True

def stop_git():
    s = S()
    if s.git_client is None:
        s.git_started = False
        return
    s.git_client.stop_sync()
    s.git_started = False

# ───────────────────────── Wrappers RPC ───────────────────────────────────────
def _current_http_conf() -> tuple[str, Optional[str]]:
    s = S()
    if s.rpc_mode == "http1":
        return s.remote1_url.strip(), (s.remote1_token.strip() or None)
    elif s.rpc_mode == "http2":
        return s.remote2_url.strip(), (s.remote2_token.strip() or None)
    return "", None

def rpc_initialize() -> dict:
    s = S()
    if s.rpc_mode == "local":
        try:
            return rpc_call_stdio(s.proc, "initialize", {"client": "streamlit-ui"}, mid=0)
        except Exception:
            return {"result": {"serverName": "mcp-local", "protocol": "jsonrpc2"}}
    url, tok = _current_http_conf()
    payload = {"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {"client": "streamlit-ui"}}
    return asyncio.run(http_rpc(url, payload, tok))

def rpc_tools_list() -> list[dict]:
    s = S()
    if s.rpc_mode == "local":
        res = rpc_call_stdio(s.proc, "tools/list", mid=1)
        return res["result"]["tools"]
    url, tok = _current_http_conf()
    res = asyncio.run(http_rpc(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, tok))
    return res["result"]["tools"]

def rpc_tools_call(name: str, args: dict) -> dict:
    s = S()
    if s.rpc_mode == "local":
        res = call_tool_stdio(s.proc, name, args, mid=s.mid)
        s.mid += 1
        if "error" in res:
            raise RuntimeError(res["error"].get("message"))
        return res["result"]
    url, tok = _current_http_conf()
    payload = {"jsonrpc": "2.0", "id": s.mid, "method": "tools/call", "params": {"name": name, "args": args}}
    s.mid += 1
    res = asyncio.run(http_rpc(url, payload, tok))
    if "error" in res:
        raise RuntimeError(res["error"].get("message"))
    return res["result"]

# ───────────────────────── Chat helpers (server llm_chat) ─────────────────────
def build_prompt(user_msg: str, max_chars: int = 4000) -> str:
    s = S()
    lines: List[str] = []
    for role, text in s.history:
        lines.append(f"{role.upper()}: {text.strip()}")
    lines.append(f"USER: {user_msg.strip()}")
    prompt = "\n".join(lines)
    if len(prompt) > max_chars:
        prompt = prompt[-max_chars:]
        i = prompt.find("\n")
        if i > 0:
            prompt = prompt[i + 1 :]
    return prompt

def chat_llm(user_msg: str) -> str:
    s = S()
    if s.rpc_mode == "local" and not local_running():
        raise RuntimeError("Servidor MCP local no está corriendo")
    s.history.append(("user", user_msg))
    out = rpc_tools_call("llm_chat", {"prompt": build_prompt(user_msg), "temperature": float(s.temperature), "max_tokens": int(s.max_tokens)})
    text = (out.get("text") or "").strip() or "(respuesta vacía)"
    s.history.append(("assistant", text))
    return text

# ───────────────────────── Tools awareness ────────────────────────────────────
def get_connected_tools_list() -> list[dict]:
    mode = S().rpc_mode
    try:
        if mode in ("local", "http1", "http2"):
            return rpc_tools_list()
        if mode == "fs" and fs_running():
            return S().fs_client.tools_list_sync()
        if mode == "git" and git_running():
            return S().git_client.tools_list_sync()
    except Exception:
        return []
    return []

def format_tools_brief(tools: list[dict]) -> str:
    if not tools:
        return "No detecté tools publicadas por el servidor actual."
    lines = []
    for t in tools[:50]:
        name = t.get("name") or "—"
        desc = (t.get("description") or "").strip()
        lines.append(f"- **{name}**" + (f" — {desc}" if desc else ""))
    return "\n".join(lines)

def is_tools_query(text: str) -> bool:
    s = (text or "").lower()
    return any(k in s for k in ["que tools", "qué tools", "que herramientas", "qué herramientas", "tools tienes", "lista tools", "list tools", "tools/list", "tools?"])

# ───────────────────────── Chat cliente (Groq con contexto) ───────────────────
DEFAULT_GROQ_CANDIDATES = [
    os.getenv("CLIENT_GROQ_MODEL", "").strip() or "llama-3.3-70b-versatile",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]

def _history_to_messages(system_prompt: str | None = None) -> list[dict]:
    s = S()
    msgs: list[dict] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    for role, text in s.history:
        msgs.append({"role": "user" if role == "user" else "assistant", "content": text})
    return msgs

def client_llm_chat(user_msg: str) -> str:
    """
    Chat directo con Groq cuando el destino no expone llm_chat.
    Incluye el contexto del server y sus tools para evitar alucinaciones.
    """
    s = S()
    if Groq is None:
        raise RuntimeError("Falta el SDK de Groq. Instala con: pip install groq")

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Falta GROQ_API_KEY en tu .env")

    client = Groq(api_key=api_key)

    tools_ctx = get_connected_tools_list()
    tools_names = ", ".join([t.get("name", "?") for t in tools_ctx]) if tools_ctx else "(sin tools detectadas)"
    base_system = os.getenv("CLIENT_LLM_SYSTEM", "Eres un asistente útil que responde en español con precisión.")
    system_prompt = (
        f"{base_system}\n"
        f"Contexto:\n"
        f"- Destino actual: {s.rpc_mode}\n"
        f"- Tools disponibles: {tools_names}\n"
        f"Reglas:\n"
        f"- Si el usuario pide las herramientas disponibles, responde EXACTAMENTE con esa lista.\n"
        f"- No inventes herramientas.\n"
    )

    msgs = _history_to_messages(system_prompt)

    last_err = None
    tried = []
    for model in [m for i, m in enumerate(DEFAULT_GROQ_CANDIDATES) if m and m not in DEFAULT_GROQ_CANDIDATES[:i]]:
        tried.append(model)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=msgs,
                temperature=float(s.temperature),
                max_tokens=int(s.max_tokens),
            )
            text = (resp.choices[0].message.content or "").strip() or "(respuesta vacía)"
            s.history.append(("assistant", text))
            s["__client_llm_model_used__"] = model
            return text
        except Exception as e:
            msg = str(e).lower()
            if ("decommissioned" in msg or "no longer supported" in msg
                or "unrecognized" in msg or "does not exist" in msg
                or "invalid_request_error" in msg):
                last_err = e
                continue
            raise

    raise RuntimeError("No se pudo usar ningún modelo Groq. Probé: " + ", ".join(tried)) from last_err

# ───────────────────────── Ejecutores NL FS/Git ───────────────────────────────
def run_fs_nl(msg: str) -> tuple[str, list[tuple[str, str, Any]]]:
    if not fs_running():
        raise RuntimeError("FS MCP no está corriendo")
    plan = parse_fs_command_es(msg)
    results: list[tuple[str, str, Any]] = []
    if not plan or plan[0].get("op") == "unknown":
        return ("__unknown__", results)
    for step in plan:
        op   = step.get("op")
        path = step.get("path")
        if op == "mkdir":
            res = S().fs_client.create_dir_sync(path)
            results.append(("mkdir", path, res))
        elif op == "write":
            content = step.get("content", "")
            res = S().fs_client.write_file_sync(path, content)
            results.append(("write", path, {"preview": content, "raw": res}))
        elif op == "list":
            res = S().fs_client.list_dir_sync(path)
            results.append(("list", path, res))
        elif op == "read":
            txt = S().fs_client.read_file_sync(path)
            results.append(("read", path, txt))
    return ("ok", results)

def run_git_nl(msg: str) -> tuple[str, list[str]]:
    """
    Ejecuta comandos Git derivados del NL. Si el mensaje NO es un comando Git,
    devuelve "__unknown__", [] para permitir el fallback a chat Groq.
    """
    if not git_running():
        raise RuntimeError("Git MCP no está corriendo")
    plan = parse_git_command_es(msg)
    if not plan:  # ← sin match → usa chat Groq en el caller
        return ("__unknown__", [])
    repo = getattr(S(), "git_root", str(PROJ_ROOT))
    steps_exec: list[str] = []
    for step in plan:
        args = dict(step.get("args", {}))
        args.setdefault("repo_path", repo)
        S().git_client.call_tool_sync(step["tool"], args)
        steps_exec.append(step["tool"])
    return ("ok", steps_exec)


# ───────────────────────── UI ─────────────────────────────────────────────────
st.set_page_config(page_title="MCP Local — Streamlit UI", page_icon="🤖", layout="wide")
st.title("MCP Servers")

with st.sidebar:
    st.subheader("Servidor")

    options = ["Local (main.py)", "HTTP remoto A", "HTTP remoto B", "Filesystem (MCP)", "Git (MCP)"]
    mode = st.radio(
        "Destino",
        options,
        index=options.index(
            {
                "local": "Local (main.py)",
                "http1": "HTTP remoto A",
                "http2": "HTTP remoto B",
                "fs": "Filesystem (MCP)",
                "git": "Git (MCP)",
            }[S().rpc_mode]
        ),
    )
    S().rpc_mode = {
        "Local (main.py)": "local",
        "HTTP remoto A": "http1",
        "HTTP remoto B": "http2",
        "Filesystem (MCP)": "fs",
        "Git (MCP)": "git",
    }[mode]

    if S().rpc_mode == "local":
        S().local_cmd = st.text_input("Comando (local stdio)", S().local_cmd)
        S().local_cwd = st.text_input("CWD", S().local_cwd)

        colA, colB = st.columns(2)
        if colA.button("Iniciar", use_container_width=True):
            try:
                start_server_local()
                st.success("Servidor iniciado")
                try:
                    st.session_state["_tools_cache"] = rpc_tools_list()
                except Exception as e:
                    err = ""
                    try:
                        err = S().proc.stderr.read().decode(errors="ignore")
                    except Exception:
                        pass
                    st.error(str(e))
                    if err.strip():
                        with st.expander("Ver STDERR del servidor"):
                            st.code(err.strip())
            except Exception as e:
                err = ""
                try:
                    err = S().proc.stderr.read().decode(errors="ignore")
                except Exception:
                    pass
                st.error(f"No se pudo iniciar: {e}")
                if err.strip():
                    with st.expander("Ver STDERR del servidor"):
                        st.code(err.strip())

        if colB.button("Detener", use_container_width=True):
            stop_server_local()
            st.info("Servidor detenido")

    elif S().rpc_mode == "http1":
        S().remote1_url = st.text_input("URL RPC (Remoto A)", S().remote1_url, placeholder="http://127.0.0.1:8787/rpc")
        S().remote1_token = st.text_input("Bearer (opcional)", S().remote1_token, type="password")
        if st.button("Probar conexión (A)"):
            try:
                res = rpc_initialize()
                st.success(f"OK: {res['result'].get('serverName','?')} ({res['result'].get('protocol','?')})")
            except Exception as e:
                st.error(str(e))

    elif S().rpc_mode == "http2":
        S().remote2_url = st.text_input("URL RPC (Remoto B)", S().remote2_url, placeholder="http://127.0.0.1:8788/rpc")
        S().remote2_token = st.text_input("Bearer (opcional)", S().remote2_token, type="password")
        if st.button("Probar conexión (B)"):
            try:
                res = rpc_initialize()
                st.success(f"OK: {res['result'].get('serverName','?')} ({res['result'].get('protocol','?')})")
            except Exception as e:
                st.error(str(e))

    elif S().rpc_mode == "fs":
        S().fs_root = st.text_input("Root expuesto por FS", S().fs_root)
        col1, col2 = st.columns(2)
        if col1.button("Iniciar FS", use_container_width=True):
            try:
                start_fs()
                st.success(f"FS server iniciado (root={S().fs_root})")
            except Exception as e:
                st.error(f"No se pudo iniciar FS: {e}")
        if col2.button("Detener FS", use_container_width=True):
            try:
                stop_fs()
                st.info("FS detenido")
            except Exception as e:
                st.error(str(e))

    else:  # Git
        S().git_root = st.text_input("Ruta del repo (local)", getattr(S(), "git_root", str(PROJ_ROOT)), help="Debe contener .git")
        col1, col2 = st.columns(2)
        if col1.button("Iniciar Git", use_container_width=True):
            try:
                start_git()
                st.success(f"Git server iniciado (repo={S().git_repo})")
            except Exception as e:
                st.error(f"Git server no pudo iniciar: {e}")
        if col2.button("Detener Git", use_container_width=True):
            try:
                stop_git()
                st.info("Git detenido")
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.subheader("Parámetros LLM")
    s = S()
    s.temperature = st.number_input("temperature", min_value=0.0, max_value=2.0, step=0.1, value=float(s.temperature))
    s.max_tokens = st.number_input("max_tokens", min_value=1, step=1, value=int(s.max_tokens))

    st.divider()
    if st.button("Listar tools (servidor LOCAL/HTTP)"):
        try:
            st.session_state["_tools_cache"] = rpc_tools_list()
            st.success("Tools actualizadas.")
        except Exception as e:
            st.error(str(e))
            if S().rpc_mode == "local" and S().proc:
                err = ""
                try:
                    err = S().proc.stderr.read().decode(errors="ignore")
                except Exception:
                    pass
                if err.strip():
                    with st.expander("Ver STDERR del servidor"):
                        st.code(err.strip())

estado = (
    "Corriendo ✅"
    if (
        (S().rpc_mode == "local" and local_running())
        or (S().rpc_mode in {"http1", "http2"})
        or (S().rpc_mode == "fs" and fs_running())
        or (S().rpc_mode == "git" and git_running())
    )
    else "Detenido ⛔"
)
st.caption(f"Estado: **{estado}**")

# ─── Tabs ───────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔧 Tools", "💬 Chat", "🧪 Tool Call", "📁 Filesystem", "🪵 Git"])

with tab1:
    tools = st.session_state.get("_tools_cache")
    if tools:
        for t in tools:
            st.markdown(f"- **{t['name']}** — {t.get('description','')}")
    else:
        st.info("Pulsa *Listar tools (servidor LOCAL/HTTP)* en la barra lateral.")

with tab2:
    st.markdown("Chat + ejecución automática de tools (usa NL para PDF/CSV/Forecast/Report y chat Groq si el destino no tiene llm_chat).")
    if S().rpc_mode == "local" and not local_running():
        st.warning("Inicia el servidor local o elige un remoto.")
    else:
        msg = st.text_area(
            "Mensaje",
            "",
            placeholder=(
                'Ejemplos (LOCAL/HTTP): extrae texto del pdf "/ruta/doc.pdf" • perfil csv "/ruta/data.csv" • '
                'pronóstico de "/ruta/data.csv" valor=ventas fecha=ds • genera un reporte pdf título:"Demo" '
                '• (FS) "crea carpeta demo y escribe demo/hola.txt que diga hola mundo" '
                '• (Git) "status", "crea rama feat/x desde main", "commit \\"msg\\""'
            ),
            height=120,
        )
        col_send, col_clear = st.columns(2)

        if col_send.button("Enviar", type="primary"):
            if not msg.strip():
                st.warning("Escribe un mensaje.")
            else:
                try:
                    mode = S().rpc_mode
                    S().history.append(("user", msg))

                    # 1) Pregunta por tools → responder con lista real (sin LLM)
                    if is_tools_query(msg):
                        tools = get_connected_tools_list()
                        text = format_tools_brief(tools)
                        st.success("Tools del servidor conectado")
                        st.markdown(text)
                        S().history.append(("assistant", text))
                    else:
                        # 2) Modo FS
                        if mode == "fs":
                            status, results = run_fs_nl(msg)
                            if status == "__unknown__":
                                out = client_llm_chat(msg)
                                st.info("FS: no se detectó comando NL; usé chat Groq.")
                                st.success("Respuesta"); st.write(out)
                            else:
                                st.success("✅ Ejecutado (FS)")
                                summary = [f"{k} {p}" for k, p, _ in results]
                                st.write("FS: " + " → ".join(summary))

                        # 3) Modo Git
                        elif mode == "git":
                            status, steps = run_git_nl(msg)
                            if not steps:
                                out = client_llm_chat(msg)
                                st.info("Git: no se detectó comando NL; usé chat Groq.")
                                st.success("Respuesta"); st.write(out)
                            else:
                                st.success("✅ Ejecutado (Git)")
                                st.write("Git: " + " → ".join(steps))

                        # 4) LOCAL/HTTP
                        else:
                            routed = route_mcp_intent_es(msg)
                            if routed:
                                tool_name, tool_args = routed
                                res = rpc_tools_call(tool_name, tool_args)
                                st.success(f"✅ Ejecutado: {tool_name}")
                                with st.expander("Ver args enviados"): st.json(tool_args)
                                st.json(res)
                                S().history.append(("assistant", f"Ejecuté `{tool_name}` con args {tool_args}"))
                            else:
                                tools_cache = st.session_state.get("_tools_cache") or rpc_tools_list()
                                has_llm = any(t.get("name") == "llm_chat" for t in tools_cache)
                                if has_llm:
                                    out = chat_llm(msg)
                                    st.success("Respuesta"); st.write(out)
                                else:
                                    out = client_llm_chat(msg)
                                    st.info("El destino no tiene 'llm_chat'; usé chat Groq (cliente).")
                                    st.success("Respuesta"); st.write(out)
                                used = S().get("__client_llm_model_used__")
                                if used: st.caption(f"Groq (cliente) • modelo: **{used}**")

                except Exception as e:
                    st.error(str(e))

        if col_clear.button("Limpiar historial"):
            S().history = []
            st.info("Historial limpiado.")

        st.markdown("### Historial")
        for role, text in S().history[-20:]:
            st.markdown(f"**{role.upper()}:** {text}")

        st.caption("Ayuda de comandos (slash + lenguaje natural)")
        with st.expander("Ver ayuda rápida"):
            st.markdown("""
**Natural**:
- "extrae texto del pdf \"/ruta/doc.pdf\"" → pdf_extract
- "extrae tablas del pdf \"/ruta/doc.pdf\" páginas 1-3" → pdf_extract
- "perfil csv \"/ruta/data.csv\"" → data_profile
- "pronóstico de \"/ruta/data.csv\" valor=ventas fecha=ds horizonte=12 mensual" → ts_forecast
- "genera un reporte pdf título:\"Mi Informe\" secciones:\"Resumen;Resultados;Conclusiones\"" → report_generate
**Slash**:
- `/pdf path="..." pages=all tables=true`
- `/profile path="..."`
- `/forecast path="..." date="date" value="value" horizon=6 freq="M"`
- `/report title="..." sections="A;B;C" format="pdf"`
""")

with tab3:
    st.markdown("Ejecuta cualquier tool con argumentos JSON en el servidor seleccionado (LOCAL/HTTP).")

    tools = st.session_state.get("_tools_cache")
    if tools is None:
        try:
            tools = rpc_tools_list()
            st.session_state["_tools_cache"] = tools
        except Exception as e:
            st.error(f"No pude listar tools: {e}")
            tools = []

    tool_names = [t.get("name", "") for t in tools if t.get("name")]

    if not tool_names:
        st.info("No hay tools cargadas. Pulsa **Listar tools** en la barra lateral.")
    else:
        prev_name = st.session_state.get("tool_sel_name")
        start_idx = tool_names.index(prev_name) if prev_name in tool_names else 0

        sel_name = st.selectbox("Nombre de la tool", tool_names, index=start_idx, key="tool_sel_name")
        sel_tool = next((t for t in tools if t.get("name") == sel_name), {})
        st.caption(sel_tool.get("description", ""))

        schema = sel_tool.get("input_schema") or {}
        if schema:
            with st.expander("Ver esquema de entrada (JSON Schema)"):
                st.json(schema)

        if "tool_args_txt" not in st.session_state:
            props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
            example_args = {k: "" for k in props.keys()} if props else {}
            st.session_state["tool_args_txt"] = orjson.dumps(example_args).decode("utf-8")

        args_txt = st.text_area("Args (JSON)", st.session_state.get("tool_args_txt", "{}"), key="tool_args_txt")

        cols = st.columns([1, 1, 2])
        if cols[0].button("Ejecutar tool", type="primary"):
            try:
                args = json.loads(args_txt or "{}")
            except Exception as e:
                st.error(f"JSON inválido: {e}")
            else:
                try:
                    out = rpc_tools_call(sel_name, args)
                    st.success("OK"); st.json(out)
                except Exception as e:
                    st.error(str(e))

        if cols[1].button("↺ Resetear selección"):
            for k in ("tool_sel_name", "tool_args_txt"):
                st.session_state.pop(k, None)
            st.rerun()

with tab4:
    st.markdown("Operaciones vía **@modelcontextprotocol/server-filesystem**.")
    if S().rpc_mode != "fs":
        st.info("Selecciona *Filesystem (MCP)* en la barra lateral.")
    elif not fs_running():
        st.warning("Inicia el servidor FS.")
    else:
        path = st.text_input("Ruta", ".")
        colA, colB, colC = st.columns(3)

        if colA.button("Listar directorio"):
            try:
                items = S().fs_client.list_dir_sync(path)
                st.success("OK"); st.json(items)
            except Exception as e:
                st.error(str(e))

        file_to_read = st.text_input("Archivo a leer", "README.md")
        if colB.button("Leer archivo"):
            try:
                text = S().fs_client.read_file_sync(file_to_read)
                st.success("OK"); st.code(text or "(vacío)")
            except Exception as e:
                st.error(str(e))

        file_to_write = st.text_input("Archivo a escribir", "mcp_demo.txt")
        content = st.text_area("Contenido", "Hello from MCP Filesystem 👋")
        if colC.button("Escribir archivo"):
            try:
                res = S().fs_client.write_file_sync(file_to_write, content)
                st.success("OK"); st.json(res)
            except Exception as e:
                st.error(str(e))

        st.divider()
        st.markdown("### Crear carpeta")
        new_dir = st.text_input("Nombre de carpeta", "demo_folder")
        if st.button("Crear carpeta"):
            try:
                res = S().fs_client.create_dir_sync(new_dir)
                st.success("OK"); st.json(res)
            except Exception as e:
                st.error(str(e))

        st.divider()
        st.markdown("### Tools del servidor FS")
        if st.button("Ver tools del servidor"):
            try:
                tools_fs = S().fs_client.tools_list_sync()
                st.success("Tools detectadas")
                for t in tools_fs:
                    st.write(f"- **{t.get('name')}** — {t.get('description','')}")
            except Exception as e:
                st.error(str(e))

        st.divider()
        st.markdown("### ⚡ Comando en lenguaje natural (FS)")
        nl_txt = st.text_input("Ejemplo: crea una carpeta demo y dentro un archivo hola.txt que diga hola mundo",
                               value="crea una carpeta demo y dentro un archivo hola.txt que diga hola mundo")
        if st.button("Ejecutar comando FS"):
            try:
                plan = parse_fs_command_es(nl_txt)
                if not isinstance(plan, list):
                    plan = [plan]

                if not plan or plan[0].get("op") == "unknown":
                    st.info("No entendí. Ejemplos:\n- **listar .**\n- **leer README.md**\n- **crear carpeta demo**\n- **escribir demo/hola.txt que diga hola mundo**")
                else:
                    results = []
                    for step in plan:
                        op   = step.get("op")
                        path = step.get("path")

                        if op == "mkdir":
                            res = S().fs_client.create_dir_sync(path)
                            results.append(("mkdir", path, res))
                        elif op == "write":
                            content = step.get("content", "")
                            res = S().fs_client.write_file_sync(path, content)
                            results.append(("write", path, {"preview": content, "raw": res}))
                        elif op == "list":
                            res = S().fs_client.list_dir_sync(path)
                            results.append(("list", path, res))
                        elif op == "read":
                            txt = S().fs_client.read_file_sync(path)
                            results.append(("read", path, txt))
                        else:
                            results.append(("unknown", path, step))

                    st.success("Comando ejecutado ✅")
                    for kind, path, res in results:
                        if path: st.markdown(f"**{kind}** → `{path}`")
                        if kind == "read":
                            st.code(res or "", language="text")
                        elif kind == "list":
                            st.json(res)
                        elif kind == "write":
                            st.markdown("**Contenido guardado (preview):**")
                            st.code((res.get("preview","")), language="text")
                            with st.expander("Raw"): st.json(res.get("raw"))

            except Exception as e:
                st.error("Ocurrió un error al ejecutar el comando.")
                with st.expander("Detalle"): st.json({"error": str(e)})

with tab5:
    st.markdown("Operaciones vía **mcp-server-git** (Python).")
    if S().rpc_mode != "git":
        st.info("Selecciona *Git (MCP)* en la barra lateral.")
    elif not git_running():
        st.warning("Inicia el servidor Git.")
    else:
        repo = getattr(S(), "git_root", str(PROJ_ROOT))

        colGT1, colGT2 = st.columns(2)
        if colGT1.button("Cargar tools (Git)"):
            try:
                tools_git = S().git_client.tools_list_sync()
                st.session_state["_git_tools_cache"] = tools_git
                st.success(f"{len(tools_git)} tool(s) detectadas")
                for t in tools_git:
                    st.write(f"- **{t.get('name')}** — {t.get('description','')}")
            except Exception as e:
                st.error(str(e))

        st.divider()
        st.markdown("### Ejecutar tool (Git)")
        tools_git = st.session_state.get("_git_tools_cache", [])
        tool_names = [t.get("name", "") for t in tools_git if t.get("name")]
        default_name = tool_names[0] if tool_names else "git_status"

        name_git = st.text_input("Nombre de la tool (Git)", default_name)
        args_git_txt = st.text_area("Args (JSON)", "{}")

        if colGT2.button("Ejecutar tool (Git)"):
            try:
                args_git = json.loads(args_git_txt or "{}")
                if isinstance(args_git, dict) and "repo_path" not in args_git:
                    args_git["repo_path"] = repo
            except Exception as e:
                st.error(f"JSON inválido: {e}")
            else:
                try:
                    out = S().git_client.call_tool_sync(name_git, args_git)
                    st.success("OK"); st.json(out)
                except Exception as e:
                    st.error(str(e))

        st.divider()
        st.markdown("### ⚡ Comando en lenguaje natural (Git)")
        git_nl = st.text_input(
            "Ejemplos: 'status', 'crea rama feat/x desde main', 'checkout feat/x', "
            "'agrega todo', 'commit \"primer commit\"', 'log 5', 'diff main..feat/x', 'show abc1234'",
            value="status",
        )

        if st.button("Ejecutar comando (Git)"):
            try:
                plan = parse_git_command_es(git_nl)
                if not plan:
                    st.info("No se detectó comando Git. Escribe un comando o usa el chat en la pestaña 💬.")
                else:
                    st.caption("Plan: " + " → ".join([p["tool"] for p in plan]))
                    for i, step in enumerate(plan, 1):
                        args = dict(step.get("args", {}))
                        if "repo_path" not in args:
                            args["repo_path"] = repo
                        st.markdown(f"**Paso {i}:** `{step['tool']}`  \nArgs: `{args}`")
                        res = S().git_client.call_tool_sync(step["tool"], args)
                        with st.expander("Detalle de respuesta"): st.json(res)
                    st.success("Comando Git completado ✅")
            except Exception as e:
                st.error(str(e))

        st.divider()
        st.markdown("### Accesos rápidos")
        q1, q2, q3, q4 = st.columns(4)
        if q1.button("Status"):
            try: st.json(S().git_client.call_tool_sync("git_status", {"repo_path": repo}))
            except Exception as e: st.error(str(e))
        if q2.button("Ramas"):
            try: st.json(S().git_client.call_tool_sync("git_branch", {"repo_path": repo}))
            except Exception as e: st.error(str(e))
        commit_msg = q3.text_input("Commit msg", key="git_quick_commit_msg")
        if q4.button("Commit (staged)"):
            if commit_msg.strip():
                try:
                    st.json(S().git_client.call_tool_sync("git_commit", {"repo_path": repo, "message": commit_msg.strip()}))
                    st.success("Commit realizado")
                except Exception as e:
                    st.error(str(e))
            else:
                st.warning("Escribe un mensaje de commit.")
