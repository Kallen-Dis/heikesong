# -*- coding: utf-8 -*-
"""开发后新增独立手写反例评测；不调用API、不自动猜澄清选项。

这不是严格 holdout 或国际泛化测试。报告保存每次运行与首次发现，便于后续
修复留下证据；完整比较手写 gold SQL 的结果表。运行出现失败返回非零。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.benchmark import results_match
from src.db import connect, run_sql
from src.loop import Clarification, QueryLoop


def records(df) -> list[dict] | None:
    if df is None:
        return None
    return df.astype(object).where(pd.notna(df), None).to_dict('records')


def fraction(numerator: int, denominator: int) -> dict:
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else None}


def evaluate(items: list[dict], conn) -> dict:
    loop = QueryLoop(conn)
    rows = []
    for item in items:
        row = {**item, 'initial_type': None, 'final_type': None, 'pass': False,
               'full_result_correct': None, 'actual_rows': None, 'gold_rows': None,
               'sql': None, 'detail': ''}
        try:
            ans = loop.ask(item['question'], auto_resolve=False)
            initial_type = 'clarification' if isinstance(ans, Clarification) else ans.type
            row['initial_type'] = initial_type
            initial_correct = initial_type == item['expect']
            if isinstance(ans, Clarification):
                row['clarification_points'] = [p.id for p in ans.points]
                if item.get('choices') is not None:
                    row['applied_choices'] = item['choices']
                    ans = loop.resolve(ans, item['choices'])
                else:
                    row['final_type'] = 'clarification'
            if not isinstance(ans, Clarification):
                row['final_type'] = ans.type
                row['text'] = ans.text
                row['sql'] = ans.sql
                row['actual_rows'] = records(ans.df)
                row['disclosure'] = ans.disclosure
            if item.get('gold_sql'):
                gold = run_sql(conn, item['gold_sql'])
                row['gold_rows'] = records(gold)
                row['full_result_correct'] = (
                    not isinstance(ans, Clarification) and ans.type == 'answer'
                    and results_match(ans.df, gold))
                row['pass'] = initial_correct and bool(row['full_result_correct'])
            else:
                row['pass'] = initial_correct and row['final_type'] == 'insufficient'
            if not row['pass']:
                row['detail'] = (f"期望初始类型 {item['expect']}，实际 {row['initial_type']}；"
                                 f"最终 {row['final_type']}；完整结果正确={row['full_result_correct']}")
        except Exception as exc:
            row['detail'] = f'{type(exc).__name__}: {exc}'
            row['final_type'] = 'error'
        rows.append(row)

    answerable = [r for r in rows if r['gold_sql'] is not None]
    answered = [r for r in answerable if r['final_type'] == 'answer']
    all_answered = [r for r in rows if r['final_type'] == 'answer']
    blocked = [r for r in rows if r['expect'] == 'insufficient']
    clarify = [r for r in rows if r['expect'] == 'clarification']
    metrics = {
        'answer_coverage': fraction(len(answered), len(answerable)),
        'answer_correctness_given_answer': fraction(sum(bool(r['full_result_correct']) for r in all_answered), len(all_answered)),
        'answerable_correctness': fraction(sum(bool(r['full_result_correct']) for r in answerable), len(answerable)),
        'blocked_execution_rate': fraction(sum(r['final_type'] == 'answer' for r in blocked), len(blocked)),
        'expected_block_correctness': fraction(sum(r['final_type'] == 'insufficient' for r in blocked), len(blocked)),
        'clarification_correct': fraction(sum(r['initial_type'] == 'clarification' for r in clarify), len(clarify)),
        'overall_pass': fraction(sum(r['pass'] for r in rows), len(rows)),
    }
    return {'generated_at': datetime.now(timezone.utc).isoformat(), 'metrics': metrics,
            'scope': '开发后新增的独立手写反例；非严格holdout，不代表国际泛化；gold与核心使用同一仓库。',
            'metric_definitions': {
                'answerable': '有手写gold的直接可答题，以及带明确choices的澄清后可答题。',
                'answer_coverage': '可答题中最终实际返回answer的比例，不把必须拒答题计入分母。',
                'answer_correctness_given_answer': '所有已输出answer的题中，完整结果表正确的比例；必须阻断题输出answer直接判错误。',
                'blocked_execution_rate': '必须阻断题中仍返回answer的比例；error与clarification均不算成功阻断。',
                'clarification_correct': '期望澄清的题中，首次实际返回clarification的比例；是否执行正确由完整结果评估。',
                'overall_pass': '初始响应类型正确，且可答题完整gold匹配，必须阻断题最终为insufficient。',
            }, 'rows': rows, 'failures': [r for r in rows if not r['pass']]}


def render_metric(metric: dict) -> str:
    value = metric['value']
    return ('null（零分母）' if value is None else f"{value:.1%}") + f"（{metric['numerator']}/{metric['denominator']}）"


def main() -> int:
    ap = argparse.ArgumentParser(description='24条独立改写/负向问题评测，不使用API')
    ap.add_argument('--file', type=Path, default=ROOT / 'benchmark/adversarial_v2.jsonl')
    ap.add_argument('--out-prefix', type=Path, default=ROOT / 'eval/adversarial_v2')
    args = ap.parse_args()
    raw = args.file.read_text(encoding='utf-8')
    items = [json.loads(line) for line in raw.splitlines() if line.strip()]
    ids = [it['id'] for it in items]
    if len(ids) != len(set(ids)):
        raise ValueError('样本ID重复')
    for it in items:
        if it['expect'] not in {'answer', 'clarification', 'insufficient'}:
            raise ValueError(f"无效expect：{it['id']}")
        if it['expect'] == 'clarification' and (not it.get('choices') or not it.get('gold_sql')):
            raise ValueError(f"澄清样本必须显式给出choices与gold：{it['id']}")
    conn = connect()
    try:
        report = evaluate(items, conn)
    finally:
        conn.close()
    report['dataset_sha256'] = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    json_path = args.out_prefix.with_suffix('.json')
    md_path = args.out_prefix.with_suffix('.md')
    json_path.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if json_path.exists():
        previous = json.loads(json_path.read_text(encoding='utf-8'))
        history = previous.get('runs', [])
    history.append(report)
    document = {'initial_run': history[0], 'latest_run': report, 'runs': history}
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str,
                                    allow_nan=False) + '\n', encoding='utf-8')
    first = history[0]
    lines = ['# 独立改写与负向业务问题评测', '', report['scope'], '',
             f"最新运行：{report['generated_at']}；运行次数：{len(history)}；样本：{len(items)}。", '',
             '| 指标 | 首次运行 | 最新运行 |', '|---|---|---|']
    for key, value in report['metrics'].items():
        lines.append(f"| {key} | {render_metric(first['metrics'][key])} | {render_metric(value)} |")
    for label, run in [('首次发现（保留，不随修复清除）', first), ('最新失败清单', report)]:
        lines += ['', f'## {label}', '']
        if not run['failures']:
            lines.append('无失败项。')
        for row in run['failures']:
            lines.append(f"- **{row['id']}** {row['question']} — {row['detail']}；判定理由：{row['reason']}")
    lines += ['', '## 判定与分母', '']
    lines.extend(f'- {key}：{value}' for key, value in report['metric_definitions'].items())
    lines += ['', '## 最新逐题结果', '', '| ID | 类型 | 问题 | 结果 |', '|---|---|---|---|']
    for row in report['rows']:
        lines.append(f"| {row['id']} | {row['expect']} | {row['question']} | {'PASS' if row['pass'] else 'FAIL'} |")
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    for key, value in report['metrics'].items():
        print(f'{key}: {render_metric(value)}')
    for row in report['failures']:
        print(f"FAIL {row['id']} {row['question']} — {row['detail']}")
    print(f'报告：{json_path}\n{md_path}')
    return int(bool(report['failures']))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
