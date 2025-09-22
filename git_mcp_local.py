#!/usr/bin/env python3
# git_mcp_local.py — MCP mínimo para Git por JSON-RPC (stdin/stdout)
import sys, os, orjson, traceback, subprocess
from pathlib import Path
from typing import Dict, Any, List

def ok(mid, result):   return {"jsonrpc":"2.0","id":mid,"result":result}
def err(mid, code, msg, data=None):
    e={"code":code,"message":msg}
    if data is not None: e["data"]=data
    return {"jsonrpc":"2.0","id":mid,"error":e}

def _run_git(cwd: Path, args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, check=False)

def _ensure_repo(dirp: Path):
    if not (dirp / ".git").exists():
        raise RuntimeError(f"No es repo git: {dirp}")

def tools_list():
    return {
        "tools":[
            {"name":"init","description":"Inicializa repo en 'dir'","input_schema":{"type":"object","properties":{"dir":{"type":"string"}},"required":["dir"]}},
            {"name":"add","description":"Agrega archivos al index","input_schema":{"type":"object","properties":{"dir":{"type":"string"},"files":{"type":"array","items":{"type":"string"}}},"required":["dir","files"]}},
            {"name":"commit","description":"Commit con mensaje","input_schema":{"type":"object","properties":{"dir":{"type":"string"},"message":{"type":"string"},"author_name":{"type":"string"},"author_email":{"type":"string"}},"required":["dir","message"]}},
            {"name":"status","description":"git status --porcelain","input_schema":{"type":"object","properties":{"dir":{"type":"string"}},"required":["dir"]}},
            {"name":"log","description":"git log -n N --oneline","input_schema":{"type":"object","properties":{"dir":{"type":"string"},"n":{"type":"integer"}},"required":["dir"]}},
        ]
    }

def call_tool(name: str, args: Dict[str, Any]):
    dirp = Path(args["dir"]).expanduser().resolve()
    dirp.mkdir(parents=True, exist_ok=True)

    if name == "init":
        cp = _run_git(dirp, ["init"])
        ok1 = cp.returncode == 0
        return {"ok": ok1, "dir": str(dirp), "stdout": cp.stdout, "stderr": cp.stderr}

    elif name == "add":
        _ensure_repo(dirp)
        files = args.get("files") or []
        cp = _run_git(dirp, ["add", *files])
        return {"ok": cp.returncode == 0, "stdout": cp.stdout, "stderr": cp.stderr}

    elif name == "commit":
        _ensure_repo(dirp)
        # Asegura identidad local si no existe
        name = args.get("author_name") or "MCP Bot"
        email = args.get("author_email") or "mcp@example.local"
        _run_git(dirp, ["config", "user.name", name])
        _run_git(dirp, ["config", "user.email", email])
        msg = args["message"]
        cp = _run_git(dirp, ["commit", "-m", msg])
        return {"ok": cp.returncode == 0, "stdout": cp.stdout, "stderr": cp.stderr}

    elif name == "status":
        _ensure_repo(dirp)
        cp = _run_git(dirp, ["status", "--porcelain"])
        return {"ok": cp.returncode == 0, "stdout": cp.stdout, "stderr": cp.stderr}

    elif name == "log":
        _ensure_repo(dirp)
        n = int(args.get("n", 10))
        cp = _run_git(dirp, ["log", f"-n{n}", "--oneline"])
        return {"ok": cp.returncode == 0, "stdout": cp.stdout, "stderr": cp.stderr}

    else:
        raise ValueError(f"tool not found: {name}")

def main():
    while True:
        line = sys.stdin.buffer.readline()
        if not line: break
        try:
            msg = orjson.loads(line)
            mid = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {}) or {}
            if method == "initialize":
                resp = ok(mid, {"serverName":"git-mcp-local","protocol":"jsonrpc2"})
            elif method == "tools/list":
                resp = ok(mid, tools_list())
            elif method == "tools/call":
                resp = ok(mid, call_tool(params["name"], params.get("args") or {}))
            elif method == "shutdown":
                resp = ok(mid, {"ok": True})
            else:
                resp = err(mid, -32601, f"Method not found: {method}")
        except Exception as e:
            resp = err(msg.get("id") if 'msg' in locals() else None, -32000, str(e), {"trace": traceback.format_exc()})
        sys.stdout.buffer.write(orjson.dumps(resp) + b"\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
