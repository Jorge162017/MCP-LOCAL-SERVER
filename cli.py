#!/usr/bin/env python3
# cli.py — Chatbot anfitrión con contexto usando tu servidor MCP local
#           + puente opcional a Filesystem MCP (FS_MCP_CMD), Git MCP (GIT_MCP_CMD)
#           + Peer genérico (PEER1_MCP_CMD / PEER1_MCP_CWD)

import os
import sys
import json
import time
import orjson
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional

PROJ_ROOT = Path(__file__).resolve().parent

# -------------------- JSON-RPC helpers (server local) --------------------
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

def rpc_call(proc, method: str, params: dict | None = None, mid: int = 1):
    payload = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        payload["params"] = params
    return _send(proc, payload)

def call_tool(proc, name: str, args: dict, mid: int):
    return rpc_call(proc, "tools/call", {"name": name, "args": args}, mid)

# -------------------- Adaptador MCP externo (FS/Git/Peer) --------------------
from src.util.mcp_process import MCPProcess  # requiere src/util/mcp_process.py

# -------------------- Conversación --------------------
History = List[Tuple[str, str]]  # (role, content)

def build_prompt(history: History, user_msg: str, max_chars: int = 4000) -> str:
    lines: List[str] = []
    for role, text in history:
        lines.append(f"{role.upper()}: {text.strip()}")
    lines.append(f"USER: {user_msg.strip()}")
    prompt = "\n".join(lines)
    if len(prompt) > max_chars:
        prompt = prompt[-max_chars:]
        idx = prompt.find("\n")
        if idx > 0:
            prompt = prompt[idx+1:]
    return prompt

def save_transcript(history: History, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"# Transcript {ts}", ""]
    for role, text in history:
        prefix = "### " + ("Usuario" if role == "user" else "Asistente")
        lines += [prefix, "", text.strip(), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)

# -------------------- CLI --------------------
HELP = """Comandos:
  /help                Muestra esta ayuda
  /tools               Lista herramientas del server local
  /new                 Reinicia el contexto
  /save [archivo.md]   Guarda el transcript (default: reports/chat.md)
  /call NAME {json}    Llama una tool del server local con args en JSON

  # Filesystem MCP externo (si FS_MCP_CMD está definido)
  /fs.list             Lista las tools del FS MCP
  /fs.call NAME {json} Llama una tool del FS MCP
  /fs.rpc {json}       RPC crudo al FS MCP (ej: {"method":"tools/list"})

  # Git MCP externo (si GIT_MCP_CMD está definido)
  /git.list            Lista las tools del Git MCP
  /git.call NAME {json}Llama una tool del Git MCP
  /git.rpc {json}      RPC crudo al Git MCP

  # Peer1 genérico (si PEER1_MCP_CMD está definido)
  /peer1.list          Lista tools del peer
  /peer1.call NAME {json}
  /peer1.rpc {json}

  /exit                Salir

Sin comando: envía el mensaje al LLM (tool llm_chat) manteniendo contexto.
"""

