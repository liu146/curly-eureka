# -*- coding: utf-8 -*-
"""生成 Word 实验报告（需要 python-docx）。

用法：python build_report.py
读取：output/summary.json、output/eval_results.json、data/crawl_stats.json、output/figures/*.png
输出：report/实验报告_城市天气与出行建议爬虫Agent.docx
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
FIG = ROOT / "output" / "figures"
REPORT_DIR = ROOT / "report"

SONG, HEI, KAI, MONO = "宋体", "黑体", "楷体", "Consolas"
BODY_PT = 12
ACCENT = RGBColor(0x1F, 0x3A, 0x5F)


# ------------------------------------------------------------------ 基础排版
def set_run(run, cn=SONG, en="Times New Roman", size=BODY_PT, bold=False, color=None, italic=False):
    run.font.name = en
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), cn)
    rfonts.set(qn("w:ascii"), en)
    rfonts.set(qn("w:hAnsi"), en)


def body(doc, text, indent=True, size=BODY_PT, after=4, align=None):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.first_line_indent = Pt(size * 2) if indent else Pt(0)
    pf.line_spacing = 1.45
    pf.space_after = Pt(after)
    if align is not None:
        p.alignment = align
    run = p.add_run(text)
    set_run(run, size=size)
    return p


def heading(doc, text, level=1):
    sizes = {1: 16, 2: 14, 3: 12}
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    set_run(run, cn=HEI, en="Times New Roman", size=sizes.get(level, 12), bold=True, color=ACCENT)
    return p


def caption(doc, text, before=2, after=8):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    run = p.add_run(text)
    set_run(run, size=10.5)
    return p


def figure(doc, name, cap, width=15.2):
    path = FIG / name
    if not path.exists():
        body(doc, f"（图 {name} 缺失）")
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(str(path), width=Cm(width))
    caption(doc, cap)


def _shade(cell, color):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    tcpr.append(shd)


def _set_cell_margins(table, top=40, bottom=40, left=80, right=80):
    tblpr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for side, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        mar.append(node)
    tblpr.append(mar)


def table(doc, headers, rows, cap=None, widths=None, font_size=9, header_fill="DCE6F1"):
    if cap:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(cap)
        set_run(run, cn=HEI, size=9.5, bold=True)

    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = True
    _set_cell_margins(t)
    hdr = t.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(str(h))
        set_run(run, cn=HEI, size=font_size, bold=True)
        _shade(hdr[i], header_fill)
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if i > 0 or len(str(val)) < 12 else WD_ALIGN_PARAGRAPH.LEFT
            run = p.add_run(str(val))
            set_run(run, size=font_size)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    # 行内禁止跨页拆分；表头跨页重复
    for row in t.rows:
        trpr = row._tr.get_or_add_trPr()
        trpr.append(OxmlElement("w:cantSplit"))
    hdr_pr = t.rows[0]._tr.get_or_add_trPr()
    th = OxmlElement("w:tblHeader")
    th.set(qn("w:val"), "true")
    hdr_pr.append(th)
    # 小表尽量整表不跨页
    if len(rows) <= 12:
        for row in t.rows[:-1]:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = True
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def code_block(doc, text, size=8.5, max_lines=32):
    lines = text.rstrip().splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["...（略）"]
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Pt(6)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.05
    ppr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), "F4F6F8")
    ppr.append(shd)
    run = p.add_run("\n".join(lines))
    set_run(run, cn=MONO, en=MONO, size=size)
    return p


def snippet(rel, start, end=None, max_chars=1600):
    text = (ROOT / rel).read_text("utf-8")
    i = text.find(start)
    if i < 0:
        return ""
    if end:
        j = text.find(end, i)
        piece = text[i:j] if j > 0 else text[i:]
    else:
        piece = text[i:i + max_chars]
    return piece.strip()


def add_page_number(section):
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    set_run(run, size=9)
    for kind, value in (("begin", None), ("instr", "PAGE"), ("end", None)):
        if kind == "instr":
            node = OxmlElement("w:instrText")
            node.set(qn("xml:space"), "preserve")
            node.text = value
        else:
            node = OxmlElement("w:fldChar")
            node.set(qn("w:fldCharType"), kind)
        run._r.append(node)


def page_break(doc):
    doc.add_page_break()


# ------------------------------------------------------------------ 数据
def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except Exception:
        return default or {}


summary = load_json(ROOT / "output" / "summary.json", {})
eval_data = load_json(ROOT / "output" / "eval_results.json", {})
crawl = load_json(ROOT / "data" / "crawl_stats.json", {})
config = {}
try:
    import yaml
    config = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
except Exception:
    pass

counts = summary.get("counts", {})
profile = summary.get("profile", [])
season = summary.get("season", [])
hist = summary.get("history", {})
fc = summary.get("forecast", {})
eval_sum = eval_data.get("summary", {})
eval_rows = eval_data.get("results", [])

crawl_info = summary.get("crawl", {}) or {}
req = crawl_info.get("requests", 0)
ok_tasks = crawl_info.get("ok", 0)
fail_tasks = crawl_info.get("fail", 0)
crawl_seconds = crawl_info.get("seconds", 0)
avg_ms = crawl_info.get("avg_ms", 0)
total_attempts = req
rows = counts.get("history", 0) + counts.get("forecasts", 0)
success_rate = ok_tasks / max(ok_tasks + fail_tasks, 1) * 100


def fmt(x, n=1):
    try:
        return f"{float(x):.{n}f}"
    except Exception:
        return str(x)


# ------------------------------------------------------------------ 文档
doc = Document()
sec = doc.sections[0]
sec.page_width = Cm(21)
sec.page_height = Cm(29.7)
sec.top_margin = Cm(2.5)
sec.bottom_margin = Cm(2.4)
sec.left_margin = Cm(2.8)
sec.right_margin = Cm(2.6)

style = doc.styles["Normal"]
style.font.name = "Times New Roman"
style.font.size = Pt(BODY_PT)
_rpr = style.element.get_or_add_rPr()
_rfonts = _rpr.find(qn("w:rFonts"))
if _rfonts is None:
    _rfonts = OxmlElement("w:rFonts")
    _rpr.append(_rfonts)
_rfonts.set(qn("w:eastAsia"), SONG)

add_page_number(sec)
sec.header.paragraphs[0].text = ""
hp = sec.header.paragraphs[0]
hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
hr = hp.add_run("网络爬虫技术课程大作业 · 城市天气与出行建议爬虫 Agent")
set_run(hr, size=9, color=RGBColor(0x66, 0x66, 0x66))

# ---------------- 封面 ----------------
for _ in range(4):
    doc.add_paragraph()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("网络爬虫技术 · 课程大作业")
set_run(r, cn=HEI, size=16, bold=True, color=ACCENT)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(30)
r = p.add_run("城市天气与出行建议爬虫 Agent")
set_run(r, cn=HEI, size=26, bold=True)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("——基于规则规划与工具调用的垂直领域智能体")
set_run(r, cn=KAI, size=14)

for _ in range(5):
    doc.add_paragraph()

info = [
    ("姓　　名", "刘志远"),
    ("学　　号", "2024612065"),
    ("班　　级", "________________"),
    ("指导教师", "________________"),
    ("完成日期", date.today().strftime("%Y 年 %m 月 %d 日")),
]
t = doc.add_table(rows=0, cols=2)
t.alignment = WD_TABLE_ALIGNMENT.CENTER
for k, v in info:
    cells = t.add_row().cells
    cells[0].width = Cm(3.5)
    cells[1].width = Cm(6.5)
    p0 = cells[0].paragraphs[0]
    p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r0 = p0.add_run(k + "：")
    set_run(r0, cn=HEI, size=13)
    p1 = cells[1].paragraphs[0]
    r1 = p1.add_run(v)
    set_run(r1, size=13)
    p1.paragraph_format.left_indent = Pt(6)

page_break(doc)

# ---------------- 摘要 ----------------
heading(doc, "摘　要", 1)
body(doc,
     "天气信息与出行决策之间存在一道“最后一公里”：预报数据散落在多个网站，用户需要自己翻页、"
     "比较城市、判断冷暖，才能得到一句“周末适不适合出门”。本项目设计并实现了一个面向该场景的"
     "垂直领域智能体（Agent）：以中国天气网城市 7 天预报和天气后报历史月度数据为数据源，"
     f"爬取 12 个城市、24 个月共 {rows} 条天气记录，构建可解释的 0–100 出行指数；"
     "在此之上实现了一个“规划—执行—反思—作答”的工具调用型 Agent，支持降水判断、穿衣建议、"
     "择日出行、城市对比、气候趋势与冷暖距平六类问题，并能一键生成带引用的出行简报。")

body(doc,
     "工程实现上，爬虫具备 robots.txt 校验、按域限速、指数退避重试、页面缓存、断点续爬与幂等入库能力；"
     f"在本次采集中共记录 {total_attempts} 次抓取，其中 {fail_tasks} 次因连接重置失败、重跑后全部补齐，"
     f"任务成功率 {success_rate:.1f}%。Agent 采用“确定性工具 + 规则规划”的架构，"
     "所有数字均由 SQL 与指标函数计算，模型只负责组织语言，从机制上避免了气温、日期等事实性幻觉；"
     "同时保留了大模型规划器的接入点，无 API Key 时也能完整运行。")

body(doc,
     f"在 20 条人工标注问题上的评测表明：意图识别准确率 {eval_sum.get('intent_accuracy', '-')}%，"
     f"工具调用召回率 {eval_sum.get('tool_recall', '-')}%，引用覆盖率 {eval_sum.get('citation_rate', '-')}%，"
     f"任务成功率 {eval_sum.get('success_rate', '-')}%，平均 {eval_sum.get('avg_steps', '-')} 步、"
     f"{eval_sum.get('avg_elapsed_s', '-')} 秒完成一次问答。项目还包含 35 个单元与集成测试，"
     "验证了解析、指标、规划与 Agent 主流程的正确性。")

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(10)
r = p.add_run("关键词：")
set_run(r, cn=HEI, size=BODY_PT, bold=True)
r = p.add_run("网络爬虫；天气数据；SQLite；出行指数；工具调用；智能体；可解释性")
set_run(r, size=BODY_PT)

page_break(doc)

# ---------------- 1 背景 ----------------
heading(doc, "1　选题背景与意义", 1)

heading(doc, "1.1　选题背景", 2)
body(doc,
     "天气是典型的“高频、低价值密度”信息：单次查询只需几秒钟，但要把“未来一周哪天适合出门”"
     "这个问题回答好，需要同时综合最高/最低气温、昼夜温差、降水、风力，还要知道当地这个季节"
     "“正常”是什么水平。普通用户通常要打开两三个页面、来回切换城市，仍然难以得出稳定结论。")
body(doc,
     "另一方面，天气站点普遍以“页面”而非“接口”的形式组织内容：中国天气网的 7 天预报把日期、"
     "天气现象、气温、风向分散在不同的 HTML 节点里，日期还只写成“21日（今天）”，必须结合页面"
     "隐藏域里的发布时间才能还原完整日期；历史数据站点则用表格承载，夹杂着广告行与空行。"
     "这些“不规整”恰好构成了爬虫课程最典型的训练场景：请求、解析、清洗、入库、分析，一个都不能少。")
body(doc,
     "大模型的出现让“采集之后”有了新的可能：与其把数据做成静态图表，不如让一个 Agent 自己决定"
     "该查哪张表、该调哪个指标、该怎样把结果讲清楚。本项目因此把“爬虫”与“Agent”结合起来，"
     "把一次性的数据采集升级为一个可以持续问答的出行助手。")

heading(doc, "1.2　项目目标", 2)
body(doc,
     "（1）完成一个结构完整、可复现、符合 robots 协议的天气数据采集系统；"
     "（2）在数据之上建立可解释的出行评价模型，而不是简单罗列气温；"
     "（3）实现一个真正调用数据工具的 Agent，回答结果可追溯、可验证；"
     "（4）交付代码、数据、图表与实验报告，形成可复现的工程闭环。")

heading(doc, "1.3　主要工作", 2)
body(doc,
     f"① 设计并实现双源爬虫，采集 12 个城市 24 个月历史天气与未来 7 天预报，共 {rows} 条结构化记录；"
     "② 设计 SQLite 数据库与断点续爬机制，支持增量更新与采集审计；"
     "③ 提出并实现五维度出行指数，输出可解释的扣分明细；"
     "④ 实现“规划—执行—反思—作答”的 Agent 运行时和 8 个确定性工具；"
     "⑤ 构建 20 题评测集与 35 个单元/集成测试，量化系统效果；"
     "⑥ 自动生成含 6 张图表、12 张表格的实验报告。")

# ---------------- 2 需求与合规 ----------------
heading(doc, "2　需求分析与合规设计", 1)

heading(doc, "2.1　功能需求", 2)
table(doc, ["编号", "需求", "验收标准"], [
    ["FR1", "多城市预报采集", "12 个城市各 7 天，字段完整率 100%"],
    ["FR2", "历史数据采集", "24 个月 × 12 城市，按日期幂等入库"],
    ["FR3", "增量与断点", "中断后重跑跳过已完成月份"],
    ["FR4", "统计与可视化", "输出气候画像表与 6 张图"],
    ["FR5", "出行指数", "0–100 分 + 等级 + 扣分理由"],
    ["FR6", "Agent 问答", "6 类意图，答案含数据来源"],
    ["FR7", "简报导出", "一键生成 Markdown 简报文件"],
    ["FR8", "离线可运行", "无网络、无 API Key 时可演示"],
], cap="表 2-1　功能需求", widths=[1.6, 5.2, 8.4])

heading(doc, "2.2　非功能需求", 2)
body(doc,
     "礼貌性：单域串行请求，默认间隔 1.2 秒，失败指数退避；可复现性：配置集中、缓存落盘、"
     "随机因素全部固定；可解释性：出行指数的每个扣分项、Agent 的每一步工具调用都写入日志与轨迹；"
     "容错性：单城市/单月份失败不影响整体任务，失败原因写入 crawl_log。")

heading(doc, "2.3　合规性设计", 2)
body(doc,
     "项目在采集前读取并解析 robots.txt。中国天气网明确 Allow: /；天气后报的 robots.txt 返回 403，"
     "按 RFC 9309 对 4xx 的语义视为“未设置限制”，但项目仍主动限速并只采集页面公开展示的数据。"
     "两个站点均只采集天气数值与文字描述，不下载图片、不抓取用户数据、不绕过任何登录或验证机制。")
table(doc, ["站点", "robots.txt", "采集策略"], [
    ["中国天气网", "Allow: /", "12 个城市预报页，间隔 1.2s"],
    ["天气后报", "403（无有效规则）", "24 个月历史表，间隔 1.2s，永久缓存"],
], cap="表 2-2　数据源与合规策略", widths=[3.4, 4.2, 7.6])

# ---------------- 3 系统设计 ----------------
heading(doc, "3　系统设计", 1)

heading(doc, "3.1　总体架构", 2)
body(doc,
     "系统分为六层：数据源、采集层、存储层、分析层、Agent 层与输出层。采集层对上层屏蔽了"
     "“网页”与“接口”的差异，统一输出结构化记录；分析层把记录变成指标；Agent 层只依赖工具接口，"
     "不直接接触 HTML。这样的分层使得“换数据源”或“换问答方式”都不会牵动其他模块。")
figure(doc, "fig6_architecture.png", "图 3-1　系统总体架构", width=15.5)

heading(doc, "3.2　模块划分", 2)
table(doc, ["模块", "文件", "职责"], [
    ["请求封装", "src/crawler/fetcher.py", "限速、重试、缓存、robots 校验"],
    ["页面解析", "src/crawler/parsers.py", "预报页与历史表解析、字段规范化"],
    ["存储", "src/crawler/store.py", "建表、幂等 upsert、断点状态、日志"],
    ["指标", "src/analysis/metrics.py", "气候画像、出行指数、冷暖距平"],
    ["图表", "src/analysis/charts.py", "6 张图的绘制与中文字体处理"],
    ["规划", "src/agent/planner.py", "意图识别、槽位抽取、工具计划"],
    ["工具", "src/agent/tools.py", "8 个只读数据工具"],
    ["运行时", "src/agent/loop.py", "执行、反思、组装答案、会话记忆"],
], cap="表 3-1　模块划分", widths=[2.6, 5.4, 7.2])

heading(doc, "3.3　数据库设计", 2)
body(doc,
     "采用 SQLite 单文件数据库，便于随作业一起打包。共 5 张表：cities 存城市元数据；forecasts 以"
     "“城市 + 发布日 + 预报日”为主键保存每次抓取的预报快照，为将来做预报准确率回测留出空间；"
     "history 以“城市 + 日期”为主键保存历史观测；crawl_log 记录每次请求的结果与耗时；"
     "crawl_state 记录“城市 + 月份”的完成状态，用于断点续爬。")
table(doc, ["表名", "主键", "关键字段", "用途"], [
    ["cities", "code", "name, province, region", "城市维度"],
    ["forecasts", "城市 + 发布日 + 预报日", "weather, temp_high/low, wind", "预报快照"],
    ["history", "城市 + 日期", "weather_day/night, temp, wind", "历史观测"],
    ["crawl_log", "id", "task, status, rows, elapsed_ms", "采集审计"],
    ["crawl_state", "key", "value, updated_at", "断点续爬"],
], cap="表 3-2　数据表设计", widths=[2.6, 5.4, 5.2, 2.6], font_size=8.5)

heading(doc, "3.4　数据流", 2)
body(doc,
     "URL → Fetcher（缓存/限速/重试）→ HTML 文本 → Parser（字段抽取与规范化）→ records → "
     "Store.upsert（幂等写入）→ DataFrame → metrics（特征与指标）→ Toolbox（工具封装）→ "
     "Agent（规划与作答）→ 图表/简报/报告。整条链路上没有任何一步依赖人工干预，"
     "run_all.ps1 可一键复现。")

# ---------------- 4 爬虫实现 ----------------
heading(doc, "4　爬虫实现", 1)

heading(doc, "4.1　请求封装：礼貌、稳健、可复现", 2)
body(doc,
     "Fetcher 统一封装了请求过程。限速不是简单的 sleep，而是为每个 host 维护“下一次允许请求的时间”，"
     "请求返回后立即预约下一次，因而不会因为解析耗时导致实际间隔被拉长；重试采用指数退避并加入"
     "随机抖动，避免多任务同时重试形成尖峰；页面按 URL 的 SHA-1 落盘缓存，历史页永久有效、"
     "预报页 2 小时过期，既减少对目标站的压力，也让断网时仍可复现实验。")
code_block(doc, snippet("src/crawler/fetcher.py", "def _wait_turn", "def get"))
code_block(doc, snippet("src/crawler/fetcher.py", "for attempt in range(self.retries + 1):",
                        "self.stats[\"failed\"] += 1"), max_lines=26)
body(doc,
     "robots 处理严格遵循 RFC 9309：2xx 解析规则并取 Crawl-delay；4xx 视为无限制；5xx 视为不可用，"
     "保守地禁止抓取；网络异常则记录警告后放行。规则本身也会缓存 24 小时，避免每个请求都去读 robots.txt。")

heading(doc, "4.2　页面解析：两个站点的三种“坑”", 2)
body(doc,
     "预报页的日期只写成“21日（今天）”，没有年份和月份。项目从页面隐藏域 fc_3h_internal_update_time "
     "读取精确到分钟的发布时间，再以发布日为起点、在 0–7 天窗口内寻找日号相同的日期，从而正确"
     "处理跨月（如 11 月 28 日发布、列表中出现“1日”）的情况。")
body(doc,
     "风力字段是复合值，例如“3-4级转<3级”，需要按“转”拆成白天与夜间两段；风向则藏在 span 的 "
     "title 属性里，文本节点是空的，直接取 text 会得到空字符串。历史页的表格有 34 行，其中 3 行是"
     "广告或空行，必须用日期正则过滤；气温单元格还可能写成“22℃/8℃”或“22℃ / 8℃”两种形式。")
code_block(doc, snippet("src/crawler/parsers.py", "def parse_forecast", "def _split_pair"), max_lines=30)
body(doc,
     "解析器在找不到关键节点或解析结果为空时抛出带城市名的 ValueError，而不是返回空列表，"
     "这样采集层能准确地把失败写入日志，避免“静默写入脏数据”。")

heading(doc, "4.3　增量采集与幂等入库", 2)
body(doc,
     "crawl_state 表以 history:<城市代码>:<年月> 为键记录完成状态。重跑时先查状态，已完成的月份"
     "直接跳过；即使状态丢失，INSERT ... ON CONFLICT DO UPDATE 也保证重复抓取不会产生重复行。"
     "这一设计让“采集—中断—续采”成为常规操作，而不是需要人工清理数据库的异常流程。")
code_block(doc, snippet("src/crawler/store.py", "def upsert_forecasts", "def upsert_history"), max_lines=18)

heading(doc, "4.4　采集结果", 2)
table(doc, ["指标", "数值"], [
    ["目标城市", f"{len(profile) or 12} 个"],
    ["历史时间范围", f"{hist.get('start', '-')} 至 {hist.get('end', '-')}"],
    ["历史记录数", f"{counts.get('history', 0)} 条"],
    ["预报记录数", f"{counts.get('forecasts', 0)} 条（{fc.get('days', '-')} 天 × 城市数）"],
    ["请求次数", f"{total_attempts} 次"],
    ["成功 / 失败", f"{ok_tasks} / {fail_tasks} 次"],
    ["写入记录数", f"{counts.get('history', 0)} 条历史 + {counts.get('forecasts', 0)} 条预报"],
    ["平均响应时间", f"{avg_ms} ms"],
    ["任务成功率", f"{success_rate:.1f}%"],
    ["采集总耗时", f"{crawl_seconds} 秒"],
], cap="表 4-1　采集结果统计", widths=[5.6, 9.4])
body(doc,
     "采集过程中，天气后报在部分时段出现 5–9 秒的慢响应甚至读超时，Fetcher 的重试机制吸收了大部分抖动；"
     "三亚首轮的 6 个月份因连接重置最终失败，重跑一次后全部补齐，没有产生数据缺口。"
     "这也从侧面验证了退避重试与断点续爬的必要性。")

# ---------------- 5 数据分析 ----------------
heading(doc, "5　数据清洗与统计分析", 1)

heading(doc, "5.1　数据质量检查", 2)
body(doc,
     "入库前对每条记录做三项校验：日期可解析、最高气温不低于最低气温、字段非空。分析阶段再次检查"
     "重复主键与缺失值，结果如下表。")
table(doc, ["检查项", "结果"], [
    ["主键重复", "0 条"],
    ["气温缺失", "0 条"],
    ["最高温 < 最低温", "0 条"],
    ["单城市天数", f"{hist.get('days_per_city', '-')} 天（24 个月）"],
    ["字段完整率", "100%"],
], cap="表 5-1　数据质量检查", widths=[6.4, 8.6])

heading(doc, "5.2　城市气候画像", 2)
body(doc,
     "对 24 个月的历史数据按城市聚合，得到均温、极端温度、降水日占比与平均昼夜温差。"
     "受纬度与海洋性影响，城市之间差异显著：三亚全年均温最高、昼夜温差最小；"
     "哈尔滨冬季极端低温最低；广州、深圳的降水频率最高，北京、西安最低。")
rows_profile = []
for p in profile:
    rows_profile.append([p["city"], fmt(p["mean_temp"]), f"{p['max_high']}/{p['min_low']}",
                         f"{p['rain_ratio']}%", fmt(p["avg_range"]), p["rain_days"]])
table(doc, ["城市", "均温(℃)", "最高/最低(℃)", "降水日占比", "平均温差(℃)", "降水日数"],
      rows_profile, cap="表 5-2　12 城市气候画像（2024-11 至 2026-10）",
      widths=[2.4, 2.6, 3.6, 3.4, 3.2, 2.6], font_size=8.5)

figure(doc, "fig2_monthly_trend.png", "图 5-1　24 个月月平均气温变化", width=15.5)
body(doc,
     "图 5-1 显示，12 城平均气温呈标准的单峰年周期：每年 7—8 月为高点、1 月为低点，"
     "2025 年与 2026 年的夏季高点几乎重合。不同城市的振幅差异很大：哈尔滨冬季月均温可低至 -18℃，"
     "而广州、深圳、三亚全年温暖，这解释了为什么同一句“周末出去玩”在不同城市需要完全不同的建议。")

_by_rain = sorted(profile, key=lambda p: -p["rain_ratio"])
_rain_top = "、".join(f"{p['city']}（{p['rain_ratio']}%）" for p in _by_rain[:3])
_rain_low = "、".join(f"{p['city']}（{p['rain_ratio']}%）" for p in _by_rain[-2:])
_by_range = sorted(profile, key=lambda p: -p["avg_range"])
_range_top = "、".join(f"{p['city']}（{p['avg_range']}℃）" for p in _by_range[:3])

heading(doc, "5.3　降水与温差", 2)
figure(doc, "fig3_rain_profile.png", "图 5-2　各城市降水频率与平均昼夜温差", width=15.5)
body(doc,
     f"降水日占比最高的是 {_rain_top}，与华南前汛期、江南梅雨的气候背景一致；"
     f"最低的是 {_rain_low}。昼夜温差最大的是 {_range_top}，普遍在 9℃ 以上，"
     "这正是出行建议里“早晚加件外套”的数据依据。")

heading(doc, "5.4　出行指数模型", 2)
body(doc,
     "出行指数从五个维度对一天打分，满分 100，逐项扣分并保留扣分理由。与“拍脑袋”的加权平均相比，"
     "规则式扣分的好处是每一项都能向用户解释：为什么今天只有 61 分？因为均温 2.5℃ 偏低扣了 35 分，"
     "昼夜温差 11℃ 又扣了 4 分。")
table(doc, ["维度", "规则", "扣分"], [
    ["气温舒适度", "均温 16–26℃ 不扣；偏离 6℃ 内 −12；11℃ 内 −25；更多 −35", "0 ~ −35"],
    ["降水", "雨/雪 −18；暴雨/大雨 −25；阴 −6；多云 −2", "0 ~ −25"],
    ["风力", "≥6 级 −12；5 级 −6；4 级 −2", "0 ~ −12"],
    ["昼夜温差", ">15℃ −12；>12℃ −8；>10℃ −4", "0 ~ −12"],
    ["极端温度", "最高 ≥35℃ 或最低 ≤−10℃ 各 −8", "0 ~ −16"],
], cap="表 5-3　出行指数扣分规则", widths=[3.2, 9.4, 2.4])
body(doc,
     "等级划分为 A（≥80）、B（≥65）、C（≥50）、D（<50）。在当前 11 月下旬的预报中，"
     "南方城市普遍为 A（如三亚、广州），北方城市多在 B/C 区间，与直觉一致，说明模型具备基本的区分度。")
figure(doc, "fig4_travel_index.png", "图 5-3　未来 7 天出行指数矩阵", width=15.5)
figure(doc, "fig1_forecast_heatmap.png", "图 5-4　未来 7 天日平均气温热力图", width=15.5)

# ---------------- 6 Agent ----------------
heading(doc, "6　Agent 设计", 1)

heading(doc, "6.1　设计原则：不做“套壳 ChatGPT”", 2)
body(doc,
     "很多“爬虫 + Agent”的实现，是把爬到的文本丢给大模型总结。这种做法有两个问题：一是模型可能"
     "编造数字，二是无法复核。本项目采用相反的思路：把“能算的”全部交给确定性代码，把“要说的”交给"
     "模板与（可选的）大模型。Agent 的职责是决定“查什么、按什么顺序查、查不到怎么办”，而不是"
     "凭记忆回答天气。")
body(doc,
     "具体而言，Agent 由四部分组成：规则规划器（意图 + 槽位 + 工具计划）、工具执行器（8 个只读工具）、"
     "反思器（覆盖性、引用、新鲜度检查）、答案组装器（把工具返回值填进模板）。四者串成一个有界的"
     "ReAct 循环，最多 8 步、最多 2 轮反思。")

heading(doc, "6.2　工具集", 2)
table(doc, ["工具", "输入", "输出", "用途"], [
    ["get_forecast", "城市, 天数, 起始日", "逐日预报", "所有建议的数据底座"],
    ["get_history", "城市, 起止", "气候画像+季节序列", "趋势与背景"],
    ["compare_cities", "城市列表, 日期", "按指数排序的对比表", "城市选择"],
    ["travel_score", "城市, 日期", "分数+等级+理由", "单日评价"],
    ["best_day", "城市, 窗口", "按分数排序的日期", "择日出行"],
    ["climate_anomaly", "城市", "逐日距平与均值", "冷暖异常"],
    ["packing_advice", "城市, 日期", "穿衣+携带清单", "行李建议"],
    ["save_brief", "Markdown 内容", "文件路径", "简报落盘"],
], cap="表 6-1　Agent 工具集", widths=[3.4, 4.6, 4.2, 4.0])

heading(doc, "6.3　规划器：意图与槽位", 2)
body(doc,
     "规划器用关键词规则识别 7 类意图，并允许一个问句命中多个意图（如“周末适合出去玩吗，要带伞吗”"
     "同时命中 best_day 与 rain）。槽位抽取负责城市、日期与时长：城市名直接匹配配置表；日期支持"
     "“今天/明天/后天”“下周三”“这周末”“未来三天”“11月24日”等表达；若问句没有城市，则沿用上一轮"
     "的城市（对话记忆），没有历史则回落到默认城市并在答案开头说明。")
table(doc, ["意图", "触发示例", "主要工具"], [
    ["rain", "要带伞吗 / 会下雨吗", "get_forecast"],
    ["packing", "穿什么 / 冷不冷", "packing_advice"],
    ["best_day", "哪天 / 周末 / 最适合", "best_day"],
    ["compare", "哪个 / 和…比 / 更适合", "compare_cities"],
    ["anomaly", "反常 / 比往年 / 同期", "climate_anomaly"],
    ["trend", "今年 / 去年 / 趋势", "get_history"],
    ["brief", "简报 / 汇总 / 报告", "多个工具 + save_brief"],
], cap="表 6-2　意图与工具映射", widths=[2.8, 6.6, 5.6])

heading(doc, "6.4　反思：让 Agent 自己发现“查漏了”", 2)
body(doc,
     "执行完计划后，反思器做四项检查：目标城市是否都有预报、目标日期是否落在预报窗口内、结论是否"
     "有可溯源引用、预报批次是否足够新。任何一项不通过，就把缺失的工具调用追加到计划末尾并重新执行，"
     "最多两轮。这样即使是“下周三去成都”这种超出 7 天窗口的问题，Agent 也能给出降级说明而不是答非所问。")
code_block(doc, snippet("src/agent/loop.py", "def _reflect", "def ask"), max_lines=26)

heading(doc, "6.5　防幻觉与可解释", 2)
body(doc,
     "答案中的每一个数字都来自 ToolResult，组装器只做字符串拼接；引用统一附在答案末尾，包含来源名称、"
     "URL 与采集时间；如果工具返回空，答案会明确写“没有查询到可用数据”，而不是编造。此外，每轮对话"
     "的轨迹（思考、动作、参数、观察、耗时）都可以用 --trace 打印，便于复盘。")

heading(doc, "6.6　对话记忆", 2)
body(doc,
     "Session 对象保存上一轮的城市。用户问“上海明天天气怎么样”，再问“那后天呢”，第二轮没有城市名，"
     "规划器会用记忆补全，并在答案开头注明“沿用上一轮城市：上海”，既方便又不会让用户困惑。")

# ---------------- 7 实验 ----------------
heading(doc, "7　实验与评测", 1)

heading(doc, "7.1　实验环境", 2)
table(doc, ["项目", "配置"], [
    ["操作系统", "Windows 11"],
    ["Python", "3.9.13"],
    ["主要依赖", "requests 2.32.3 / BeautifulSoup4 / pandas / matplotlib / python-docx"],
    ["数据库", "SQLite 3（单文件）"],
    ["硬件", "普通笔记本，无 GPU"],
    ["网络", "家庭宽带，单线程采集"],
], cap="表 7-1　实验环境", widths=[4.2, 10.8])

heading(doc, "7.2　爬虫性能", 2)
body(doc,
     f"本次采集共记录 {total_attempts} 次抓取，其中 {ok_tasks} 次成功、{fail_tasks} 次失败，"
     f"平均响应 {avg_ms} ms，整体耗时 {crawl_seconds} 秒（约 {crawl_seconds / 60:.0f} 分钟），"
     f"任务成功率 {success_rate:.1f}%。失败集中在三亚的 6 个月份，均为连接重置或读超时，重跑一次后全部补齐。"
     "限速策略下请求间隔不小于 1.2 秒，多数请求的响应时间在 1 秒以内；"
     "缓存机制在调试阶段作用明显：重复运行分析、Agent 评测时不再产生任何网络请求。")
table(doc, ["指标", "数值", "说明"], [
    ["抓取次数", f"{total_attempts}", "含失败"],
    ["成功 / 失败", f"{ok_tasks} / {fail_tasks}", "失败后重跑补齐"],
    ["平均响应", f"{avg_ms} ms", "不含限速等待"],
    ["总耗时", f"{crawl_seconds} s", "串行 + 限速"],
    ["任务成功率", f"{success_rate:.1f}%", "最终无数据缺口"],
], cap="表 7-2　爬虫性能指标", widths=[4.2, 4.0, 6.8])

heading(doc, "7.3　Agent 评测", 2)
body(doc,
     f"评测集包含 20 条人工标注问题，覆盖 7 类意图与默认城市回落等边界情况。"
     f"总体任务成功率 {eval_sum.get('success_rate', '-')}%，意图准确率 {eval_sum.get('intent_accuracy', '-')}%，"
     f"工具召回率 {eval_sum.get('tool_recall', '-')}%，引用覆盖率 {eval_sum.get('citation_rate', '-')}%。"
     f"平均每次问答 {eval_sum.get('avg_steps', '-')} 步、耗时 {eval_sum.get('avg_elapsed_s', '-')} 秒。")
rows_eval = []
for r in eval_rows:
    rows_eval.append([r["id"], r["question"][:18], "✓" if r["intent_ok"] else "✗",
                      f"{r['tool_recall']:.0%}", r["steps"], r["elapsed_s"],
                      "✓" if r["success"] else "✗"])
table(doc, ["#", "问题", "意图", "工具召回", "步数", "耗时(s)", "成功"],
      rows_eval, cap="表 7-3　Agent 20 题评测结果",
      widths=[0.9, 5.8, 1.3, 1.9, 1.2, 1.8, 1.2], font_size=7.5)

heading(doc, "7.4　典型案例", 2)
body(doc,
     "以“北京这周末适合出去玩吗？需要带伞吗？”为例，Agent 的执行轨迹如下（节选）：")
code_block(doc, """[1] ✓ get_forecast(city=北京, days=2)  14ms
    思考：所有出行建议都需要预报数据
    观察：北京未来 2 天：2026-11-21 至 2026-11-22，降水 0 天，气温 -3~8℃。
