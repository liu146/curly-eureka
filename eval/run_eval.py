# -*- coding: utf-8 -*-
"""Agent 评测脚本：20 条标注问题，统计意图准确率、工具召回率、引用覆盖率等。

用法：
    python -m eval.run_eval
结果写入 output/eval_results.json 与 output/eval_report.md。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.agent.loop import Agent
from src.agent.tools import Toolbox
from src.config import load_config
from src.crawler.store import Store
from src.utils import force_utf8_stdout

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = Path(__file__).parent / "questions.jsonl"


def main() -> int:
    force_utf8_stdout()
    cfg = load_config()
    store = Store(cfg.db_path)
    agent = Agent(Toolbox(store, cfg), cfg)

    cases = [json.loads(line) for line in QUESTIONS.read_text("utf-8").splitlines() if line.strip()]
    results = []
    for case in cases:
        started = time.monotonic()
        ans = agent.ask(case["q"])
        elapsed = time.monotonic() - started

        actions = [t.action for t in ans.trace]
        intent_ok = all(i in ans.intents for i in case["intents"])
        tool_hit = [t for t in case["tools"] if t in actions]
        tool_recall = len(tool_hit) / len(case["tools"]) if case["tools"] else 1.0
        citation_ok = len(ans.citations) > 0
        length_ok = len(ans.text) >= 80
        trace_ok = all(t.ok for t in ans.trace)
        checks_ok = all(c["pass"] for c in ans.checks) if ans.checks else False
        success = intent_ok and tool_recall == 1.0 and citation_ok and length_ok and trace_ok

        results.append({
            "id": case["id"],
            "question": case["q"],
            "expected_intents": case["intents"],
            "predicted_intents": ans.intents,
            "intent_ok": intent_ok,
            "tool_recall": round(tool_recall, 2),
            "missing_tools": [t for t in case["tools"] if t not in actions],
            "actions": actions,
            "citation_ok": citation_ok,
            "length_ok": length_ok,
            "trace_ok": trace_ok,
            "checks_ok": checks_ok,
            "success": success,
            "steps": len(ans.trace),
            "elapsed_s": round(elapsed, 3),
            "answer_chars": len(ans.text),
        })
        print(f"[{case['id']:02d}] {'✓' if success else '✗'} {case['q'][:26]:28s} "
              f"intent={intent_ok} tools={tool_recall:.0%} steps={len(ans.trace)} {elapsed:.2f}s")

    n = len(results)
    summary = {
        "total": n,
        "success_rate": round(sum(r["success"] for r in results) / n * 100, 1),
        "intent_accuracy": round(sum(r["intent_ok"] for r in results) / n * 100, 1),
        "tool_recall": round(sum(r["tool_recall"] for r in results) / n * 100, 1),
        "citation_rate": round(sum(r["citation_ok"] for r in results) / n * 100, 1),
        "trace_ok_rate": round(sum(r["trace_ok"] for r in results) / n * 100, 1),
        "avg_steps": round(sum(r["steps"] for r in results) / n, 2),
        "avg_elapsed_s": round(sum(r["elapsed_s"] for r in results) / n, 3),
        "avg_answer_chars": round(sum(r["answer_chars"] for r in results) / n, 1),
    }

    cfg.ensure_dirs()
    (cfg.output_dir / "eval_results.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), "utf-8"
    )

    lines = [
        "# Agent 评测报告", "",
        f"- 问题数：{n}",
        f"- 任务成功率：{summary['success_rate']}%",
        f"- 意图识别准确率：{summary['intent_accuracy']}%",
        f"- 工具调用召回率：{summary['tool_recall']}%",
        f"- 引用覆盖率：{summary['citation_rate']}%",
        f"- 轨迹全部成功：{summary['trace_ok_rate']}%",
        f"- 平均执行步数：{summary['avg_steps']}，平均耗时：{summary['avg_elapsed_s']} s",
        "", "| # | 问题 | 意图正确 | 工具召回 | 步数 | 耗时(s) | 成功 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r['id']} | {r['question']} | {'✓' if r['intent_ok'] else '✗'} | "
                     f"{r['tool_recall']:.0%} | {r['steps']} | {r['elapsed_s']} | "
                     f"{'✓' if r['success'] else '✗'} |")
    (cfg.output_dir / "eval_report.md").write_text("\n".join(lines), "utf-8")

    print("\n评测汇总：", json.dumps(summary, ensure_ascii=False))
    print(f"结果写入 {cfg.output_dir / 'eval_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
