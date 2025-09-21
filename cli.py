#!/usr/bin/env python3
# cli.py — Chatbot anfitrión con contexto usando tu servidor MCP local
import os
import sys
import json
import time
import orjson
import subprocess
from pathlib import Path
from typing import List, Tuple

PROJ_ROOT = Path(__file__).resolve().parent

# -------------------- JSON-RPC helpers --------------------
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

# -------------------- Conversación --------------------
History = List[Tuple[str, str]]  # (role, content)

def build_prompt(history: History, user_msg: str, max_chars: int = 4000) -> str:
    """
    Empaqueta el historial en un prompt compacto:
    [system implícito lo pone el server] + últimos turnos + mensaje del usuario.
    Limitamos a ~max_chars para no exceder token window.
    """
    lines: List[str] = []
    for role, text in history:
        lines.append(f"{role.upper()}: {text.strip()}")
    lines.append(f"USER: {user_msg.strip()}")
    prompt = "\n".join(lines)
    # recorta por la cola si se pasa
    if len(prompt) > max_chars:
        prompt = prompt[-max_chars:]
        # intenta no cortar en mitad de línea
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
  /tools               Lista herramientas disponibles
  /new                 Reinicia el contexto
  /save [archivo.md]   Guarda el transcript (default: reports/chat.md)
  /call NAME {json}    Llama una tool arbitraria con args en JSON
  /exit                Salir

Sin comando: envía el mensaje al LLM (tool llm_chat) manteniendo contexto.
"""

def main():
    # Lanza el server MCP
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

    # inicializa y obtiene tools
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

    # Config “suave” por entorno
    default_temp = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    default_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "120"))

    history: History = []  # [(role, content)]

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

                print("Comando no reconocido. /help para ayuda.")
                continue

            # ---- chat normal con contexto ----
            history.append(("user", user_msg))
            prompt = build_prompt(history, user_msg, max_chars=4000)

            args = {
                "prompt": prompt,
                # No mandamos "system": el server usa prompts/system_llm.txt
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
