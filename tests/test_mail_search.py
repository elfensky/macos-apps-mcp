import asyncio

from fastmcp import Client

import macos_apps_mcp.server as srv


def test_mail_search_tool_registered_read_only():
    async def go():
        async with Client(srv.mcp) as c:
            tools = {t.name: t for t in await c.list_tools()}
            assert "mail_search" in tools and "mail_index_bodies" in tools
            assert tools["mail_search"].annotations.readOnlyHint is True
            assert tools["mail_index_bodies"].annotations.readOnlyHint is True

    asyncio.run(go())
