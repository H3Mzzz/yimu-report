# 隐私陷阱

## templates/ 包含真实消费数据

`templates/knowledge/finance/` 下的模板文件包含真实餐厅名、消费金额、出行轨迹、运营商信息。

**已随 yimu-report.git 推送到 GitHub**（commit `a484ea2`）。

**预防**：
1. 新建模板时用模拟数据替换
2. 或在 README 标注仓库为 private
3. 已推送真实数据：`git filter-branch` 或 BFG 清理

**检查**：
```bash
grep -r "¥[0-9]" templates/knowledge/ --include="*.md" | head -20
```
