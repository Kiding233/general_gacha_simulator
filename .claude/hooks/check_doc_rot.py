#!/usr/bin/env python3
"""
H6 Stop Hook —— 文档腐烂检测。

触发：Stop（会话结束时）
动作：扫描所有模块 05-笔记.md 最后更新日期 → 超过 7 天标记。

exit: 0（永不阻止会话结束——只输出提醒到 stderr）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_hook_input, get_main_repo_root, scan_module_notes


def main():
    hook_input = read_hook_input()
    cwd = hook_input.get("cwd", None)
    project_root = get_main_repo_root(cwd=cwd)

    if project_root is None:
        return 0

    docs_dir = project_root / "docs" / "01-活跃"
    if not docs_dir.is_dir():
        return 0

    stale_modules = scan_module_notes(docs_dir, max_stale_days=7)

    if stale_modules:
        print("📋 H6 文档腐烂检测 — 以下模块 05-笔记 >7 天未更新:", file=sys.stderr)
        for item in stale_modules[:10]:  # 最多 10 条
            print(f"   • {item['module']} — {item['days_ago']} 天前", file=sys.stderr)
        if len(stale_modules) > 10:
            print(f"   ... 及其他 {len(stale_modules) - 10} 个模块", file=sys.stderr)
        print("   C3 周报生成器将在周一自动汇总并写入本周聚焦。", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
