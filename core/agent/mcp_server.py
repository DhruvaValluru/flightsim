"""Serve the tools over the Model Context Protocol when the optional
``mcp`` package is present (contracts §7). It is not in
``requirements.txt`` and must not become required: importing this
module never imports ``mcp``; :func:`serve` does, and says by name
when it is absent.

    .venv/bin/python -m core.agent.mcp_server --out campaigns/demo

Every MCP tool call goes through :meth:`core.agent.tools.Tools.call`,
so the policy and the trace apply exactly as they do for the
controller and the tests; MCP annotations are metadata, not
enforcement (brainstorm §7.2).

Not claimed: tested against an MCP client here (none is installed);
only the schema handed to the server is the one the tests check.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

from .tools import TOOL_NAMES, Tools, schemas

#: What a caller without ``mcp`` is told, by name. Not a catalogue
#: entry: nothing in the pipeline refuses this; only this optional
#: entry point does, and it is not reachable from a page or a CLI.
MCP_MISSING = ("the optional 'mcp' package is not installed; "
               "pip install mcp to serve the tools over MCP "
               "(the controller and the CLI need no MCP)")


def mcp_tools() -> List[Dict[str, Any]]:
    """The tool list an MCP server advertises: name, description,
    inputSchema -- drawn from the same schemas the docs are built from."""
    return [{"name": s["name"], "description": s["description"],
             "inputSchema": s["parameters"]} for s in schemas()]


def serve(out: str, tier: str = "regex") -> int:
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore
    except ImportError:
        print(f"mcp is not installed: {MCP_MISSING}")
        return 2
    tools = Tools(out, tier=tier)
    server = FastMCP("flightsim")
    for name in TOOL_NAMES:
        def make(tool_name: str):
            def handler(reason: str = "", **kwargs: Any) -> str:
                return json.dumps(tools.call(tool_name, reason=reason, **kwargs),
                                  default=str)
            handler.__name__ = tool_name
            handler.__doc__ = next(s["description"] for s in schemas() if s["name"] == tool_name)
            return handler
        server.tool(name=name)(make(name))
    server.run()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="serve the agent tools over MCP")
    parser.add_argument("--out", required=True, help="the directory campaigns and the trace live in")
    parser.add_argument("--tier", default="regex", choices=("regex", "llm"))
    parser.add_argument("--list", action="store_true", help="print the tool list and exit")
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps(mcp_tools(), indent=1))
        return 0
    return serve(args.out, tier=args.tier)


if __name__ == "__main__":
    sys.exit(main())
