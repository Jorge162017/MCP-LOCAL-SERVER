# src/util/mcp_process.py
from __future__ import annotations
import subprocess
import orjson
import shlex
import time
from typing import Optional, Dict, Any, List

class MCPProcess:
    """
    Pequeño wrapper para un proceso MCP (JSON-RPC por stdin/stdout).
    Ejemplo:
        proc = MCPProcess("filesystem-mcp --stdio").start()
        proc.initialize()
        tools = proc.tools_list()
        res = proc.tools_call("writeFile", {"path":"README.md","text":"hola"})
        proc.shutdown()
    """
    def __init__(self, cmd: str, cwd: Optional[str] = None, env: Optional[dict] = None):
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.p = None
        self._id = 0

    def start(self) -> "MCPProcess":
        if self.p:
            return self
        argv = shlex.split(self.cmd)
        self.p = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            env=self.env,
            text=False,
            bufsize=0,
        )
        return self

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.p or not self.p.stdin or not self.p.stdout:
            raise RuntimeError("Proceso MCP no iniciado.")
        self.p.stdin.write(orjson.dumps(payload) + b"\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            # opcional: leer stderr para ayuda
            try:
                err = (self.p.stderr.read() or b"").decode()
            except Exception:
                err = ""
            raise RuntimeError(f"MCP ({self.cmd}) no respondió. {err}")
        return orjson.loads(line)

    def rpc_call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            payload["params"] = params
        return self._send(payload)

    # Helpers típicos
    def initialize(self) -> Dict[str, Any]:
        return self.rpc_call("initialize", {"client": "cli-host"})

    def tools_list(self) -> List[Dict[str, Any]]:
        res = self.rpc_call("tools/list")
        return res.get("result", {}).get("tools", [])

    def tools_call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        res = self.rpc_call("tools/call", {"name": name, "args": args})
        if "error" in res:
            return res
        return res.get("result", {})

    def shutdown(self):
        try:
            self.rpc_call("shutdown")
        except Exception:
            pass
        try:
            if self.p:
                self.p.terminate()
        except Exception:
            pass
