#!/usr/bin/env python3
"""
H8 PreCompact Hook —— 上下文保存。

触发：PreCompact（上下文即将被压缩时）
动作：保存当前任务状态、关键决策、进行中计划到 checkpoint。

路径自适应：
  - worktree 内运行 → 写入主仓库 .claude/worktrees/{task-name}-checkpoint.json
  - 主仓库内运行 → 写入 .claude/checkpoint.json
  （worktree 可能被 force-remove，checkpoint 必须存在主仓库）

exit: 0（永不阻止——纯保存）
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    read_hook_input,
    get_main_repo_root,
    is_in_worktree,
    get_worktree_name,
)


def _read_git_log_summary(project_root: Path, n: int = 5) -> str:
    """获取最近 N 个 commit 摘要。"""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "-n", str(n)],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(project_root), timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _get_current_branch(project_root: Path) -> str:
    """获取当前分支名。"""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(project_root), timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def main():
    hook_input = read_hook_input()
    cwd = hook_input.get("cwd", None)
    main_repo = get_main_repo_root(cwd=cwd)

    if main_repo is None:
        return 0

    session_id = hook_input.get("session_id", "unknown")
    transcript_path = hook_input.get("transcript_path", "")

    now = datetime.now(timezone.utc)
    branch = _get_current_branch(main_repo)
    recent_commits = _read_git_log_summary(main_repo, 5)

    checkpoint = {
        "saved_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "session_id": session_id,
        "branch": branch,
        "recent_commits": recent_commits.split("\n") if recent_commits else [],
        "transcript_path": transcript_path,
        # 以下字段为可扩展的占位——agent 可通过 Bash 追加内容
        "task": "",
        "completed_step": "",
        "decision_summary": "",
        "pending_actions": [],
    }

    # ── 确定 checkpoint 路径 ────────────────────────────
    if is_in_worktree(cwd=cwd):
        wt_name = get_worktree_name(cwd=cwd) or session_id.replace("/", "-")
        # 确保写入主仓库
        cp_dir = main_repo / ".claude" / "worktrees"
        cp_dir.mkdir(parents=True, exist_ok=True)
        cp_path = cp_dir / f"{wt_name}-checkpoint.json"
    else:
        cp_path = main_repo / ".claude" / "checkpoint.json"

    # ── 写入 ────────────────────────────────────────────
    try:
        cp_path.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except IOError:
        # 写入失败静默——不阻塞压缩
        pass

    # ── 输出精简摘要供压缩后恢复使用 ─────────────────────
    output_lines = [
        f"[H8] checkpoint 已保存 → {cp_path.relative_to(main_repo)}",
        f"分支: {branch} | 时间: {now.strftime('%H:%M UTC')}",
    ]
    if recent_commits:
        output_lines.append(f"最近提交: {recent_commits.split(chr(10))[0] if recent_commits else '无'}")

    print("\n".join(output_lines))

    return 0


if __name__ == "__main__":
    sys.exit(main())