[2] ✓ best_day(city=北京, within=2)  0ms
    思考：需要在未来几天中排序
    观察：北京未来 2 天最佳出行日：2026-11-22（63 分）。
── 自检项 ──────────────────────────────
  ✓ 预报数据覆盖目标城市
  ✓ 目标日期在预报覆盖范围内 2026-11-21
  ✓ 结论包含可溯源引用
  ✓ 预报数据足够新""", max_lines=16)
body(doc,
     "最终答案是“北京在本周末内没有降水天气，不需要带伞；最佳出行日 11-22（周日，多云，-1~6℃，"
     "出行指数 63）”，并附上逐日表格与数据来源链接。整条链路中，Agent 只做了两次工具调用，"
     "没有一次自由生成的气温数字。")

heading(doc, "7.5　失败与边界分析", 2)
body(doc,
     "（1）城市未收录：如“天津天气怎么样”，系统会回落到默认城市并在开头说明，属于有意的降级而非错误；"
     "（2）超出预报窗口：“下个月去哈尔滨”这类问题只能给出未来 7 天概况，答案中会明确提示；"
     "（3）复杂多跳问题：如“比较北京和上海未来一周最适合出行的一天并说明理由”，当前规划器会拆成"
     "两组工具调用，但组织语言的丰富度仍不及大模型；（4）口语化时间表达（“过两天”“月底”）尚未覆盖。")

# ---------------- 8 问题与改进 ----------------
heading(doc, "8　遇到的问题与改进方向", 1)

heading(doc, "8.1　遇到的问题", 2)
body(doc,
     "① 反爬与限速：天气后报在连续请求后出现 5–9 秒慢响应，最初的 15 秒超时会被触发；通过指数退避"
     "与单线程串行解决，代价是采集时间变长。"
     "② 日期歧义：预报页只有“21日”没有年月，最初直接取系统日期导致跨月错位；改为读取隐藏域发布时间后解决。"
     "③ 编码问题：Windows 控制台默认 GBK，输出勾选符号与中文时乱码；统一在 CLI 入口把 stdout 改为 UTF-8。"
     "④ 规则天花板：关键词规则对同义表达覆盖有限，评测中个别问题需要补充同义词才能命中意图。")

heading(doc, "8.2　改进方向", 2)
body(doc,
     "① 接入大模型作为规划器：保留现有工具与校验层，只把“意图 + 计划”交给模型生成，用结构化输出约束，"
     "可在不牺牲可靠性的前提下显著提升语言理解覆盖面；"
     "② 预报准确率回测：forecasts 表已按发布日保存快照，持续采集一段时间后可与 history 对齐，"
     "计算不同预报时效的误差；"
     "③ 扩展到更多城市与要素（空气质量、紫外线、日出日落），并引入异步采集提升吞吐；"
     "④ 增加 Web 前端与定时任务，把“周末提醒”做成真正的日常工具；"
     "⑤ 引入向量检索，对历史天气事件做相似日检索，为“今年是否反常”提供更充分的证据。")

# ---------------- 9 总结 ----------------
heading(doc, "9　总结", 1)
body(doc,
     f"本项目完成了一个从数据采集到智能问答的完整闭环：爬取 12 个城市 24 个月共 {rows} 条天气记录，"
     "建立了可解释的出行指数模型，实现了具备规划、工具调用与反思能力的 Agent，并通过 20 题评测与"
     "35 个测试验证了系统的正确性与稳定性。")
body(doc,
     "相比“把网页内容丢给大模型”的做法，本项目更强调确定性与可追溯：数字由代码计算，结论有引用，"
     "过程有轨迹。这一思路也可以迁移到其他垂直领域，例如校园通知聚合、招聘信息分析、电商比价等，"
     "只需替换采集器与工具集，Agent 的规划与反思框架可以复用。")

# ---------------- 参考文献 ----------------
heading(doc, "参考文献", 1)
refs = [
    "Requests. Requests: HTTP for Humans[EB/OL]. https://requests.readthedocs.io/, 2024.",
    "Richardson L. Beautiful Soup Documentation[EB/OL]. https://www.crummy.com/software/BeautifulSoup/bs4/doc/, 2024.",
    "Koster M, Illyes G, Zeller H, et al. Robots Exclusion Protocol: RFC 9309[S]. IETF, 2022.",
    "Yao S, Zhao J, Yu D, et al. ReAct: Synergizing Reasoning and Acting in Language Models[C]//ICLR. 2023.",
    "Schick T, Dwivedi-Yu J, Dessì R, et al. Toolformer: Language Models Can Teach Themselves to Use Tools[C]//NeurIPS. 2023.",
    "Wei J, Wang X, Schuurmans D, et al. Chain-of-Thought Prompting Elicits Reasoning in Large Language Models[C]//NeurIPS. 2022.",
    "中国天气网. 城市 7 天天气预报[EB/OL]. http://www.weather.com.cn/weather/101010100.shtml.",
    "天气后报. 历史天气预报查询[EB/OL]. http://www.tianqihoubao.com/lishi/.",
    "SQLite. SQLite Documentation[EB/OL]. https://www.sqlite.org/docs.html, 2024.",
    "pandas. pandas Documentation[EB/OL]. https://pandas.pydata.org/docs/, 2024.",
]
for i, ref in enumerate(refs, 1):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Pt(24)
    p.paragraph_format.first_line_indent = Pt(-24)
    p.paragraph_format.line_spacing = 1.25
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(f"[{i}] {ref}")
    set_run(r, size=10.5)

# ---------------- 附录 ----------------
heading(doc, "附录 A　运行说明", 1)
body(doc, "环境要求：Python 3.9+，依赖见 requirements.txt。按以下顺序执行即可复现全部结果：")
code_block(doc, """pip install -r requirements.txt
python -m src.crawler.cli init-db
python -m src.crawler.cli crawl-all
python -m src.analysis.cli
python -m src.agent.cli "北京这周末适合出去玩吗？需要带伞吗？" --trace
python -m eval.run_eval
python build_report.py""", max_lines=10)
body(doc,
     "若只需演示，仓库内已附带 data/weather.db 与解析测试快照，可跳过采集直接运行分析与 Agent；"
     "run_all.ps1 提供了一键执行脚本，并支持 -SkipCrawl / -SkipReport 参数。")

heading(doc, "附录 B　交付清单", 1)
table(doc, ["类别", "内容"], [
    ["代码", "src/（采集、分析、Agent）、eval/、tests/"],
    ["数据", "data/weather.db、data/crawl_stats.json、data/cache/（页面快照）"],
    ["结果", "output/figures/ 6 张图、CSV、summary.json、eval_report.md、briefs/"],
    ["报告", "report/实验报告_*.docx 与本 PDF"],
    ["说明", "README.md、requirements.txt、config.yaml、run_all.ps1"],
], cap="表 B-1　交付清单", widths=[2.4, 12.6])

out = REPORT_DIR / "实验报告_城市天气与出行建议爬虫Agent.docx"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
doc.save(out)
print(f"报告已生成：{out}")
