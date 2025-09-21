# src/tools/llm_chat.py
import os
import time
from pathlib import Path

MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")
BASE  = os.getenv("OPENAI_API_BASE", "http://localhost:11434/v1")
KEY   = os.getenv("OPENAI_API_KEY", "ollama")

# ---- System prompt (archivo / env / fallback) ----
DEFAULT_SYSTEM = """Eres el asistente técnico del proyecto "MCP-LOCAL-SERVER".
Objetivo: responder breve, preciso y orientado a acción sobre las capacidades del servidor MCP.

Contexto del servidor:
- Expone herramientas MCP (tools) invocables por "tools/call".
- Resuelve tareas locales: extraer texto/tablas de PDF, perfilar CSV, pronóstico simple de series temporales y generar reportes HTML/PDF.

Política de respuesta:
- Longitud por defecto: 1 frase clara. Si el usuario pide más detalle, 3 viñetas máximo.
- Lenguaje: mismo idioma del usuario.
- No pidas más contexto salvo que sea imprescindible; en ese caso, sugiere exactamente qué input se necesita.
- Si se solicita “cómo probar”, devuelve un mini flujo input→tool→output (1 línea).
- No inventes herramientas que no existen; si falta una, dilo y sugiere la más cercana.

Formato sugerido cuando apliquen ejemplos:
- “Input → tool → Output/artefacto (ruta/archivo)”.

Estilo:
- Directo, técnico y sin rodeos.
"""

def _read_text_if_exists(p: Path) -> str | None:
    try:
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return None

def get_system_prompt() -> str:
    # 1) Ruta explícita por env
    path_env = os.getenv("LLM_SYSTEM_PROMPT_PATH")
    if path_env:
        txt = _read_text_if_exists(Path(path_env))
        if txt:
            return txt

    # 2) Ruta por defecto dentro del repo
    default_path = Path("prompts/system_llm.txt")
    txt = _read_text_if_exists(default_path)
    if txt:
        return txt

    # 3) Prompt en env directo
    env_txt = os.getenv("LLM_SYSTEM_PROMPT")
    if env_txt:
        return env_txt

    # 4) Fallback embebido
    return DEFAULT_SYSTEM


# ---- Definición MCP ----
def tool_def():
    return {
        "name": "llm_chat",
        "description": "Envía un prompt al modelo Llama (Ollama) y devuelve texto.",
        "args_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Instrucción del usuario."},
                "system": {"type": "string", "description": "System prompt opcional (override)."},
                "temperature": {"type": "number", "minimum": 0, "maximum": 2, "default": 0.2},
                "max_tokens": {"type": "integer", "minimum": 1, "default": 120}
            },
            "required": ["prompt"]
        }
    }

# ---- Implementación ----
def run(args):
    from openai import OpenAI  # OpenAI SDK apuntando al endpoint de Ollama
    client = OpenAI(base_url=BASE, api_key=KEY)

    prompt = args["prompt"]
    system = args.get("system") or get_system_prompt()
    temperature = float(args.get("temperature", 0.2))
    max_tokens = int(args.get("max_tokens", 120))

    t0 = time.time()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    text = resp.choices[0].message.content

    return {
        "provider": "ollama",
        "model": MODEL,
        "duration_ms": round((time.time() - t0) * 1000),
        "text": text
    }
