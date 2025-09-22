#!/usr/bin/env python3
# Expone /rpc (HTTP JSON) y reenvía a un proceso MCP por stdin/stdout

import argparse, asyncio, json, os, signal
from aiohttp import web

class MCPSubprocess:
    def __init__(self, cmd: list[str], cwd: str | None = None, verbose: bool = False):
        self.cmd = cmd
        self.cwd = cwd
        self.verbose = verbose
        self.proc: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()

    async def start(self):
        if self.proc and self.proc.returncode is None:
            return
        if self.verbose:
            print(f"[mcp] launching: {' '.join(self.cmd)} (cwd={self.cwd})")
        self.proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            cwd=self.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            if self.verbose:
                print("[mcp] terminating...")
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                self.proc.kill()
        self.proc = None

    async def call(self, payload: dict) -> dict:
        if not self.proc or self.proc.returncode is not None:
            await self.start()

        assert self.proc and self.proc.stdin and self.proc.stdout
        data = (json.dumps(payload) + "\n").encode()

        async with self.lock:  # serializa escritura/lectura
            if self.verbose:
                print(f"[mcp] → {payload.get('method')}")
            self.proc.stdin.write(data)
            await self.proc.stdin.drain()
            line = await self.proc.stdout.readline()
            if not line:
                # lee stderr para diagnóstico
                err = b""
                try:
                    err = await self.proc.stderr.read()
                except Exception:
                    pass
                raise RuntimeError(f"MCP no respondió. STDERR: {err.decode(errors='ignore')}")
            try:
                res = json.loads(line.decode().strip())
            except Exception as e:
                raise RuntimeError(f"Respuesta no-JSON del MCP: {e}: {line!r}")
            if self.verbose:
                print(f"[mcp] ← ok ({payload.get('id')})")
            return res

async def make_app(bridge: MCPSubprocess) -> web.Application:
    app = web.Application()

    async def rpc_handler(request: web.Request):
        try:
            payload = await request.json()
        except Exception as e:
            return web.json_response(
                {"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":f"JSON parse error: {e}"}},
                status=400
            )
        try:
            res = await bridge.call(payload)
            return web.json_response(res)
        except Exception as e:
            # Devolvemos error JSON-RPC
            rid = payload.get("id") if isinstance(payload, dict) else None
            return web.json_response(
                {"jsonrpc":"2.0","id":rid,"error":{"code":-32000,"message":str(e)}},
                status=500
            )

    app.add_routes([web.post("/rpc", rpc_handler)])

    async def on_cleanup(_):
        await bridge.stop()
    app.on_cleanup.append(on_cleanup)
    return app

def main():
    ap = argparse.ArgumentParser(description="MCP HTTP bridge (server-side)")
    ap.add_argument("--cmd", required=True, help="Comando MCP (ej: 'python -u main.py')")
    ap.add_argument("--cwd", default=None, help="Directorio de trabajo del MCP")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cmd = args.cmd if isinstance(args.cmd, list) else args.cmd.split()
    bridge = MCPSubprocess(cmd, cwd=args.cwd, verbose=args.verbose)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bridge.stop()))

    app = loop.run_until_complete(make_app(bridge))
    web.run_app(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