def main():
    # Lanza el server MCP local
    env = {**os.environ, "PYTHONPATH": str(PROJ_ROOT)}
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(PROJ_ROOT),
        env=env,
        text=False,
        bufsize=0,
    )

    # Inicializa y lista tools locales
    try:
        rpc_call(proc, "initialize", {"client": "cli"}, mid=0)
    except Exception:
        pass
    res = rpc_call(proc, "tools/list", mid=1)
    tools = {t["name"] for t in res["result"]["tools"]}
    print(f"🧩 Tools: {', '.join(sorted(tools))}")
    if "llm_chat" not in tools:
        print("⚠️  No está llm_chat; revisa tu server/registry.")
    print("💬 Escribe tu mensaje (o /help). Ctrl+C o /exit para salir.\n")

    # Arrancar FS MCP si FS_MCP_CMD está definido
    fs_cmd = os.getenv("FS_MCP_CMD")
    fs: Optional[MCPProcess] = None
    if fs_cmd:
        try:
            fs = MCPProcess(fs_cmd, cwd=str(PROJ_ROOT), env=os.environ).start()
            fs.initialize()
            names = [t["name"] for t in fs.tools_list()]
            print(f"🗂️  FS MCP listo: {', '.join(names) or '(sin tools?)'}")
        except Exception as e:
            print(f"⚠️  FS MCP no inicializó: {e}")
            fs = None

    # Arrancar Git MCP si GIT_MCP_CMD está definido
    git_cmd = os.getenv("GIT_MCP_CMD")
    git: Optional[MCPProcess] = None
    if git_cmd:
        try:
            git = MCPProcess(git_cmd, cwd=str(PROJ_ROOT), env=os.environ).start()
            git.initialize()
            names = [t["name"] for t in git.tools_list()]
            print(f"📦  Git MCP listo: {', '.join(names) or '(sin tools?)'}")
        except Exception as e:
            print(f"⚠️  Git MCP no inicializó: {e}")
            git = None

    # Arrancar Peer1 MCP genérico si PEER1_MCP_CMD está definido
    peer1_cmd = os.getenv("PEER1_MCP_CMD")
    peer1_cwd = os.getenv("PEER1_MCP_CWD", str(PROJ_ROOT))
    peer1: Optional[MCPProcess] = None
    if peer1_cmd:
        try:
            peer1 = MCPProcess(peer1_cmd, cwd=peer1_cwd, env=os.environ).start()
            peer1.initialize()
            names = [t["name"] for t in peer1.tools_list()]
            print(f"🤝 Peer1 MCP listo: {', '.join(names) or '(sin tools?)'}")
        except Exception as e:
            print(f"⚠️  Peer1 MCP no inicializó: {e}")
            peer1 = None

    # Config “suave” por entorno
    default_temp = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    default_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "120"))

    history: History = []
    mid = 10

    try:
        while True:
            try:
                user_msg = input("> ").strip()
            except EOFError:
                break
            if not user_msg:
                continue

            # ---- comandos ----
            if user_msg.startswith("/"):
                parts = user_msg.split(" ", 2)
                cmd = parts[0].lower()

                if cmd in ("/exit", "/quit", "/q"):
                    break

                if cmd == "/help":
                    print(HELP)
                    continue

                if cmd == "/new":
                    history.clear()
                    print("🆕 Contexto reiniciado.")
                    continue

                if cmd == "/tools":
                    res = rpc_call(proc, "tools/list", mid=mid); mid += 1
                    listed = [t["name"] for t in res["result"]["tools"]]
                    print("🧩 Tools disponibles:", ", ".join(sorted(listed)))
                    continue

                if cmd == "/save":
                    out = Path("reports/chat.md") if len(parts) == 1 else Path(parts[1])
                    path = save_transcript(history, out)
                    print(f"💾 Transcript guardado → {path}")
                    continue

                if cmd == "/call":
                    if len(parts) < 3:
                        print("Uso: /call NAME {json_args}")
                        continue
                    name = parts[1]
                    try:
                        args = json.loads(parts[2])
                    except Exception as e:
                        print(f"JSON inválido: {e}")
                        continue
                    try:
                        resp = call_tool(proc, name, args, mid=mid); mid += 1
                        if "error" in resp:
                            print("[ERROR]", resp["error"])
                        else:
                            print(orjson.dumps(resp["result"], option=orjson.OPT_INDENT_2).decode())
                    except Exception as e:
                        print(f"[call error] {e}")
                    continue

                # ----- Filesystem MCP externo -----
                if cmd == "/fs.list":
                    if not fs:
                        print("FS MCP no está configurado (FS_MCP_CMD).")
                        continue
                    try:
                        tools = fs.tools_list()
                        print("🗂️  FS tools:", ", ".join(t["name"] for t in tools))
                    except Exception as e:
                        print(f"[fs.list error] {e}")
                    continue

                if cmd == "/fs.call":
                    if not fs:
                        print("FS MCP no está configurado (FS_MCP_CMD).")
                        continue
                    if len(parts) < 3:
                        print("Uso: /fs.call NAME {json_args}")
                        continue
                    name = parts[1]
                    try:
                        args = json.loads(parts[2])
                    except Exception as e:
                        print(f"JSON inválido: {e}")
                        continue
                    try:
                        result = fs.tools_call(name, args)
                        print(orjson.dumps(result, option=orjson.OPT_INDENT_2).decode())
                    except Exception as e:
                        print(f"[fs.call error] {e}")
                    continue

                if cmd == "/fs.rpc":
                    if not fs:
                        print("FS MCP no está configurado (FS_MCP_CMD).")
                        continue
                    if len(parts) < 2:
                        print('Uso: /fs.rpc {"method":"tools/list"}')
                        continue
                    try:
                        payload = json.loads(parts[1])
                    except Exception as e:
                        print(f"JSON inválido: {e}")
                        continue
                    try:
                        m = payload.get("method")
                        params = payload.get("params")
                        res = fs.rpc_call(m, params)
                        print(orjson.dumps(res, option=orjson.OPT_INDENT_2).decode())
                    except Exception as e:
                        print(f"[fs.rpc error] {e}")
                    continue

                # ----- Git MCP externo -----
                if cmd == "/git.list":
                    if not git:
                        print("Git MCP no está configurado (GIT_MCP_CMD).")
                        continue
                    try:
                        tools = git.tools_list()
                        print("📦  Git tools:", ", ".join(t["name"] for t in tools))
                    except Exception as e:
                        print(f"[git.list error] {e}")
                    continue

                if cmd == "/git.call":
                    if not git:
                        print("Git MCP no está configurado (GIT_MCP_CMD).")
                        continue
                    if len(parts) < 3:
                        print("Uso: /git.call NAME {json_args}")
                        continue
                    name = parts[1]
                    try:
                        args = json.loads(parts[2])
                    except Exception as e:
                        print(f"JSON inválido: {e}")
                        continue
                    try:
                        result = git.tools_call(name, args)
                        print(orjson.dumps(result, option=orjson.OPT_INDENT_2).decode())
                    except Exception as e:
                        print(f"[git.call error] {e}")
                    continue

                if cmd == "/git.rpc":
                    if not git:
                        print("Git MCP no está configurado (GIT_MCP_CMD).")
                        continue
                    if len(parts) < 2:
                        print('Uso: /git.rpc {"method":"tools/list"}')
                        continue
                    try:
                        payload = json.loads(parts[1])
                    except Exception as e:
                        print(f"JSON inválido: {e}")
                        continue
                    try:
                        m = payload.get("method")
                        params = payload.get("params")
                        res = git.rpc_call(m, params)
                        print(orjson.dumps(res, option=orjson.OPT_INDENT_2).decode())
                    except Exception as e:
                        print(f"[git.rpc error] {e}")
                    continue

                # ----- Peer1 genérico -----
                if cmd == "/peer1.list":
                    if not peer1:
                        print("Peer1 no está configurado (PEER1_MCP_CMD).")
                        continue
                    try:
                        tools = peer1.tools_list()
                        print("🤝  Peer1 tools:", ", ".join(t["name"] for t in tools))
                    except Exception as e:
                        print(f"[peer1.list error] {e}")
                    continue

                if cmd == "/peer1.call":
                    if not peer1:
                        print("Peer1 no está configurado (PEER1_MCP_CMD).")
                        continue
                    if len(parts) < 3:
                        print("Uso: /peer1.call NAME {json_args}")
                        continue
                    name = parts[1]
                    try:
                        args = json.loads(parts[2])
                    except Exception as e:
                        print(f"JSON inválido: {e}")
                        continue
                    try:
                        result = peer1.tools_call(name, args)
                        print(orjson.dumps(result, option=orjson.OPT_INDENT_2).decode())
                    except Exception as e:
                        print(f"[peer1.call error] {e}")
                    continue

                if cmd == "/peer1.rpc":
                    if not peer1:
                        print("Peer1 no está configurado (PEER1_MCP_CMD).")
                        continue
                    if len(parts) < 2:
                        print('Uso: /peer1.rpc {"method":"tools/list"}')
                        continue
                    try:
                        payload = json.loads(parts[1])
                    except Exception as e:
                        print(f"JSON inválido: {e}")
                        continue
                    try:
                        m = payload.get("method")
                        params = payload.get("params")
                        res = peer1.rpc_call(m, params)
                        print(orjson.dumps(res, option=orjson.OPT_INDENT_2).decode())
                    except Exception as e:
                        print(f"[peer1.rpc error] {e}")
                    continue

                print("Comando no reconocido. /help para ayuda.")
                continue

            # ---- chat normal con contexto ----
            history.append(("user", user_msg))
            prompt = build_prompt(history, user_msg, max_chars=4000)

            args = {
                "prompt": prompt,
                "temperature": default_temp,
                "max_tokens": default_max_tokens,
            }

            try:
                resp = call_tool(proc, "llm_chat", args, mid=mid); mid += 1
                if "error" in resp:
                    text = f"[llm_chat][ERROR] {resp['error'].get('message')}"
                else:
                    text = resp["result"].get("text", "").strip() or "(respuesta vacía)"
            except Exception as e:
                text = f"[llm_chat][EXCEPTION] {e}"

            print(text)
            history.append(("assistant", text))

    except KeyboardInterrupt:
        pass
    finally:
        try:
            rpc_call(proc, "shutdown", mid=999)
        except Exception:
            pass
        proc.terminate()

if __name__ == "__main__":
    main()
