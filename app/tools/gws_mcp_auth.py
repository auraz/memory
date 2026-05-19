from __future__ import annotations

import argparse
import asyncio
import os
import re
import shlex

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.settings import settings


async def run_auth_probe(spreadsheet_id: str, range_name: str, wait_seconds: int) -> None:
    params = StdioServerParameters(
        command=settings.gws_mcp_command,
        args=shlex.split(settings.gws_mcp_args),
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "read_sheet_values",
                {
                    "user_google_email": settings.gws_mcp_user_google_email,
                    "spreadsheet_id": spreadsheet_id,
                    "range_name": range_name,
                },
            )
            text = "\n".join(str(getattr(item, "text", "")) for item in getattr(result, "content", []))
            match = re.search(r"https://accounts\.google\.com/o/oauth2/auth\S+", text)
            if match:
                print(f"AUTH_URL={match.group(0)}", flush=True)
                print(f"Keeping OAuth callback server alive for {wait_seconds} seconds.", flush=True)
                await asyncio.sleep(wait_seconds)
                return
            print(text or "No authorization URL returned; credentials may already be valid.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a Workspace MCP OAuth probe and keep callback alive.")
    parser.add_argument("spreadsheet_id")
    parser.add_argument("--range", default="Sheet1!A1:A1", dest="range_name")
    parser.add_argument("--wait-seconds", default=300, type=int)
    args = parser.parse_args()
    if not settings.gws_mcp_user_google_email.strip():
        raise SystemExit("GWS_MCP_USER_GOOGLE_EMAIL must be set.")
    asyncio.run(run_auth_probe(args.spreadsheet_id, args.range_name, args.wait_seconds))


if __name__ == "__main__":
    main()
