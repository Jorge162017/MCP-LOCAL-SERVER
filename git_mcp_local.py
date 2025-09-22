# git_mcp_local.py
import os
import shutil
from typing import Any, Dict, List, Optional

# Usamos el helper de alto nivel del SDK oficial (sin pelear con transportes):
from mcp.client.stdio import stdio_client  # type: ignore


class GitClient:
    """
    Cliente MCP para el servidor oficial de Git.
    Arranca:   uvx mcp-server-git --repository <repo>
    Expone métodos SINCRONOS pensados para integrarse fácil en Streamlit.
    """

    def __init__(self, repo_path: Optional[str] = None):
        self.repo_path = os.path.abspath(repo_path or os.getcwd())
        self._acm = None        # context manager devuelto por stdio_client
        self._session = None    # ClientSession

    # ------------- ciclo de vida ------------------------------------------------
    def start_sync(self) -> None:
        """
        Inicia el server git (mcp-server-git) vía uvx y abre la sesión MCP.
        """
        if self._session:
            return

        # Verifica que uvx esté disponible
        if not shutil.which("uvx"):
            raise RuntimeError(
                "No se encontró 'uvx' en el PATH. Instala uv (https://docs.astral.sh/uv/):\n"
                "  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
                "…o asegúrate de tener 'uvx' en el PATH."
            )

        # Config estilo 'config dict' para stdio_client (más robusto entre versiones)
        config = {
            "command": "uvx",
            "args": ["mcp-server-git", "--repository", self.repo_path],
            # puedes añadir entorno si lo necesitas:
            # "env": {"FOO": "BAR"},
        }

        # Abre el context manager y guarda la sesión ya inicializada
        self._acm = stdio_client(config, client_name="mcp-local-ui", client_version="1.0.0")
        sess = self._acm.__enter__()   # síncrono en esta versión del SDK
        # Dependiendo del SDK puede devolver (session, transport) o solo session
        if isinstance(sess, tuple):
            self._session = sess[0]
        else:
            self._session = sess

        # precarga tools para fallar temprano si algo no va
        _ = self.tools_list_sync()

    def stop_sync(self) -> None:
        """
        Cierra la sesión MCP y el subproceso del server git.
        """
        if self._acm:
            try:
                self._acm.__exit__(None, None, None)
            finally:
                self._acm = None
        self._session = None

    def _ensure(self):
        if not self._session:
            raise RuntimeError("GitClient no iniciado. Llama start_sync() primero.")

    # ------------- helpers genéricos -------------------------------------------
    def tools_list_sync(self) -> List[Dict[str, Any]]:
        self._ensure()
        res = self._session.list_tools()  # type: ignore
        # Puede ser objeto tipo ToolsList; normalizamos a lista de dicts
        tools = []
        for t in getattr(res, "tools", []) or []:
            tools.append({"name": getattr(t, "name", None), "description": getattr(t, "description", None)})
        return tools

    def call_tool_sync(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure()
        result = self._session.call_tool(name, args)  # type: ignore
        # Normalizamos la respuesta a dict simple
        out: Dict[str, Any] = {}
        if hasattr(result, "content") and result.content:
            # tomamos el primer bloque; distintas tools devuelven text o data
            c0 = result.content[0]
            if getattr(c0, "type", None) == "text":
                out["text"] = getattr(c0, "text", "")
            elif getattr(c0, "type", None) == "data":
                out["content"] = getattr(c0, "data", None)
        # añade campos útiles crudos
        out.setdefault("raw", getattr(result, "model_dump", lambda: {} )())
        return out

    # ------------- operaciones Git (nombres de tools del server oficial) -------
    def status_sync(self) -> Dict[str, Any]:
        return self.call_tool_sync("git_status", {"repo_path": self.repo_path})

    def add_sync(self, files: List[str]) -> Dict[str, Any]:
        return self.call_tool_sync("git_add", {"repo_path": self.repo_path, "files": files})

    def commit_sync(self, message: str) -> Dict[str, Any]:
        return self.call_tool_sync("git_commit", {"repo_path": self.repo_path, "message": message})

    def log_sync(self, max_count: int = 10) -> Dict[str, Any]:
        return self.call_tool_sync("git_log", {"repo_path": self.repo_path, "max_count": max_count})

    def init_sync(self) -> Dict[str, Any]:
        return self.call_tool_sync("git_init", {"repo_path": self.repo_path})

    def branches_sync(self, branch_type: str = "local") -> Dict[str, Any]:
        return self.call_tool_sync("git_branch", {"repo_path": self.repo_path, "branch_type": branch_type})

    def checkout_sync(self, name: str) -> Dict[str, Any]:
        return self.call_tool_sync("git_checkout", {"repo_path": self.repo_path, "branch": name})
