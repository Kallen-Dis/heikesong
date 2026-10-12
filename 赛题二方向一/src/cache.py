# -*- coding: utf-8 -*-
"""语义缓存：同一问题在同一语义版本下只编译执行一次。

设计要点（与"随便加个 lru_cache"的区别）：

1. **键里带语义版本**：本体（metrics/synonyms/learned）任何文件的 mtime 变化、
   或数据仓库文件发生变化 → 版本号变 → 旧缓存自动失效，杜绝"改了本体还在答旧口径"；
2. **只缓存确定答案**：澄清分支不入缓存，避免把某次用户选择固化成系统默认
   （这会把"澄清"退化成"猜测"，与平台原则冲突）；
3. **可观测**：命中率 / 淘汰数 / 逐题命中明细，供性能与质量分析。
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def cache_version(ontology_mtimes: dict[str, float], db_path: Path | None = None) -> str:
    """由本体文件 mtime + 数据仓库指纹生成语义版本号（短哈希）。"""
    parts = [f"{Path(p).name}:{m}" for p, m in sorted(ontology_mtimes.items())]
    if db_path is not None:
        try:
            st = db_path.stat()
            parts.append(f"{db_path.name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            pass
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.lookups if self.lookups else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"hits": self.hits, "misses": self.misses, "evictions": self.evictions,
                "lookups": self.lookups, "hit_rate": round(self.hit_rate, 4)}


@dataclass
class SemanticCache:
    """LRU 缓存（键由调用方构造，值通常是 Answer）。"""

    maxsize: int = 256
    stats: CacheStats = field(default_factory=CacheStats)
    _store: OrderedDict = field(default_factory=OrderedDict, repr=False)

    def make_key(self, question: str, profile: str, version: str,
                 auto_resolve: bool = False) -> tuple:
        normalized = " ".join((question or "").split())
        return (normalized, profile, auto_resolve, version)

    def get(self, key: tuple) -> Any | None:
        if key not in self._store:
            self.stats.misses += 1
            return None
        self._store.move_to_end(key)
        self.stats.hits += 1
        return self._store[key]

    def put(self, key: tuple, value: Any) -> None:
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)
            self.stats.evictions += 1

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: tuple) -> bool:
        return key in self._store
