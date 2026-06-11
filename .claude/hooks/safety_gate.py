#!/usr/bin/env python3
"""
H2 PreToolUse Hook —— 安全门禁。

三层防护：
  1. AGENT_FREEZE 紧急冻结 —— 文件存在则阻止所有 Bash 操作（最高优先级）
  2. 危险命令拦截 —— rm -rf /、git push --force main、生产环境操作等
  3. HARNESS_BYPASS 紧急旁路 —— 存在则降级 H7/H9 为 warn-only

触发：PreToolUse(Bash)
exit 0: 安全，放行
exit 1: 警告（旁路模式提示）
exit 2: 硬阻止（冻结 / 危险命令）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_hook_input, get_main_repo_root

# 危险命令模式列表 (正则，不区分大小写)
DANGEROUS_PATTERNS = [
    (r"rm\s+-rf\s+/", "禁止递归删除根目录"),
    (r"rm\s+-rf\s+/\*", "禁止递归删除根目录文件"),
    (r"git\s+push\s+--force\s+.*main", "禁止强制推送到 main 分支"),
    (r"git\s+push\s+-f\s+.*main", "禁止强制推送到 main 分支"),
    (r":\s*>\s*/dev/sda", "禁止直接写入磁盘设备"),
    (r"mkfs\.", "禁止格式化命令"),
    (r"dd\s+if=", "禁止 dd 磁盘操作"),
    (r"chmod\s+-R\s+777\s+/", "禁止递归开放根目录权限"),
    (r"git\s+reset\s+--hard\s+origin/main", "警告：硬重置到远程 main"),
]


def main():
    import re

    hook_input = read_hook_input()
    cwd = hook_input.get("cwd", None)
    project_root = get_main_repo_root(cwd=cwd)

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # ── 检查 AGENT_FREEZE（最高优先级）──────────────────
    if project_root:
        freeze_file = project_root / "AGENT_FREEZE"
        if freeze_file.exists():
            print("🚫 H2 紧急冻结: AGENT_FREEZE 文件存在——所有 agent 操作已被阻止。", file=sys.stderr)
            print("   移除 AGENT_FREEZE 文件以恢复正常操作。", file=sys.stderr)
            return 2

    # ── 检查 HARNESS_BYPASS ─────────────────────────────
    bypass_active = False
    if project_root:
        bypass_file = project_root / "HARNESS_BYPASS"
        bypass_active = bypass_file.exists()

    # ── 检查危险命令 ────────────────────────────────────
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            print(f"🚫 H2 安全门禁: {reason}", file=sys.stderr)
            print(f"   命令: {command[:120]}", file=sys.stderr)
            print(f"   此操作已被硬阻止。如需绕过，请确认风险后手动在终端执行。", file=sys.stderr)
            return 2

    # ── 旁路模式提示 ────────────────────────────────────
    if bypass_active:
        print("⚠️  [H2] HARNESS_BYPASS 存在——H7/H9 门禁已降级为 warn-only。", file=sys.stderr)
        print("   请尽快删除 HARNESS_BYPASS 恢复正常门禁（C4 将在 30 分钟后自动删除）。", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
