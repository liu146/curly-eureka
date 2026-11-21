# -*- coding: utf-8 -*-
"""Agent 运行时：规划 → 调工具 → 观察 → 反思 → 作答。

这是一个"有边界"的工具调用型 Agent：
- 规划器把问题拆成确定的工具调用序列（可解释）；
- 运行时逐步执行并记录轨迹（可审计）；
- 反思器检查数据覆盖与引用完整性，不满足时补调工具（可纠错）；
- 所有数字都来自工具返回值，答案由模板组装（不可幻觉）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from ..analysis import metrics
from ..config import Config
from . import planner
from .planner import Plan, PlanStep, Slots
from .tools import ToolResult, Toolbox

GRADE_TEXT = {"A": "优", "B": "良", "C": "一般", "D": "较差"}


@dataclass
class TraceStep:
    index: int
    thought: str
    action: str
    args: Dict
    ok: bool
    observation: str
    elapsed_ms: int = 0

    def to_dict(self) -> Dict:
        return {
            "step": self.index,
            "thought": self.thought,
            "action": self.action,
            "args": self.args,
            "ok": self.ok,
            "observation": self.observation,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class Answer:
    question: str
    text: str
    intents: List[str]
    slots: Slots
    trace: List[TraceStep]
    citations: List[Dict]
    checks: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "question": self.question,
            "answer": self.text,
            "intents": self.intents,
            "cities": self.slots.cities,
            "date_label": self.slots.date_label,
            "trace": [t.to_dict() for t in self.trace],
            "citations": self.citations,
            "checks": self.checks,
        }


class Session:
    """极简对话记忆：支持"那杭州呢？"这类省略城市的追问。"""

    def __init__(self):
        self.last_city: Optional[str] = None
        self.turns: List[Answer] = []

    def remember(self, answer: Answer) -> None:
        if answer.slots.cities:
            self.last_city = answer.slots.cities[0]
        self.turns.append(answer)


# ------------------------------------------------------------------ 工具表
def _fmt_table(headers: List[str], rows: List[List[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _find(observations: List[Tuple[PlanStep, ToolResult]], tool: str, city: Optional[str] = None):
    for step, res in observations:
        if step.tool != tool or not res.ok:
            continue
        if city is None:
            return res
        target = (res.data or {}).get("city")
        if target == city:
            return res
    return None


# ------------------------------------------------------------------ 组装答案
class Composer:
    def __init__(self, config: Config):
        self.config = config

    def _source_line(self, citations: List[Dict]) -> str:
        if not citations:
            return "> 数据来源：本地缓存（未获取到在线数据）"
        parts = []
        for c in citations[:3]:
            parts.append(f"[{c['source']}]({c['url']})")
        issue = citations[0].get("fetched_at", "")
        return "> 数据来源：" + "；".join(parts) + (f"（采集于 {issue}）" if issue else "")

    def _forecast_table(self, rows: List[Dict]) -> str:
        body = []
        for r in rows:
            body.append([
                r["date"][5:], r["weekday"], r["weather"],
                f"{r['low']}~{r['high']}℃",
                f"{r['score']}（{r['grade']}·{GRADE_TEXT.get(r['grade'], '')}）",
            ])
        return _fmt_table(["日期", "星期", "天气", "气温", "出行指数"], body)

    # ---------------------------------------------------------- 各意图
    def compose(self, plan: Plan, observations: List[Tuple[PlanStep, ToolResult]]) -> str:
        intents = plan.intents
        sections: List[str] = []
        citations: List[Dict] = []

        for _, res in observations:
            citations.extend(res.citations)

        if "brief" in intents:
            return self._compose_brief(plan, observations)

        if "compare" in intents and _find(observations, "compare_cities"):
            return self._compose_compare(plan, observations)

        for city in plan.slots.cities:
            fc = _find(observations, "get_forecast", city)
            if fc is None:
                continue
            rows = fc.data["rows"]
            if plan.slots.weekend_only:
                rows = [r for r in rows if r["weekday"] in ("周六", "周日")]
            if not rows:
                rows = fc.data["rows"]

            sections.append(self._city_section(plan, city, rows, observations))

        if not sections:
            return "抱歉，没有查询到可用数据。请确认城市名称，或先运行爬虫更新数据。"

        text = "\n\n".join(sections)
        if plan.notes:
            text = "说明：" + "；".join(plan.notes) + "\n\n" + text

        uniq = []
        seen = set()
        for c in citations:
            if c["url"] and c["url"] not in seen:
                seen.add(c["url"])
                uniq.append(c)
        return text + "\n\n" + self._source_line(uniq)

    def _city_section(self, plan: Plan, city: str, rows: List[Dict],
                      observations) -> str:
        intents = plan.intents
        lines: List[str] = []
        head = f"## {city} · {plan.slots.date_label}"

        # 结论句
        if "rain" in intents:
            rainy = [r for r in rows if metrics.is_rainy(r["weather"])]
            if rainy:
                dates = "、".join(f"{r['date'][5:]}（{r['weather']}）" for r in rainy)
                lines.append(f"**结论**：{city}在{plan.slots.date_label}内有 {len(rainy)} 天可能降水：{dates}，"
                             f"建议随身带伞。")
            else:
                lines.append(f"**结论**：{city}在{plan.slots.date_label}内没有降水天气，不需要带伞。")

        best = _find(observations, "best_day", city)
        if "best_day" in intents and best:
            ranked = best.data["rows"]
            if plan.slots.weekend_only:
                ranked = [r for r in ranked if r["weekday"] in ("周六", "周日")] or ranked
            top = ranked[0]
            alt = ranked[1] if len(ranked) > 1 else None
            extra = f"；次选 {alt['date'][5:]}（{alt['score']} 分）" if alt else ""
            lines.append(f"**最佳出行日**：{top['date'][5:]}（{top['weekday']}，{top['weather']}，"
                         f"{top['low']}~{top['high']}℃，出行指数 {top['score']}）{extra}。")

        if "packing" in intents:
            pk = _find(observations, "packing_advice", city)
            if pk:
                lines.append(f"**穿衣建议**：{pk.data['clothing']}；建议携带：{'、'.join(pk.data['items'])}。")

        if "anomaly" in intents:
            an = _find(observations, "climate_anomaly", city)
            if an:
                rows_a = an.data["rows"]
                peak = max(rows_a, key=lambda x: abs(x["delta"]))
                lines.append(f"**冷暖距平**：未来几天平均气温较常年同期 "
                             f"{'偏高' if an.data['avg_delta'] >= 0 else '偏低'} "
                             f"{abs(an.data['avg_delta'])}℃（{rows_a[0]['verdict']}），"
                             f"其中 {peak['date'][5:]} 偏差最大（{peak['delta']:+.1f}℃）。")

        if "trend" in intents:
            his = _find(observations, "get_history", city)
            if his:
                lines.append(self._trend_sentence(city, his.data))

        if not ({"rain", "best_day", "packing", "anomaly", "trend"} & set(intents)):
            from collections import Counter

            common = Counter(r["weather"] for r in rows).most_common(1)[0][0]
            best_row = max(rows, key=lambda r: r["score"])
            lows = min(r["low"] for r in rows)
            highs = max(r["high"] for r in rows)
            lines.append(f"**概况**：{city}未来 {len(rows)} 天以{common}为主，气温 {lows}~{highs}℃，"
                         f"其中 {best_row['date'][5:]}（{best_row['weekday']}）出行指数最高，"
                         f"为 {best_row['score']} 分。")

        if not (set(plan.intents) <= {"trend"}):
            lines.append("")
            lines.append(self._forecast_table(rows))

        # 出行理由（取第一条的扣分项，展示可解释性）
        if "trend" not in plan.intents and rows:
            reasons = rows[0].get("reasons") or []
            if reasons:
                lines.append("")
                lines.append(f"*{rows[0]['date'][5:]} 出行指数说明：" + "；".join(reasons) + "。*")

        return head + "\n\n" + "\n".join(lines)

    def _trend_sentence(self, city: str, data: Dict) -> str:
        seasons = data.get("seasons") or []
        if not seasons:
            return f"**气候趋势**：{city}历史均温 {data['profile']['mean_temp']}℃。"
        by_year = {int(s["year"]): s for s in seasons if s.get("days", 0) >= 60}
        if len(by_year) >= 2:
            years = sorted(by_year)
            last, prev = years[-1], years[-2]
            delta = by_year[last]["mean_temp"] - by_year[prev]["mean_temp"]
            trend = "偏高" if delta >= 0 else "偏低"
            return (f"**气候趋势**：{city} {last} 年夏季（6-8 月）平均气温 "
                    f"{by_year[last]['mean_temp']}℃，较 {prev} 年{trend} {abs(delta):.1f}℃；"
                    f"夏季降水日数 {int(by_year[last]['rain_days'])} 天。")
        return f"**气候趋势**：{city}历史均温 {data['profile']['mean_temp']}℃。"

    def _compose_compare(self, plan: Plan, observations) -> str:
        cmp_res = _find(observations, "compare_cities")
        rows = cmp_res.data["rows"]
        body = [[r["city"], r["weather"], f"{r['low']}~{r['high']}℃",
                 f"{r['score']}（{r['grade']}）"] for r in rows]
        table = _fmt_table(["城市", "天气", "气温", "出行指数"], body)
        top, second = rows[0], (rows[1] if len(rows) > 1 else None)
        conclusion = (f"**结论**：{cmp_res.data['date']} 这天，"
                      f"{top['city']}最适合出行（{top['score']} 分，{top['weather']}，"
                      f"{top['low']}~{top['high']}℃）")
        if second:
            conclusion += f"，其次是{second['city']}（{second['score']} 分）。"
        else:
            conclusion += "。"

        text = [f"## 城市对比 · {cmp_res.data['date']}", conclusion, "", table]

        # 针对"哪个更暖和/温差更大"这类问题补充温度维度的直接回答
        if "温差" in plan.question and rows:
            widest = max(rows, key=lambda r: r["high"] - r["low"])
            text.insert(2, f"**温差对比**：{widest['city']}的昼夜温差最大，"
                           f"为 {widest['high'] - widest['low']}℃（{widest['low']}~{widest['high']}℃）。")
            text.insert(3, "")
        elif any(k in plan.question for k in ("暖和", "冷", "气温", "温度")) and len(rows) >= 2:
            warm = max(rows, key=lambda r: r["high"] + r["low"])
            cold = min(rows, key=lambda r: r["high"] + r["low"])
            gap = ((warm["high"] + warm["low"]) - (cold["high"] + cold["low"])) / 2
            text.insert(2, f"**气温对比**：{warm['city']}更暖和，日均温 "
                           f"{(warm['high'] + warm['low']) / 2:.1f}℃，比{cold['city']}高 {gap:.1f}℃。")
            text.insert(3, "")

        # 补充各城市最佳日期
        extra = []
        for city in plan.slots.cities:
            best = _find(observations, "best_day", city)
            if best and best.data["rows"]:
                top_day = best.data["rows"][0]
                extra.append(f"- {city}：最佳日期 {top_day['date'][5:]}（{top_day['score']} 分）")
        if extra:
            text += ["", "**各城市未来一周最佳日期**", ""] + extra

        uniq, seen = [], set()
        for _, res in observations:
            for c in res.citations:
                if c["url"] and c["url"] not in seen:
                    seen.add(c["url"])
                    uniq.append(c)
        return "\n".join(text) + "\n\n" + self._source_line(uniq)

    def _compose_brief(self, plan: Plan, observations) -> str:
        city = plan.slots.cities[0]
        fc = _find(observations, "get_forecast", city)
        best = _find(observations, "best_day", city)
        an = _find(observations, "climate_anomaly", city)
        his = _find(observations, "get_history", city)
        if fc is None:
            return "抱歉，简报所需的数据不完整。"

        rows = fc.data["rows"]
        rainy = [r for r in rows if metrics.is_rainy(r["weather"])]
        lines = [
            f"# {city}出行简报（{plan.slots.date_label}）",
            "",
            f"- 预报批次：{fc.data['issue_date']}",
            f"- 气温区间：{min(r['low'] for r in rows)}~{max(r['high'] for r in rows)}℃",
            f"- 降水日数：{len(rainy)} 天",
        ]
        if best:
            t = best.data["rows"][0]
            lines.append(f"- 最佳出行日：{t['date']}（{t['weekday']}，{t['weather']}，{t['score']} 分）")
        if an:
            lines.append(f"- 冷暖距平：较常年同期 {'偏高' if an.data['avg_delta'] >= 0 else '偏低'} "
                         f"{abs(an.data['avg_delta'])}℃")
        if his:
            p = his.data["profile"]
            lines.append(f"- 气候背景：历史均温 {p['mean_temp']}℃，降水日占比 {p['rain_ratio']}%")
        lines += ["", "## 逐日预报", "", self._forecast_table(rows), "", "## 出行建议", ""]
        for r in rows:
            lines.append(f"- {r['date'][5:]} {r['weekday']}：{r['weather']}，{r['low']}~{r['high']}℃，"
                         f"指数 {r['score']}（{'；'.join(r['reasons'][:2])}）")
        if rainy:
            lines.append("")
            lines.append("**提醒**：有降水，出门带伞并预留通勤时间。")

        uniq, seen = [], set()
        for _, res in observations:
            for c in res.citations:
                if c.get("url") and c["url"] not in seen:
                    seen.add(c["url"])
                    uniq.append(c)
        lines += ["", self._source_line(uniq)]
        return "\n".join(lines)


# ------------------------------------------------------------------ Agent
class Agent:
    def __init__(self, toolbox: Toolbox, config: Config, today: Optional[date] = None,
                 max_reflect: int = 2):
        self.toolbox = toolbox
        self.config = config
        self.today = today or date.today()
        self.max_reflect = max_reflect
        self.composer = Composer(config)

    # ---------------------------------------------------------- 反思
    def _reflect(self, plan: Plan, observations) -> Tuple[List[Dict], List[Tuple[str, Dict]]]:
        checks = []
        issues = []

        # 1) 城市覆盖
        missing = []
        for city in plan.slots.cities:
            if _find(observations, "get_forecast", city) is None:
                missing.append(city)
        checks.append({"name": "预报数据覆盖目标城市", "pass": not missing,
                       "detail": "、".join(missing)})
        for city in missing:
            issues.append(("get_forecast", {"city": city, "days": plan.slots.within}))

        # 2) 目标日期是否在预报范围内
        if plan.slots.target_date:
            covered = False
            for city in plan.slots.cities:
                fc = _find(observations, "get_forecast", city)
                if fc and plan.slots.target_date.isoformat() in {r["date"] for r in fc.data["rows"]}:
                    covered = True
            checks.append({"name": "目标日期在预报覆盖范围内", "pass": covered,
                           "detail": plan.slots.target_date.isoformat()})
            if not covered:
                issues.append(("get_forecast", {"city": plan.slots.cities[0], "days": 7}))
        else:
            checks.append({"name": "目标日期在预报覆盖范围内", "pass": True, "detail": "未指定具体日期"})

        # 3) 引用完整性
        has_citation = any(res.citations for _, res in observations if res.ok)
        checks.append({"name": "结论包含可溯源引用", "pass": has_citation, "detail": ""})

        # 4) 数据新鲜度
        fresh = True
        detail = ""
        for city in plan.slots.cities:
            fc = _find(observations, "get_forecast", city)
            if fc:
                gap = (self.today - date.fromisoformat(fc.data["issue_date"])).days
                if gap > 2:
                    fresh = False
                    detail = f"{city} 预报批次距今 {gap} 天"
        checks.append({"name": "预报数据足够新", "pass": fresh, "detail": detail})

        return [{"check": c["name"], "pass": c["pass"], "detail": c.get("detail", "")} for c in checks], issues

    # ---------------------------------------------------------- 主循环
    def ask(self, question: str, session: Optional[Session] = None) -> Answer:
        session = session or Session()
        plan = planner.make_plan(question, self.config, today=self.today,
                                 memory_city=session.last_city)

        trace: List[TraceStep] = []
        observations: List[Tuple[PlanStep, ToolResult]] = []
        idx = 0

        def run(step: PlanStep):
            nonlocal idx
            idx += 1
            started = time.monotonic()
            res = self.toolbox.call(step.tool, **step.args)
            elapsed = int((time.monotonic() - started) * 1000)
            observations.append((step, res))
            trace.append(TraceStep(
                index=idx,
                thought=step.reason,
                action=step.tool,
                args=step.args,
                ok=res.ok,
                observation=res.summary if res.ok else f"失败：{res.error}",
                elapsed_ms=elapsed,
            ))
            return res

        for step in plan.steps:
            run(step)

        checks: List[Dict] = []
        if self.max_reflect <= 0:
            checks, _ = self._reflect(plan, observations)
        for round_no in range(self.max_reflect):
            checks, issues = self._reflect(plan, observations)
            if not issues:
                break
            for tool, args in issues[:3]:
                if tool == "get_forecast" and _find(observations, "get_forecast", args["city"]):
                    continue
                plan.steps.append(PlanStep(tool, args, f"反思补全（第 {round_no + 1} 轮）"))
                run(plan.steps[-1])

        text = self.composer.compose(plan, observations)

        if "brief" in plan.intents:
            idx += 1
            saved = self.toolbox.call("save_brief", content=text)
            trace.append(TraceStep(idx, "把简报写入文件", "save_brief", {},
                                   saved.ok, saved.summary))
            text += f"\n\n> 简报文件：`{saved.data['path']}`"

        citations, seen = [], set()
        for _, res in observations:
            for c in res.citations:
                if c.get("url") and c["url"] not in seen:
                    seen.add(c["url"])
                    citations.append(c)

        answer = Answer(question, text, plan.intents, plan.slots, trace, citations, checks)
        session.remember(answer)
        return answer
