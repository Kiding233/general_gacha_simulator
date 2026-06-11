#!/usr/bin/env python3
"""
H3 PreToolUse Hook —— commit 信息校验。

触发：PreToolUse(Bash(git commit:*))
exit 0: 格式合规，放行
exit 2: 格式不合规，阻止提交

校验规则：Conventional Commits
  type(scope): description
  type: description
允许类型: feat, fix, docs, style, refactor, perf, test, chore, ci, build, revert
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_hook_input, check_conventional_commit


def _extract_commit_message(command: str) -> str:
    """从 git commit 命令中提取提交信息。"""
    # 匹配 git commit -m "message" 或 git commit -m 'message'
    for quote in ['"', "'"]:
        m = re.search(rf'-m\s*{quote}([^{quote}]*){quote}', command)
        if m:
            return m.group(1)
    # 未找到 -m → 可能是编辑器模式，放行（编辑器模式无法在此校验）
    return ""


def main():
    hook_input = read_hook_input()
    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # 只拦截 git commit
    if "git commit" not in command:
        return 0

    # 检测 amend / merge commit
    if "--amend" in command or "-m" not in command:
        # amend 或编辑器模式——不校验（amend 保留原信息，编辑器模式无法在此解析）
        return 0

    msg = _extract_commit_message(command)
    if not msg:
        # 无 -m 参数，可能是编辑器模式
        return 0

    # [auto] 前缀的 commit（cron agent 产出）——放宽校验
    if msg.startswith("[auto]"):
        # 确保基本格式正确但不强制完整 Conventional Commits
        return 0

    passed, error = check_conventional_commit(msg)
    if not passed:
        print(f"🚫 H3 提交信息格式错误:", file=sys.stderr)
        print(f"   {error}", file=sys.stderr)
        print(f"   正确示例: feat: 添加xxx功能", file=sys.stderr)
        print(f"             fix: 修复xxx问题", file=sys.stderr)
        print(f"             docs: 更新xxx文档", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
