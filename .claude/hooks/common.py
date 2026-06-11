"""
Harness 公共工具模块 —— 所有 hook 脚本的共享基础设施。

职责：项目根检测、worktree 感知、checkpoint 搜索、输入解析。
此模块被 9 个 hook 脚本导入，不独立运行。
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── 路径检测 ─────────────────────────────────────────────


def _run_git(args: list[str], cwd: Optional[str] = None) -> str:
    """运行 git 命令，返回 stdout。失败时返回空字符串。"""
    try:
        r = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, encoding="utf-8",
            cwd=cwd, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def get_current_root(cwd: Optional[str] = None) -> Optional[Path]:
    """当前工作树的根目录（worktree 内返回 worktree 根；主仓库返回主仓库根）。"""
    out = _run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(out) if out else None


def get_main_repo_root(cwd: Optional[str] = None) -> Optional[Path]:
    """主仓库根目录——即使在 worktree 内也返回主仓库路径。"""
    out = _run_git(["rev-parse", "--git-common-dir"], cwd=cwd)
    if not out:
        return None
    common = Path(out)
    # --git-common-dir 返回 .git 目录路径；主仓库在其父目录
    if common.name == ".git":
        return common.parent
    # 某些 git 版本返回绝对路径到 .git 目录
    return common.parent if common.name == ".git" else common


def is_in_worktree(cwd: Optional[str] = None) -> bool:
    """判断当前是否在 git worktree 内执行。"""
    main = get_main_repo_root(cwd=cwd)
    cur = get_current_root(cwd=cwd)
    if main is None or cur is None:
        return False
    return main.resolve() != cur.resolve()


def get_worktree_name(cwd: Optional[str] = None) -> Optional[str]:
    """若在 worktree 内，返回 worktree 名称（从路径推断）。否则返回 None。"""
    if not is_in_worktree(cwd):
        return None
    cur = get_current_root(cwd=cwd)
    return cur.name if cur else None


# ── 输入解析 ─────────────────────────────────────────────


def read_hook_input() -> dict:
    """读取 Claude Code 通过 stdin 传入的 hook 事件 JSON。"""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, IOError):
        return {}


# ── checkpoint 搜索 ──────────────────────────────────────


def find_checkpoints(project_root: Path) -> list[Path]:
    """搜索所有 checkpoint 文件。返回按修改时间降序排列的路径列表。"""
    checkpoints = []

    # 主仓库 checkpoint
    main_checkpoint = project_root / ".claude" / "checkpoint.json"
    if main_checkpoint.exists():
        checkpoints.append(main_checkpoint)

    # worktree checkpoints
    wt_dir = project_root / ".claude" / "worktrees"
    if wt_dir.is_dir():
        for f in sorted(wt_dir.glob("*-checkpoint.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            checkpoints.append(f)

    return checkpoints


# ── 文件扫描 ─────────────────────────────────────────────


def find_latest_files(directory: Path, pattern: str, count: int = 3) -> list[Path]:
    """在目录中查找匹配 glob 的最新 N 个文件。"""
    if not directory.is_dir():
        return []
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:count]


# ── 文档扫描 ─────────────────────────────────────────────


def scan_module_notes(docs_dir: Path, max_stale_days: int = 7) -> list[dict]:
    """扫描所有模块的 05-笔记.md，返回超过阈值的列表。"""
    stale = []
    now = datetime.now(timezone.utc)
    for notes_file in docs_dir.rglob("05-笔记.md"):
        try:
            mtime = datetime.fromtimestamp(notes_file.stat().st_mtime, tz=timezone.utc)
            days_ago = (now - mtime).days
            if days_ago > max_stale_days:
                # 提取模块名
                rel = notes_file.relative_to(docs_dir)
                module = str(rel.parent) if rel.parent != Path(".") else "根目录"
                stale.append({"module": module, "path": str(notes_file), "days_ago": days_ago})
        except OSError:
            continue
    return sorted(stale, key=lambda x: x["days_ago"], reverse=True)


# ── 版本号提取 ──────────────────────────────────────────


def extract_version_from_init(project_root: Path) -> Optional[str]:
    """从 _version.py 提取版本号字符串。"""
    version_file = project_root / "gacha_simulator" / "_version.py"
    if not version_file.exists():
        return None
    try:
        content = version_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("__version__"):
                # 匹配 __version__ = "1.10.0" 或 __version__ = '1.10.0'
                for quote in ['"', "'"]:
                    if quote in line:
                        return line.split(quote)[1]
    except Exception:
        return None
    return None


def extract_version_from_claude_md(project_root: Path) -> Optional[str]:
    """从 CLAUDE.md 提取硬编码版本号。返回 None 表示未硬编码（阶段 7 后格式）。"""
    claude_md = project_root / "CLAUDE.md"
    if not claude_md.exists():
        return None
    try:
        content = claude_md.read_text(encoding="utf-8")
        for line in content.splitlines():
            if "版本号" in line or "version" in line.lower():
                # 尝试匹配 vX.Y.Z 或 X.Y.Z 格式的硬编码版本号
                import re
                m = re.search(r'v?(\d+\.\d+\.\d+)', line)
                if m:
                    return m.group(1)
    except Exception:
        return None
    return None


# ── 格式校验 ─────────────────────────────────────────────


def check_conventional_commit(msg: str) -> tuple[bool, str]:
    """校验 Conventional Commits 格式。返回 (通过, 错误信息)。"""
    import re
    # 允许的类型
    allowed_types = r'(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)'
    # 格式: type(scope): description 或 type: description
    pattern = rf'^{allowed_types}(\([^)]+\))?!?: .+'
    if re.match(pattern, msg.strip()):
        return True, ""
    return False, f"提交信息不符合 Conventional Commits 格式: {msg[:80]}\n期望格式: type(scope): description\n允许类型: feat, fix, docs, style, refactor, perf, test, chore, ci, build, revert"
