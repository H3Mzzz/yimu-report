#!/usr/bin/env python3
"""
知识库文件滚动裁剪脚本。

按 `---` 分隔符将文件拆为 header + N 个内容块，
保留 header + 最后 max_blocks 个块，超出的旧块追加到归档文件。

用法：
  python3 trim_knowledge.py daily-insights.md --max 30
  python3 trim_knowledge.py weekly-insights.md --max 12
  python3 trim_knowledge.py some-file.md --max 5 --dry-run
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="滚动裁剪知识库 .md 文件")
    parser.add_argument("file", help="要裁剪的 .md 文件路径")
    parser.add_argument("--max", type=int, required=True, help="最多保留的内容块数")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不实际修改")
    args = parser.parse_args()

    filepath = Path(args.file).resolve()
    if not filepath.exists():
        print(f"❌ 文件不存在: {filepath}", file=sys.stderr)
        sys.exit(1)

    text = filepath.read_text(encoding="utf-8")
    parts = text.split("\n---\n")

    # parts[0] = header + 可能的第一个块（如果 header 行以 --- 结尾）
    # 但我们的格式是: header\n\n---\n\nblock1\n\n---\n\nblock2...
    # split("\n---\n") 得到: [header, block1, block2, ...]
    # 验证：第一个 part 不应包含 ---（header 的 --- 已被 split 吃掉）

    header = parts[0]
    blocks = parts[1:]  # 内容块

    total = len(blocks)
    keep = args.max
    excess = total - keep

    print(f"📄 {filepath.name}")
    print(f"   总块数: {total}, 保留: {min(total, keep)}, 裁剪: {max(0, excess)}")

    if excess <= 0:
        print("   ✅ 未超限，无需裁剪")
        return

    # 要归档的旧块（前面的）
    archive_blocks = blocks[:excess]
    # 要保留的块（最后 N 个）
    keep_blocks = blocks[excess:]

    # 归档文件路径：同目录下 xxx-archive.md
    archive_path = filepath.parent / f"{filepath.stem}-archive.md"

    if args.dry_run:
        print(f"   [dry-run] 将裁剪 {excess} 块 → {archive_path.name}")
        print(f"   [dry-run] 保留最后 {keep} 块在 {filepath.name}")
        return

    # 写归档：追加
    archive_content = "\n---\n".join(archive_blocks) + "\n---\n"
    if archive_path.exists():
        # 已有归档，追加
        with open(archive_path, "a", encoding="utf-8") as f:
            f.write(archive_content)
        print(f"   📦 追加 {excess} 块到 {archive_path.name}")
    else:
        archive_path.write_text(archive_content, encoding="utf-8")
        print(f"   📦 创建 {archive_path.name}，写入 {excess} 块")

    # 写回原文件：header + 保留的块
    new_text = header + "\n---\n" + "\n---\n".join(keep_blocks)
    # 确保文件末尾有换行
    if not new_text.endswith("\n"):
        new_text += "\n"
    filepath.write_text(new_text, encoding="utf-8")
    print(f"   ✂️  已裁剪，保留 {len(keep_blocks)} 块")


if __name__ == "__main__":
    main()
