# -*- coding: utf-8 -*-
"""语枢原型工程公共模块。"""
import sys


def enable_utf8() -> None:
    """把标准输出切到 UTF-8。

    Windows 控制台默认 GBK，脚本里的 ✅/❌/🎯 等符号会触发
    UnicodeEncodeError 并以非零码退出（数据其实已经写好了，用户只看到报错）。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


enable_utf8()

