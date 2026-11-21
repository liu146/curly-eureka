# 一键运行：采集 -> 分析 -> 评测 -> 测试 -> 报告
param(
    [switch]$SkipCrawl,
    [switch]$SkipReport
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==> 1/6 初始化数据库" -ForegroundColor Cyan
python -m src.crawler.cli init-db

if (-not $SkipCrawl) {
    Write-Host "==> 2/6 采集数据（约 5-10 分钟）" -ForegroundColor Cyan
    python -m src.crawler.cli crawl-all
} else {
    Write-Host "==> 2/6 跳过采集" -ForegroundColor Yellow
}

Write-Host "==> 3/6 统计分析与图表" -ForegroundColor Cyan
python -m src.analysis.cli

Write-Host "==> 4/6 Agent 评测" -ForegroundColor Cyan
python -m eval.run_eval

Write-Host "==> 5/6 单元测试" -ForegroundColor Cyan
python -m unittest discover -s tests -t .

if (-not $SkipReport) {
    Write-Host "==> 6/6 生成 Word 报告（需要 python-docx）" -ForegroundColor Cyan
    python build_report.py
} else {
    Write-Host "==> 6/6 跳过报告" -ForegroundColor Yellow
}

Write-Host "全部完成。" -ForegroundColor Green
