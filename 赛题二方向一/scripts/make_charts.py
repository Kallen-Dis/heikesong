# -*- coding: utf-8 -*-
"""生成路演用图表（PNG）：战绩对比 / 分类战绩 / 消融实验 / 消融分类。

数据源（自动取最新）：
    eval/matrix_*.csv       —— 四组实验矩阵（A/B/C/D）
    eval/ablation_*.md      —— 消融实验报告
产出：
    eval/charts/fig1_headline.png    主战绩对比
    eval/charts/fig2_category.png    分类战绩（6 类 × 4 组）
    eval/charts/fig3_ablation.png    消融实验总览
    eval/charts/fig4_ablation_cat.png 消融分类战绩

用法：python scripts/make_charts.py
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

# 中文 Windows 控制台默认 GBK，输出 ✅ 会 UnicodeEncodeError 并让脚本以非零码退出。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
OUT = EVAL / "charts"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

GROUPS = ["D", "A", "B", "C"]
GLABEL = {"D": "D 语枢\n（语义编译器）", "A": "A 裸 DDL\n（现状基线）",
          "B": "B +中文注释\n与关系", "C": "C +本体全文\n入提示词"}
COLORS = {"D": "#1b8a5a", "A": "#8d99ae", "B": "#e0a458", "C": "#c1443c"}
CAT_ZH = {"A_synonym": "A 同义词", "B_metric_ambiguity": "B 口径歧义",
          "C_entity_ambiguity": "C 实体歧义", "D_time": "D 时间理解",
          "E_multi_hop": "E 多跳推理", "F_trap": "F 陷阱题"}
PROFILE_ZH = {"full": "全量系统", "no_synonyms": "去同义词表",
              "no_axioms": "去公理/关系指标", "no_clarify": "去澄清器"}


def latest(pattern: str) -> Path:
    files = sorted(EVAL.glob(pattern))
    if not files:
        raise FileNotFoundError(f"未找到 {pattern}（请先跑对应实验脚本）")
    return files[-1]


def load_matrix() -> list[dict]:
    rows = list(csv.DictReader(latest("matrix_2*.csv").open(encoding="utf-8-sig")))
    return rows


def rate(rows: list[dict], g: str) -> tuple[int, int]:
    vals = [r.get(f"{g.lower()}_verdict") for r in rows
            if r.get(f"{g.lower()}_verdict") in ("PASS", "FAIL")]
    return sum(1 for v in vals if v == "PASS"), len(vals)


def parse_ablation() -> tuple[dict[str, tuple[int, int]], dict[str, dict[str, tuple[int, int]]]]:
    text = latest("ablation_*.md").read_text(encoding="utf-8")
    overall: dict[str, tuple[int, int]] = {}
    for m in re.finditer(r"\|\s*\*\*(\w+)\*\*\s*\|[^|]*\|\s*(\d+)/(\d+)", text):
        overall[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    per_cat: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0] in CAT_ZH:
            for prof, cell in zip(PROFILE_ZH, cells[1:]):
                mm = re.match(r"(\d+)/(\d+)", cell)
                if mm:
                    per_cat[cells[0]][prof] = (int(mm.group(1)), int(mm.group(2)))
    if len(overall) < 4:
        raise RuntimeError("消融报告解析失败，请检查 ablation_*.md 格式")
    return overall, per_cat


def _annotate(ax, bars, values):
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.5,
                f"{v:.1f}%", ha="center", va="bottom", fontsize=11, fontweight="bold")


def fig1_headline(rows: list[dict]) -> None:
    rates = {g: rate(rows, g) for g in GROUPS}
    vals = [rates[g][0] / max(1, rates[g][1]) * 100 for g in GROUPS]
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=150)
    bars = ax.bar([GLABEL[g] for g in GROUPS], vals, color=[COLORS[g] for g in GROUPS], width=0.58)
    _annotate(ax, bars, vals)
    ax.set_ylim(0, 112)
    ax.set_ylabel("正确率（%）")
    ax.set_title("语枢 vs 三种 LLM 直连路线 · AmbiQuery 种子 24 题\n"
                 "（DeepSeek-chat · 每组 3 次采样取多数）", fontsize=13, fontweight="bold")
    for b, g, v in zip(bars, GROUPS, vals):
        n, t = rates[g]
        if v >= 12:
            ax.text(b.get_x() + b.get_width() / 2, 3, f"{n}/{t}", ha="center", color="white",
                    fontsize=10, fontweight="bold")
        else:
            ax.text(b.get_x() + b.get_width() / 2, v + 8.5, f"{n}/{t}", ha="center",
                    color="#777777", fontsize=9)
    ax.annotate("本体塞进提示词 = 最差路线", xy=(3, 12), xytext=(2.15, 45),
                arrowprops=dict(arrowstyle="->", color="#c1443c"), color="#c1443c",
                fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "fig1_headline.png")
    plt.close(fig)


def fig2_category(rows: list[dict]) -> None:
    cats = [c for c in CAT_ZH if any(r["category"] == c for r in rows)]
    per: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)
    for c in cats:
        sub = [r for r in rows if r["category"] == c]
        for g in GROUPS:
            per[c][g] = rate(sub, g)
    x = range(len(cats))
    width = 0.2
    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
    for i, g in enumerate(GROUPS):
        offs = [xi + (i - 1.5) * width for xi in x]
        vals = [per[c][g][0] / max(1, per[c][g][1]) * 100 for c in cats]
        ax.bar(offs, vals, width=width, color=COLORS[g], label=GLABEL[g].replace("\n", ""))
    ax.set_xticks(list(x))
    ax.set_xticklabels([CAT_ZH[c] for c in cats])
    ax.set_ylim(0, 112)
    ax.set_ylabel("正确率（%）")
    ax.set_title("分类战绩：六类考点 × 四组路线", fontsize=13, fontweight="bold")
    ax.legend(fontsize=9, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "fig2_category.png")
    plt.close(fig)


def fig3_ablation(overall: dict[str, tuple[int, int]]) -> None:
    profs = list(PROFILE_ZH)
    vals = [overall[p][0] / max(1, overall[p][1]) * 100 for p in profs]
    cols = ["#1b8a5a", "#4c9f70", "#7fb069", "#1b8a5a"]
    fig, ax = plt.subplots(figsize=(9, 5.4), dpi=150)
    bars = ax.bar([PROFILE_ZH[p] for p in profs], vals, color=cols, width=0.55)
    _annotate(ax, bars, vals)
    for b, p in zip(bars, profs):
        n, t = overall[p]
        ax.text(b.get_x() + b.get_width() / 2, 3, f"{n}/{t}", ha="center", color="white",
                fontsize=10, fontweight="bold")
    ax.set_ylim(0, 112)
    ax.set_ylabel("正确率（%）")
    ax.set_title("消融实验：逐构件拆除（AmbiQuery-120 · 117 道自动判定题）",
                 fontsize=13, fontweight="bold")
    ax.annotate("准确率不变，但 36.8% 的题\n在未确认口径下作答（风险面）",
                xy=(3, 100), xytext=(2.05, 46),
                arrowprops=dict(arrowstyle="->", color="#c1443c"),
                color="#c1443c", fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "fig3_ablation.png")
    plt.close(fig)


def fig4_ablation_cat(per_cat: dict[str, dict[str, tuple[int, int]]]) -> None:
    cats = list(CAT_ZH)
    profs = list(PROFILE_ZH)
    cols = ["#1b8a5a", "#4c9f70", "#7fb069", "#a3b18a"]
    x = range(len(cats))
    width = 0.2
    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
    for i, p in enumerate(profs):
        offs = [xi + (i - 1.5) * width for xi in x]
        vals = []
        for c in cats:
            n, t = per_cat.get(c, {}).get(p, (0, 1))
            vals.append(n / max(1, t) * 100)
        ax.bar(offs, vals, width=width, color=cols[i], label=PROFILE_ZH[p])
    ax.set_xticks(list(x))
    ax.set_xticklabels([CAT_ZH[c] for c in cats])
    ax.set_ylim(0, 112)
    ax.set_ylabel("正确率（%）")
    ax.set_title("消融分类战绩：哪个构件撑起哪类考点", fontsize=13, fontweight="bold")
    ax.legend(fontsize=9, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "fig4_ablation_cat.png")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = load_matrix()
    overall, per_cat = parse_ablation()
    fig1_headline(rows)
    fig2_category(rows)
    fig3_ablation(overall)
    fig4_ablation_cat(per_cat)
    for f in sorted(OUT.glob("*.png")):
        print(f"✅ {f.relative_to(ROOT)}  ({f.stat().st_size // 1024} KB)")
    print("图表已生成，可用于路演 PPT 与看板。")


if __name__ == "__main__":
    main()
