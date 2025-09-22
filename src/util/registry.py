# util/registry.py
import asyncio
import importlib
from typing import Any, Callable, Dict, Tuple

class ToolRegistry:
    """
    Registro de herramientas MCP.
    - Acepta handlers sync/async.
    - list_tools() → { "tools": [spec, ...] }
    - call(name, args) → dict con el resultado del handler.
    """
    def __init__(self) -> None:
        self._tools: Dict[str, dict] = {}                 # name -> spec
        self._handlers: Dict[str, Callable[..., Any]] = {}  # name -> async fn(args) -> dict

    def register(self, spec: dict, handler: Callable[..., Any]) -> None:
        name = spec["name"]
        self._tools[name] = spec
        if asyncio.iscoroutinefunction(handler):
            self._handlers[name] = handler
        else:
            async def _awrap(args: dict) -> dict:
                return handler(args)
            self._handlers[name] = _awrap

    def list_tools(self) -> dict:
        return {"tools": list(self._tools.values())}

    async def call(self, name: str, args: dict) -> dict:
        if name not in self._handlers:
            raise ValueError(f"tool not found: {name}")
        return await self._handlers[name](args)


# ---------- helpers para cargar módulos de tools ----------
def _resolve_spec_and_handler(module) -> Tuple[dict, Callable[..., Any]]:
    """
    Soporta dos estilos:
      - tool_def() -> dict   (nuestro estilo nuevo)
      - tool_spec : dict     (tu estilo original)
    En ambos casos, el handler debe ser `run`.
    """
    # spec
    if hasattr(module, "tool_def") and callable(getattr(module, "tool_def")):
        spec = module.tool_def()
    elif hasattr(module, "tool_spec"):
        spec = module.tool_spec
    elif hasattr(module, "TOOL_SPEC"):
        spec = module.TOOL_SPEC
    else:
        raise ValueError(f"{module.__name__}: no se encontró tool_def() ni tool_spec")

    # handler
    if not hasattr(module, "run"):
        raise ValueError(f"{module.__name__}: no se encontró handler run(...)")
    handler = getattr(module, "run")
    return spec, handler


def build_registry() -> ToolRegistry:
    """
    Crea el registro con todos los tools.
    Ajusta la lista si agregas/renombras módulos.
    """
    reg = ToolRegistry()

    module_names = [
        "src.tools.pdf_extract",
        "src.tools.data_profile",
        "src.tools.ts_forecast",
        "src.tools.report_generate",
        "src.tools.llm_chat",              # Llama vía Ollama
        "src.tools.project_scaffold",      # registrar scaffold
    ]

    for modname in module_names:
        m = importlib.import_module(modname)
        spec, handler = _resolve_spec_and_handler(m)
        reg.register(spec, handler)

    return reg
