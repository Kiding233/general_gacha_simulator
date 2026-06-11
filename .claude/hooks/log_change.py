#!/usr/bin/env python3
"""
H4 PostToolUse Hook —— 变更日志。

触发：PostToolUse(Write | Edit)
动作：修改 gacha_simulator/ 或 docs/ 下文件后，追加
      `{时间} | {操作} | {文件路径}` 到对应模块的 05-笔记.md。

映射规则：
  1. 读取 .claude/file_map.json（代码路径 → 文档路径映射）
  2. 命中映射 → 写入对应 05-笔记.md
  3. 未命中但属于 docs/ 变更 → 写入全局 docs/01-活跃/05-笔记.md
  4. 未命中但属于 gacha_simulator/ 变更 → 写入全局 05-笔记.md（提醒补充映射）

exit: 0 (永不阻止——纯记录)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_hook_input, get_main_repo_root


def _load_file_map(project_root: Path) -> dict[str, str]:
    """加载代码路径→文档路径映射表。"""
    map_path = project_root / ".claude" / "file_map.json"
    if not map_path.exists():
        return {}
    try:
        return json.loads(map_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {}


def _find_notes_target(file_path: str, project_root: Path, file_map: dict[str, str]) -> Path | None:
    """
    找到变更文件对应的 05-笔记.md。
    返回 None 表示使用全局默认。
    """
    # 1. 精确匹配映射表
    if file_path in file_map:
        notes_path = project_root / file_map[file_path]
        if notes_path.exists():
            return notes_path

    # 2. 模糊匹配：检查映射表中是否有前缀匹配
    for mapped_src, mapped_dst in file_map.items():
        if file_path.startswith(mapped_src) or mapped_src.startswith(file_path):
            notes_path = project_root / mapped_dst
            if notes_path.exists():
                return notes_path

    # 3. 若变更在 docs/ 下，写入全局活跃 05-笔记
    if file_path.startswith("docs/"):
        global_notes = project_root / "docs" / "01-活跃" / "05-笔记.md"
        if global_notes.exists():
            return global_notes

    return None


def _append_log_entry(notes_path: Path, operation: str, file_path: str):
    """追加日志条目到笔记文件。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n| {now} | {operation} | {file_path} |"

    try:
        # 确保父目录存在
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        with open(notes_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except IOError:
        # 写入失败时静默——日志丢失不应阻塞操作
        pass


def main():
    hook_input = read_hook_input()
    cwd = hook_input.get("cwd", None)
    project_root = get_main_repo_root(cwd=cwd)

    if project_root is None:
        return 0

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return 0

    # 只记录 gacha_simulator/ 和 docs/ 下的变更
    if not (file_path.startswith("gacha_simulator/") or file_path.startswith("docs/")):
        return 0

    # 排除纯收件箱写入（避免 agent 间通信产生日志噪音）
    if "04-收件箱" in file_path:
        return 0

    # 排除 05-笔记.md 自身的变更（避免递归记录）
    if file_path.endswith("05-笔记.md"):
        return 0

    # 排除 CLAUDE.md 的变更（H4 记录的原始数据供 C3 生成周报用——CLAUDE.md 的变更在 git log 中有完整记录）
    if file_path.endswith("CLAUDE.md"):
        return 0

    file_map = _load_file_map(project_root)
    notes_target = _find_notes_target(file_path, project_root, file_map)

    if notes_target is None:
        # 未找到映射——写入全局笔记
        notes_target = project_root / "docs" / "01-活跃" / "05-笔记.md"

    operation = "Write" if tool_name == "Write" else "Edit"
    _append_log_entry(notes_target, operation, file_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
