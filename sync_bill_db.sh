#!/bin/bash
set -a
source ~/.hermes/.env
set +a
/usr/bin/python3 ~/yimu-report/sync_db.py

# 知识库滚动裁剪（在 AI 读取前执行）
TRIM=~/yimu-report/trim_knowledge.py
/usr/bin/python3 "$TRIM" ~/cow/knowledge/finance/daily-insights.md --max 30
/usr/bin/python3 "$TRIM" ~/cow/knowledge/finance/weekly-insights.md --max 12
