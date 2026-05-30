# 数据修正后完整工作流

> 当用户说"账单数据有误，已修正"时的操作清单。

## 标准流程（SQLite 数据源）

1. **用户在 App 中修正数据**：用户在一木记账 App 中修改/删除/新增账单

2. **等待 App 自动同步**：一木记账会自动将加密 zip 同步到坚果云 `一木记账/` 文件夹

3. **拉取修正后数据**：运行 DB 同步脚本刷新本地数据库
   ```bash
   bash ~/.hermes/scripts/sync_bill_db.sh
   # 或手动：cd ~/yimu-report && /usr/bin/python3 sync_db.py
   ```

4. **验证修正结果**：用 `analyze_bills.py` 获取修正后的摘要
   ```bash
   python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --from YYYY-MM-DD --to YYYY-MM-DD --json
   python3 ~/.hermes/skills/bill-analyzer/scripts/analyze_bills.py --month current --json
   ```

5. **修正知识库文件**：不是重跑就够了——必须 `patch` 以下文件中的错误条目：
   - `/root/cow/knowledge/finance/daily-insights.md` — 修正对应日期的日报条目 + 月度预算全景表
   - `/root/cow/knowledge/finance/consumption-profile.md` — 更新日志，标注修正内容

6. **生成修正版报告**：Markdown 报告开头写 `⚠️ 数据修正公告`，明确标注改动内容

7. **重新发送邮件**：`send_report.py --mode daily --body-file /tmp/report.md`

## 常见错误类型

| 类型 | 示例 | 修正方式 |
|------|------|---------|
| 误记账（错误支出条目） | 演唱会 ¥1,434 不应存在 | 用户在一木记账删除后重新备份 |
| 分类错误 | 餐饮归入娱乐 | 用户修正后重新备份 |
| 金额错误 | 餐费 ¥39.40 误记为 ¥394.00 | 同上 |

## 易错点

- ❌ 只重跑备份和分析，忘记 patch `daily-insights.md` — 导致知识库仍含错误记录，下次日报引用错误历史
- ❌ 只修正日报条目，忘记修正下方的预算全景表 — 数字对不上
- ✅ 每次修正后应在修正条目中列出修正前后的关键数字对比（如 ¥1,487 → ¥53）
