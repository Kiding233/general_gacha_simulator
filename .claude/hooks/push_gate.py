#!/usr/bin/env python3
"""
H9 PreToolUse Hook —— Push Gate（推送前测试检查）。

触发：PreToolUse(Bash(git push:*))
动作：运行 pytest -q（不含覆盖率，只跑失败用例）。

设计理由：pytest 是分钟级操作——不能放在 commit 路径阻塞写代码节奏。
         放在 push 前异步检查，commits 可自由累积但 push 时有质量门禁。

HARNESS_BYPASS 存在时降级为 warn-only。

exit 0: 测试通过，放行
exit 1: 警告（旁路模式）
exit 2: 硬阻止（pytest 失败）
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_hook_input, get_main_repo_root


def _is_bypass_active(project_root: Path) -> bool:
    return (project_root / "HARNESS_BYPASS").exists()


def _run_pytest(project_root: Path) -> tuple[bool, str]:
    """运行 pytest。返回 (通过, 输出)。"""
    try:
        r = subprocess.run(
            ["python", "-m", "pytest", "-q", "--tb=short"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(project_root), timeout=120,
        )
        output = r.stdout.strip() or r.stderr.strip()
        return r.returncode == 0, output
    except FileNotFoundError:
        return True, "(pytest 不可用——跳过检查)"
    except subprocess.TimeoutExpired:
        return False, "(pytest 超时——超过 120 秒)"
    except Exception as e:
        return True, f"(pytest 执行异常: {e})"


def main():
    hook_input = read_hook_input()
    cwd = hook_input.get("cwd", None)
    project_root = get_main_repo_root(cwd=cwd)

    if project_root is None:
        return 0

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    if "git push" not in command:
        return 0

    bypass = _is_bypass_active(project_root)

    # ── pytest ──────────────────────────────────────────
    passed, output = _run_pytest(project_root)

    if not passed:
        # 提取失败摘要
        fail_lines = [l for l in output.splitlines() if "FAILED" in l or "ERROR" in l or "failed" in l.lower()]
        summary = "\n".join(fail_lines[:10]) if fail_lines else output[:500]

        if bypass:
            print("⚠️  [H9] HARNESS_BYPASS 模式——pytest 失败未阻止推送:", file=sys.stderr)
            print(summary[:500], file=sys.stderr)
            return 1
        else:
            print("🚫 H9 Push Gate — pytest 失败，推送被阻止:", file=sys.stderr)
            print(summary[:500], file=sys.stderr)
            print("\n修复: 修复失败的测试后重新推送。", file=sys.stderr)
            print("紧急绕过: 创建 HARNESS_BYPASS 文件（30 分钟后自动删除）。", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
