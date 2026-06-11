#!/usr/bin/env python3
"""
H5 PreToolUse Hook —— 版本号/Tab 列表一致性校验。

触发：PreToolUse(Bash(git commit:*))
自适应检测 CLAUDE.md 格式：
  阶段 7 前（硬编码版本号）：检查 _version.py vs CLAUDE.md vs 技术栈.md 三者一致
  阶段 7 后（引用格式）：检查 CLAUDE.md 含版本号引用 → 验证 _version.py vs 技术栈.md 一致

exit 0: 一致，放行
exit 2: 不一致，阻止提交
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_hook_input, get_main_repo_root


def _read_file(path: Path) -> str:
    """安全读文件。"""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _extract_version_from_file(content: str) -> str | None:
    """从文件内容中提取版本号（vX.Y.Z 或 X.Y.Z 格式）。"""
    for line in content.splitlines():
        m = re.search(r'v?(\d+\.\d+\.\d+)', line)
        if m and ("版本" in line or "version" in line.lower()):
            return m.group(1)
    return None


def _extract_tabs_from_main(content: str) -> list[str]:
    """从 main.py 提取 Tab 名称列表。"""
    tabs = []
    for line in content.splitlines():
        # 匹配 addTab(SomePanel(), "Tab名") 或类似模式
        m = re.search(r'addTab\([^,]+,\s*"([^"]+)"', line)
        if m:
            tabs.append(m.group(1))
    return tabs


def _find_tabs_in_claude(content: str) -> list[str]:
    """从 CLAUDE.md 提取硬编码的 Tab 列表。返回空 = 未硬编码（阶段 7 后）。"""
    tabs = []
    in_tab_section = False
    for line in content.splitlines():
        if "Tab" in line and ("列表" in line or "包含" in line):
            in_tab_section = True
            continue
        if in_tab_section:
            m = re.search(r'["「]([^"」]+)["」]', line)
            if m:
                tabs.append(m.group(1))
            if not line.strip() or line.startswith("```"):
                break
    return tabs


def _has_hardcoded_version(content: str) -> bool:
    """检测 CLAUDE.md 是否包含硬编码版本号。"""
    for line in content.splitlines():
        if re.search(r'v\d+\.\d+\.\d+', line) and ("版本" in line or "version" in line.lower()):
            return True
    return False


def main():
    hook_input = read_hook_input()
    cwd = hook_input.get("cwd", None)
    project_root = get_main_repo_root(cwd=cwd)

    if project_root is None:
        return 0

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    if "git commit" not in command:
        return 0

    # ── 读取所有相关文件 ─────────────────────────────────
    version_file = project_root / "gacha_simulator" / "_version.py"
    claude_md = project_root / "CLAUDE.md"
    tech_stack = project_root / "docs" / "00-meta" / "技术栈.md"
    main_py = project_root / "gacha_simulator" / "main.py"

    init_content = _read_file(version_file)
    claude_content = _read_file(claude_md)
    tech_content = _read_file(tech_stack)

    errors = []

    # ── 版本号检查 ──────────────────────────────────────
    init_version = _extract_version_from_file(init_content)
    tech_version = _extract_version_from_file(tech_content)
    claude_has_hardcoded = _has_hardcoded_version(claude_content)
    claude_version = _extract_version_from_file(claude_content) if claude_has_hardcoded else None

    if init_version is None:
        errors.append("无法从 _version.py 提取版本号")

    if claude_has_hardcoded:
        # 阶段 7 前格式——三者一致
        if init_version and claude_version and init_version != claude_version:
            errors.append(f"版本号不一致: _version.py={init_version} vs CLAUDE.md={claude_version}")
        if init_version and tech_version and init_version != tech_version:
            errors.append(f"版本号不一致: _version.py={init_version} vs 技术栈.md={tech_version}")
    else:
        # 阶段 7 后格式——CLAUDE.md 不含硬编码版本号，只检查 _version.py vs 技术栈.md
        if init_version and tech_version and init_version != tech_version:
            errors.append(f"版本号不一致: _version.py={init_version} vs 技术栈.md={tech_version}")
        # 验证 CLAUDE.md 含版本号引用
        if "version" not in claude_content.lower() and "版本" not in claude_content:
            errors.append("CLAUDE.md 缺少版本号引用（应指向 _version.py）")

    # ── Tab 列表检查 ────────────────────────────────────
    main_content = _read_file(main_py)
    actual_tabs = _extract_tabs_from_main(main_content)
    claude_tabs = _find_tabs_in_claude(claude_content)

    if claude_tabs and actual_tabs:
        # 只报告缺失的 Tab（新增 Tab 未在 CLAUDE.md 中反映）
        missing = set(actual_tabs) - set(claude_tabs)
        if missing:
            errors.append(f"CLAUDE.md Tab 列表缺少: {', '.join(sorted(missing))}")

    if errors:
        print("🚫 H5 版本/结构一致性校验失败:", file=sys.stderr)
        for e in errors:
            print(f"   • {e}", file=sys.stderr)
        print("   修复: 更新 CLAUDE.md / 技术栈.md 中的版本号/Tab 列表，或运行 C1 cron 自动修复。", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
