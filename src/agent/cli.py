# -*- coding: utf-8 -*-
"""Agent 命令行入口。

单轮：
    python -m src.agent.cli "北京这周末适合出去玩吗，要带伞吗？"
    python -m src.agent.cli "上海和杭州哪个更适合周末出游" --trace
交互（保留上下文）：
    python -m src.agent.cli -i
"""
from __future__ import annotations

import argparse
import json
import sys

from ..config import load_config
from ..crawler.store import Store
from ..utils import force_utf8_stdout
from .loop import Agent, Session
from .tools import Toolbox


def render_trace(answer) -> str:
    lines = ["", "── Agent 执行轨迹 " + "─" * 40]
    for t in answer.trace:
        flag = "✓" if t.ok else "✗"
        args = ", ".join(f"{k}={v}" for k, v in t.args.items()) or "-"
        lines.append(f"[{t.index}] {flag} {t.action}({args})  {t.elapsed_ms}ms")
        lines.append(f"    思考：{t.thought}")
        lines.append(f"    观察：{t.observation}")
    lines.append("── 自检项 " + "─" * 44)
    for c in answer.checks:
        lines.append(f"  {'✓' if c['pass'] else '✗'} {c['check']} {c['detail']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="城市天气出行 Agent")
    parser.add_argument("question", nargs="?", help="自然语言问题")
    parser.add_argument("-i", "--interactive", action="store_true", help="交互模式")
    parser.add_argument("--trace", action="store_true", help="打印 Agent 执行轨迹")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    cfg = load_config()
    store = Store(cfg.db_path)
    if store.counts()["forecasts"] == 0:
        print("数据库为空，请先运行：python -m src.crawler.cli crawl-all", file=sys.stderr)
        return 1

    agent = Agent(Toolbox(store, cfg), cfg)
    session = Session()

    if args.interactive or not args.question:
        print("城市天气出行 Agent（输入 exit 退出）")
        while True:
            try:
                q = input("\n你> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in {"exit", "quit", "退出"}:
                break
            if not q:
                continue
            answer = agent.ask(q, session)
            print("\n" + answer.text)
            if args.trace:
                print(render_trace(answer))
        return 0

    answer = agent.ask(args.question, session)
    if args.json:
        print(json.dumps(answer.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(answer.text)
        if args.trace:
            print(render_trace(answer))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
