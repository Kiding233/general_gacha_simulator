#!/usr/bin/env python3
"""
H1 SessionStart Hook —— 上下文注入。

在每次会话启动时注入：
  1. 最近 10 条 git log
  2. 本周聚焦摘要
  3. P0 阻塞项列表
  4. Deep Evaluator 最新审查报告（若存在）
  5. 未完成 checkpoint 恢复提示（若存在）

优雅降级：任何文件不存在时静默跳过，不报错、不阻塞。
exit: 0 (永不阻止会话启动)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 将父目录加入 sys.path 以便导入 common
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    read_hook_input,
    get_main_repo_root,
    get_current_root,
    is_in_worktree,
    find_checkpoints,
    find_latest_files,
    extract_version_from_init,
)


def _read_file(path: Path) -> str:
    """安全读文件——失败返回空字符串。"""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_first_lines(path: Path, n: int = 30) -> str:
    """读取文件前 N 行。"""
    try:
        with open(path, encoding="utf-8") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= n:
                    break
                lines.append(line.rstrip())
            return "\n".join(lines)
    except Exception:
        return ""


def _get_last_n_git_log(project_root: Path, n: int = 10) -> str:
    """获取最近 N 条 git log（一行格式）。"""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "-n", str(n)],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(project_root), timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else "(无法获取 git log)"
    except Exception:
        return "(无法获取 git log)"


def _extract_p0_items(matrix_content: str) -> list[str]:
    """从模块状态矩阵中提取 P0 列表。"""
    import re
    p0_items = []
    in_p0_section = False
    for line in matrix_content.splitlines():
        if "### P0" in line:
            in_p0_section = True
            continue
        if in_p0_section:
            if line.startswith("### ") or line.startswith("## "):
                break
            # 匹配 | P{n} | ...
            m = re.match(r'\|\s*(P\d+)\s*\|', line)
            if m:
                p0_items.append(line.strip())
    return p0_items


def _summarize_checkpoint(cp_path: Path) -> str:
    """提取 checkpoint 摘要（前 500 字符）。"""
    try:
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        task = data.get("task", data.get("task_name", "未知任务"))
        step = data.get("completed_step", data.get("step", "未知"))
        summary = data.get("summary", data.get("decision_summary", ""))
        ts = data.get("saved_at", "")
        lines = [f"- **{task}** → 已完成: {step}"]
        if summary:
            lines.append(f"  摘要: {summary[:200]}")
        if ts:
            lines.append(f"  保存时间: {ts}")
        return "\n".join(lines)
    except Exception:
        return f"- 存在但无法解析: {cp_path.name}"


def main():
    hook_input = read_hook_input()
    cwd = hook_input.get("cwd", None)
    project_root = get_main_repo_root(cwd=cwd)
    current_root = get_current_root(cwd=cwd)

    if project_root is None:
        print("⚠️ [H1] 无法确定项目根目录，跳过上下文注入。")
        return 0

    output_parts = []

    # ── 1. 工作区状态 ──────────────────────────────────
    if is_in_worktree(cwd=cwd):
        wt_name = current_root.name if current_root else "unknown"
        output_parts.append(f"## 🔧 当前位于 Worktree: `{wt_name}`\n")
        output_parts.append("> 操作在隔离环境中进行——不影响主分支。破坏性操作安全。")

    # ── 2. 最近提交历史 ────────────────────────────────
    git_log = _get_last_n_git_log(project_root)
    if git_log:
        output_parts.append(f"## 📜 最近 10 条提交\n```\n{git_log}\n```")

    # ── 3. 版本号 ──────────────────────────────────────
    version = extract_version_from_init(project_root)
    if version:
        output_parts.append(f"**当前版本:** `{version}`")

    # ── 4. 本周聚焦 ────────────────────────────────────
    weekly_focus = project_root / "docs" / "01-活跃" / "00-本周聚焦.md"
    if weekly_focus.exists():
        summary = _read_first_lines(weekly_focus, 40)
        if summary.strip():
            output_parts.append(f"## 🎯 本周聚焦\n{summary}")

    # ── 5. P0 阻塞项 ────────────────────────────────────
    matrix_file = project_root / "docs" / "00-meta" / "模块状态矩阵.md"
    if matrix_file.exists():
        matrix_content = _read_file(matrix_file)
        p0_items = _extract_p0_items(matrix_content)
        if p0_items:
            items_str = "\n".join(p0_items[:5])  # 最多 5 条
            output_parts.append(f"## 🔴 P0 阻塞项\n{items_str}")

    # ── 6. Deep Evaluator 审查报告 ─────────────────────
    inbox_dir = project_root / "docs" / "01-活跃" / "04-收件箱"
    eval_files = find_latest_files(inbox_dir, "eval-*.md", count=3)
    if eval_files:
        eval_summaries = []
        for ef in eval_files:
            first_lines = _read_first_lines(ef, 5)
            # 提取标题行
            title = ""
            for line in first_lines.splitlines():
                if line.startswith("#") and ("FAIL" in line or "CLEAN" in line or "REVIEW" in line):
                    title = line.lstrip("#").strip()
                    break
            eval_summaries.append(f"- [{ef.name}]({ef}) — {title}" if title else f"- [{ef.name}]({ef})")
        if eval_summaries:
            output_parts.append(f"## 📋 最新审查报告 (Deep Evaluator)\n" + "\n".join(eval_summaries))

    # ── 6b. P38 计划审查报告 ────────────────────────────
    peer_review_files = find_latest_files(inbox_dir, "peer-review-*.md", count=2)
    if peer_review_files:
        pr_lines = []
        for pf in peer_review_files:
            first_lines = _read_first_lines(pf, 3)
            title = ""
            for line in first_lines.splitlines():
                if line.startswith("#"):
                    title = line.lstrip("#").strip()
                    break
            pr_lines.append(f"- [{pf.name}]({pf}) — {title}" if title else f"- [{pf.name}]({pf})")
        if pr_lines:
            output_parts.append(f"## 📋 计划审查报告 (P38)\n" + "\n".join(pr_lines))

    # ── 7. 未完成 checkpoint ───────────────────────────
    checkpoints = find_checkpoints(project_root)
    if checkpoints:
        cp_lines = []
        for cp in checkpoints[:3]:  # 最多 3 个
            cp_lines.append(_summarize_checkpoint(cp))
        if cp_lines:
            output_parts.append(f"## 🔄 未完成任务 (checkpoint)\n" + "\n".join(cp_lines))
            # 孤儿 checkpoint 检测
            orphan = []
            for cp in checkpoints:
                name = cp.stem.replace("-checkpoint", "")
                wt_dir = project_root / ".claude" / "worktrees" / name
                if name != "checkpoint" and not wt_dir.is_dir() and not (project_root / ".." / f"task-{name}").is_dir():
                    orphan.append(name)
            if orphan:
                output_parts.append(f"\n⚠️ **孤儿 checkpoint:** {', '.join(orphan)} — worktree 已删除但 checkpoint 残留。使用 `--session-id {orphan[0]}` 恢复。")

    # ── 8. HARNESS_BYPASS 提示 ─────────────────────────
    bypass_file = project_root / "HARNESS_BYPASS"
    if bypass_file.exists():
        output_parts.append("\n⚠️ ⚠️ ⚠️ **当前处于 HARNESS_BYPASS 旁路模式** —— H7/H9 已降级为 warn-only。请尽快删除 HARNESS_BYPASS 文件恢复正常门禁。")

    # ── 输出 ────────────────────────────────────────────
    if output_parts:
        print("\n\n".join(output_parts))
    else:
        print("[H1] 无额外上下文注入（所有数据源为空或不存在，属于正常状态）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
