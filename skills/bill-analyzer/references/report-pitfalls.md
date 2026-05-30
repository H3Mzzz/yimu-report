# 报告生成 Pitfalls

## 饼图注入机制

`html_renderer.py` 的 `build_html_email()` 接收 `metrics` 参数后生成 base64 饼图 PNG，通过 `_inject_chart_after_section()` 按关键词注入到报告 HTML 的对应章节末尾。

**关键词必须与 AI 生成的报告标题匹配**：

| 渲染器关键词 | 匹配目标 |
|------|------|
| `支出结构` | `## 支出结构` 或 `## 📈 支出结构` |
| `收入结构` | `## 收入结构` |

⚠️ `summarize()` 输出用 `## 支出分类全景`，但 cron AI 重写时改成 `## 支出结构`。renderer 关键词必须跟 AI 输出走，否则饼图静默跳过。

**排查**：邮件无饼图时：
1. `cat /tmp/daily_report.md | grep "## 支出"` 看实际标题
2. 对比 `html_renderer.py` 中 `charts["..."]` 的 key

## Cron AI 用错发送脚本（无 HTML / 无饼图）

**症状**：邮件日报是纯文本 Markdown，没有 HTML 格式、没有饼图。

**根因**：cron prompt 要求用 `send_report.py`，但 AI 改用 `send_mail.py`。

| 脚本 | 作用 |
|------|------|
| `send_mail.py` | 直接发文件内容，纯文本或原始 HTML |
| `send_report.py` | Markdown → HTML 渲染 + 饼图（`html_renderer.py`）+ 发送 |

**排查**：
```bash
grep "send_mail\|send_report" ~/.hermes/cron/output/27325cc5b40d/$(ls -t ~/.hermes/cron/output/27325cc5b40d/ | head -1)
```

## 地点聚类在报告中丢失

`main.py --data-only` 的 JSON 输出包含 `## 🗺️ 高频活动区域` 表格，但 cron AI 可能丢弃。

**根因**：cron prompt 未明确要求保留。已修复——prompt 加入了保留指令。

**排查**：
```bash
/usr/bin/python3 ~/yimu-report/main.py --data-only --mode weekly > /tmp/data.json
grep "高频活动区域" /tmp/data.json
```

## 知识库"幽灵监控"

cron AI 会持续跟踪知识库中的未解决标记（`⚠️`/`🔴`/`待确认`），即使事项已解决。

**修复模式**：
1. `consumption-profile.md`：`⚠️` → `✅` 已核实
2. `daily-insights.md`：加删除线 + 结案标记
3. `weekly-insights.md` / `agent-evolution.md`：更新跟踪状态

**预防**：用户确认异常已解决时，立即批量更新 4 个文件。

## 晚补数据后重跑日报

1. `cd ~/yimu-report && /usr/bin/python3 sync_db.py`
2. 验证：`analyze_bills.py --from YYYY-MM-DD --to YYYY-MM-DD --json`
3. 删除旧日报段落：`grep -n "^### " <knowledge-file>` 找行号，`patch` 删除
4. `cronjob run` 指定 job_id（日报 `27325cc5b40d`）
5. 验证：`~/.hermes/cron/output/27325cc5b40d/` 有新文件

⚠️ `cronjob run` 异步执行，等 2-4 分钟。
