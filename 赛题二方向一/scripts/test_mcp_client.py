# -*- coding: utf-8 -*-
"""MCP 端到端自测：以标准 stdio 协议连接本工程的 MCP Server 并调用工具。

这是"任何 Agent 即插即用"的证明——本脚本扮演一个 MCP 客户端。
用法：python scripts/test_mcp_client.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import enable_utf8  # noqa: E402

enable_utf8()

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


def _text(result) -> str:
    parts = []
    for c in result.content:
        parts.append(getattr(c, "text", str(c)))
    return "\n".join(parts)


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp_server.py")],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("== 工具清单 ==")
            for t in tools.tools:
                print(f"  · {t.name}: {(t.description or '').splitlines()[0]}")

            resources = await session.list_resources()
            print("== 资源清单 ==")
            for r in resources.resources:
                print(f"  · {r.uri}")

            prompts = await session.list_prompts()
            print("== Prompt 清单 ==")
            for p in prompts.prompts:
                print(f"  · {p.name}")

            print("\n== 调用 nl_query（歧义问题，应返回澄清卡）==")
            r1 = await session.call_tool("nl_query", {"question": "8月的金额是多少？", "auto_resolve": False})
            data = json.loads(_text(r1))
            print("  type:", data["type"], "| 澄清点:", [p["id"] for p in data.get("points", [])])

            print("\n== 调用 nl_query（明确问题，应返回答案 + 披露）==")
            r2 = await session.call_tool("nl_query", {"question": "8月华东区的履约超时率是多少按已签收口径"})
            data2 = json.loads(_text(r2))
            print("  type:", data2["type"], "| 答案:", data2.get("text"))
            print("  披露:", data2.get("disclosure"))
            print("  信任标签:", data2.get("trust"))

            print("\n== 调用 align_terms（仅对齐）==")
            r3 = await session.call_tool("align_terms", {"question": "8月苹果的订单量是多少？"})
            print(" ", _text(r3).replace("\n", " ")[:160])

            print("\n== 调用 run_metric（多口径未指定 → 应返回澄清选项，不猜）==")
            r4 = await session.call_tool("run_metric", {"metric": "GMV", "region": "华东"})
            d4 = json.loads(_text(r4))
            print("  type:", d4["type"], "| 澄清点:", [p["id"] for p in d4.get("points", [])],
                  "| 选项数:", len((d4.get("points") or [{}])[0].get("options", [])))

            print("\n== 调用 run_metric（指定口径 net → 应返回数值 + 披露 + 信任标签）==")
            r5 = await session.call_tool("run_metric", {"metric": "GMV", "variant": "net",
                                                       "region": "华东",
                                                       "start_date": "2026-08-01",
                                                       "end_date": "2026-08-31"})
            d5 = json.loads(_text(r5))
            print("  type:", d5["type"], "| 值:", d5.get("value"), "| 口径:", d5.get("variant"))
            print("  披露:", d5.get("disclosure"))
            print("  信任标签:", d5.get("trust"))
            assert d5["type"] == "answer" and d5["value"] is not None, "run_metric 应返回数值答案"

            print("\n✅ MCP 端到端自测完成")


if __name__ == "__main__":
    asyncio.run(main())
