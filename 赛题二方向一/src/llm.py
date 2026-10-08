# -*- coding: utf-8 -*-
"""LLM 客户端（OpenAI 兼容端点：阿里云百炼 / DeepSeek / 任意兼容服务）。

环境变量（或 .env 文件）：
    LLM_API_KEY   必填（缺失时 available=False，原型仍可离线运行）
    LLM_BASE_URL  默认百炼兼容端点
    LLM_MODEL     默认 qwen-plus
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    """极简 .env 加载器（不覆盖已存在的环境变量）。"""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


class LLMClient:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, temperature: float = 0.0) -> None:
        load_dotenv()
        self.model = model or os.getenv("LLM_MODEL", "qwen-plus")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.api_key = (api_key or os.getenv("LLM_API_KEY", "")).strip()
        self.temperature = temperature
        self._client = None
        if self.api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            except Exception:  # 未安装 openai 或初始化失败 → 降级离线
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def chat(self, system: str, user: str, temperature: float | None = None) -> str:
        if not self._client:
            raise RuntimeError("LLM 不可用：请在 .env 中配置 LLM_API_KEY")
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature if temperature is None else temperature,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""

    def sql(self, system: str, user: str) -> str:
        """请求 LLM 生成 SQL 并剥离代码块围栏。"""
        text = self.chat(system, user)
        text = re.sub(r"```(?:sql)?", "", text, flags=re.IGNORECASE).strip("` \n\t")
        return text.strip().rstrip(";").strip()


def get_client() -> LLMClient:
    return LLMClient()
