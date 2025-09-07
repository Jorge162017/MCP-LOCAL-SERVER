import asyncio

class ToolRegistry:
    def __init__(self):
        self._tools = {}     # name -> spec
        self._handlers = {}  # name -> async fn(args) -> dict

    def register(self, spec: dict, handler):
        name = spec["name"]
        self._tools[name] = spec
        # Permite handler sync o async
        if asyncio.iscoroutinefunction(handler):
            self._handlers[name] = handler
        else:
            async def awrap(args): return handler(args)
            self._handlers[name] = awrap

    def list_tools(self):
        return {"tools": list(self._tools.values())}

    async def call(self, name: str, args: dict):
        if name not in self._handlers:
            raise ValueError(f"tool not found: {name}")
        return await self._handlers[name](args)
