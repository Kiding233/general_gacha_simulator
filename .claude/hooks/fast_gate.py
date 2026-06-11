#!/usr/bin/env python3
"""
H7 PreToolUse Hook —— Fast Gate（提交前快速检查）。

触发：PreToolUse(Bash(git commit:*))
动作：
  1. ruff check（毫秒级——代码格式 + 基本质量）
  2. 目录边界检查（变更文件是否在允许的目录内）

注意：pytest 不在此处执行——pytest 在 push 时由 H9 异步检查。
     HARNESS_BYPASS 存在时降级为 warn-only（不阻止提交）。

exit 0: 通过，放行
exit 1: 警告（旁路模式）
exit 2: 硬阻止（ruff 失败 / 目录越界）
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_hook_input, get_main_repo_root

# 允许变更的目录
ALLOWED_DIRS = ["gacha_simulator/", "docs/", "config/", ".claude/"]


def _is_bypass_active(project_root: Path) -> bool:
    return (project_root / "HARNESS_BYPASS").exists()


def _get_staged_files(project_root: Path) -> list[str]:
    """获取暂存区文件列表。Windows 下 git 可能输出 GBK 编码的中文路径，
    先用 utf-8 解码，失败则回退 GBK。同时统一反斜杠为正斜杠。"""
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(project_root), timeout=10,
        )
        if r.returncode != 0:
            return []
        lines = r.stdout.splitlines()
    except (UnicodeDecodeError, LookupError):
        # utf-8 解码失败，回退 GBK（Windows 中文系统默认编码）
        try:
            r = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                capture_output=True, text=True, encoding="gbk",
                cwd=str(project_root), timeout=10,
            )
            if r.returncode != 0:
                return []
            lines = r.stdout.splitlines()
        except Exception:
            return []
    except Exception:
        return []
    return [f.strip().replace('\\', '/') for f in lines if f.strip()]


def _run_ruff(project_root: Path) -> tuple[bool, str]:
    """运行 ruff check。返回 (通过, 输出)。"""
    try:
        r = subprocess.run(
            ["ruff", "check", "gacha_simulator/"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(project_root), timeout=30,
        )
        output = r.stdout.strip() or r.stderr.strip()
        return r.returncode == 0, output
    except FileNotFoundError:
        return True, "(ruff 未安装——跳过检查)"
    except Exception as e:
        return True, f"(ruff 执行异常: {e})"


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

    bypass = _is_bypass_active(project_root)
    errors = []

    # ── 1. 目录边界检查 ─────────────────────────────────
    staged_files = _get_staged_files(project_root)
    for f in staged_files:
        if not any(f.startswith(d) for d in ALLOWED_DIRS):
            errors.append(f"文件越界: {f}（不在允许目录 {ALLOWED_DIRS} 中）")

    # ── 2. ruff check ───────────────────────────────────
    ruff_ok, ruff_output = _run_ruff(project_root)
    if not ruff_ok:
        errors.append(f"ruff check 失败:\n{ruff_output[:500]}")

    # ── 判定 ────────────────────────────────────────────
    if errors:
        if bypass:
            print("⚠️  [H7] HARNESS_BYPASS 模式——以下问题未阻止提交:", file=sys.stderr)
            for e in errors:
                print(f"   • {e[:200]}", file=sys.stderr)
            return 1  # 降级为警告
        else:
            print("🚫 H7 Fast Gate 阻止提交:", file=sys.stderr)
            for e in errors:
                print(f"   • {e[:200]}", file=sys.stderr)
            print("   修复: 将文件移至允许目录，或运行 `ruff check --fix` 自动修复。", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
