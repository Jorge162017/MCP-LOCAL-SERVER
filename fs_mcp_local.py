# fs_mcp_local.py
# Cliente MCP (JSON-RPC por stdio) genérico: sirve para Filesystem (Node) y Git (Python).
# - Corre el server como subproceso
# - Mantiene su propio event loop en un hilo (seguro para Streamlit)
# - NO agrega 'root' al comando cuando se usa server_cmd (a menos que pass_root=True)

from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import Future
from typing import Any, Optional, List


class FSClient:
    def __init__(
        self,
        root: str | None = None,
        server_cmd: Optional[List[str]] = None,
        pass_root: bool = False,
        env: Optional[dict] = None,
    ):
        """
        root: ruta base (para FS server o para herramientas que lo necesiten)
        server_cmd: comando completo a ejecutar (ej. ['python','-m','mcp_server_git','--repository','/repo'])
        pass_root: si True, añade 'root' al final del comando (solo útil para servers que esperan arg posicional)
        env: extra env vars
        """
        self.root = os.path.abspath(root or os.getcwd())
        self.server_cmd = list(server_cmd) if server_cmd else None
        self.pass_root = bool(pass_root)
        self.env = dict(env or {})

        self._proc: Optional[asyncio.subprocess.Process] = None
        self._req_id = 0
        self._started = False

        # Loop propio en hilo (evita conflictos con Streamlit)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        # Para debug
        self._last_cmd: Optional[List[str]] = None

    # ────────────────────────── Infra de loop en hilo ──────────────────────────
    def _ensure_loop(self) -> None:
        if self._loop and self._thread and self._thread.is_alive():
            return

        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            loop.run_forever()

        self._thread = threading.Thread(target=_runner, name="FSClientLoop", daemon=True)
        self._thread.start()
        while self._loop is None:
            pass  # espera hasta que el loop esté listo

    def _run(self, coro) -> Any:
        """Ejecuta una corrutina en el loop del hilo y devuelve el resultado (bloqueante)."""
        assert self._loop is not None, "Loop no inicializado"
        fut: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    # ────────────────────────── JSON-RPC helpers (async) ───────────────────────
    async def _rpc(self, method: str, params: Optional[dict] = None) -> Any:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise RuntimeError("Servidor MCP no iniciado")

        self._req_id += 1
        req = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params is not None:
            req["params"] = params

        line = json.dumps(req, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

        resp_line = await self._proc.stdout.readline()
        if not resp_line:
            err = ""
            try:
                err_bytes = await self._proc.stderr.read()  # type: ignore[arg-type]
                err = err_bytes.decode("utf-8", "ignore") if err_bytes else ""
            except Exception:
                pass
            raise RuntimeError(f"Servidor MCP sin respuesta. STDERR:\n{err}")

        resp = json.loads(resp_line.decode("utf-8").strip())
        if "error" in resp:
            msg = resp["error"].get("message", "error")
            raise RuntimeError(f"MCP error: {msg}")
        return resp.get("result")

    # ────────────────────────── Ciclo de vida (async) ──────────────────────────
    async def start(self) -> None:
        if self._started:
            return

        # Construye comando real
        if self.server_cmd:
            cmd = list(self.server_cmd)
            if self.pass_root:
                cmd.append(self.root)  # solo si el server espera root posicional
        else:
            # Default: Filesystem server vía Node, espera root como posicional
            cmd = ["npx", "-y", "@modelcontextprotocol/server-filesystem", self.root]

        self._last_cmd = cmd  # para debug

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **self.env},
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"No se pudo ejecutar el servidor MCP: {e}")

        # Handshake JSON-RPC
        await self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-local-ui", "version": "0.1.0"},
            },
        )
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        assert self._proc and self._proc.stdin
        self._proc.stdin.write((json.dumps(notif) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

        self._started = True

    async def stop(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
            finally:
                self._proc = None
        self._started = False

    # ────────────────────────── Tools genéricas (async) ────────────────────────
    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Invoca cualquier tool del servidor MCP actual."""
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})

    async def tools_list(self) -> list[dict]:
        """Lista las tools publicadas por el servidor."""
        res = await self._rpc("tools/list")
        return (res or {}).get("tools", [])

    # ────────────────────────── FS conveniencia (async) ────────────────────────
    async def list_dir(self, path: str = ".") -> list[dict[str, Any]]:
        out = await self.call_tool("list_directory", {"path": path})
        content = (out or {}).get("content") or []
        if content and "data" in content[0]:
            return content[0]["data"]
        return []

    async def read_file(self, path: str) -> str:
        out = await self.call_tool("read_file", {"path": path})
        content = (out or {}).get("content") or []
        if content and "text" in content[0]:
            return content[0]["text"]
        return ""

    async def write_file(self, path: str, content: str) -> dict[str, Any]:
        out = await self.call_tool("write_file", {"path": path, "content": content})
        return out or {}

    async def create_dir(self, path: str) -> dict[str, Any]:
        for tool in ("create_directory", "make_directory", "mkdir"):
            try:
                return await self.call_tool(tool, {"path": path})
            except Exception:
                continue
        raise RuntimeError("El servidor FS no expone una tool de creación de carpetas conocida.")

    # ────────────────────────── Métodos SÍNCRONOS (para Streamlit) ─────────────
    def start_sync(self) -> None:
        self._ensure_loop()
        self._run(self.start())

    def stop_sync(self) -> None:
        if self._loop:
            self._run(self.stop())
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def call_tool_sync(self, name: str, arguments: dict) -> Any:
        self._ensure_loop()
        return self._run(self.call_tool(name, arguments))

    def tools_list_sync(self) -> list[dict]:
        self._ensure_loop()
        return self._run(self.tools_list())

    # FS sync helpers (para tu pestaña FS)
    def list_dir_sync(self, path: str = ".") -> list[dict[str, Any]]:
        self._ensure_loop()
        return self._run(self.list_dir(path))

    def read_file_sync(self, path: str) -> str:
        self._ensure_loop()
        return self._run(self.read_file(path))

    def write_file_sync(self, path: str, content: str) -> dict[str, Any]:
        self._ensure_loop()
        return self._run(self.write_file(path, content))

    def create_dir_sync(self, path: str) -> dict[str, Any]:
        self._ensure_loop()
        return self._run(self.create_dir(path))
