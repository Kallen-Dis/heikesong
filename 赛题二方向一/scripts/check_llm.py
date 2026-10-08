# -*- coding: utf-8 -*-
"""LLM 连通性自检：依次尝试常见 OpenAI 兼容端点，确认 .env 中的 Key 属于哪家。

用法：python scripts/check_llm.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm import LLMClient, load_dotenv

load_dotenv()
key = os.getenv("LLM_API_KEY", "").strip()
if not key:
    print("❌ 未找到 LLM_API_KEY（请检查 .env）")
    sys.exit(1)

print(f"开始探测（Key 前缀 {key[:6]}…，长度 {len(key)}）\n")

CANDIDATES = [
    ("阿里云百炼 DashScope", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("DeepSeek", "https://api.deepseek.com", "deepseek-chat"),
    ("Moonshot Kimi", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ("智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
]

winner = None
for name, base, model in CANDIDATES:
    client = LLMClient(model=model, base_url=base)
    if not client.available:
        print(f"[跳过] {name}: openai 包不可用")
        continue
    try:
        text = client.chat("你是测试助手。", "只回复两个字：可用")
        print(f"[✅ 可用] {name} | model={model} | 回复={text.strip()[:20]}")
        winner = (name, base, model)
        break
    except Exception as e:
        print(f"[不可用] {name}: {type(e).__name__}: {str(e)[:110]}")

print()
if winner:
    name, base, model = winner
    print(f"🏆 结论：请将 .env 配置为——")
    print(f"    LLM_BASE_URL={base}")
    print(f"    LLM_MODEL={model}")
else:
    print("❌ 所有候选端点均不可用：请检查 Key 是否正确/是否过期/网络是否可达")
    sys.exit(1)
