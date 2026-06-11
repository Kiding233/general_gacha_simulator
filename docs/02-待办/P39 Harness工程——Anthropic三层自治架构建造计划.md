<!-- META: P39 | module:00-meta | status:completed | last:2026-06-11 -->
# P39 Harness工程——Anthropic三层自治架构建造计划

> 日期：2026-06-11 | 版本：v2.8
> 状态：**✅ 已完成**（2026-06-11）
> v2.8 修订：实施前操作性加固——新增 §八 成本估算（日均/月均 token + 降频策略）；C3/C5 改为"每天运行+周一产出"规避 7 天过期；新增 file_map.json 引导期手动维护方案；阶段 1 新增 worktree+hooks 兼容性烟雾测试；H1 优雅降级（找不到 eval 报告时静默跳过）；阶段 6 新增合并执行策略（agent pipeline + 断链验证）；新增 settings.local.json 权限矩阵草案；风险表追加 4 条
> v2.7 修订：长时运行安全加固——checkpoint 从 worktree 内移至主仓库 `.claude/worktrees/{name}-checkpoint.json`（H8 路径自适应 + H1 双路径搜索）；worktree 生命周期新增孤儿恢复 + checkpoint 清理；新增 4e 已知限制（5 项设计边界）；架构图/文件清单同步
> v2.6 修订：实施前最终评审——七阶段网状依赖图 + 并行策略、H5 自适应阶段检测（移除手动切换）、C2 升级门控量化（3 条件）、C6 心跳监控（cron 静默失败检测）、H2 紧急旁路机制（HARNESS_BYPASS 文件）、H4 映射外置为 file_map.json（C2 自动维护）、阶段 6→7 间验证步骤、验证脚本骨架、P38 收件箱命名空间预留
> v2.5 修订：一致性扫尾——架构图移除 pytest 残留、旧文件名引用全部更新为阶段 6 合并后的名称、H5 增加阶段 7 后逻辑分叉、H4 补充文件路径映射规范、eval 命名统一、拼写修正
> v2.4 修订：阶段 6 升级——新增 agent META 元数据头规范 + 04-收件箱/ 命名/生命周期/清理规范 + 全局约定.md 精简方案；阶段 7 重构——CLAUDE.md 三层结构（项目事实/架构约束/Harness使用指南）+ 具体删除清单 + 验证标准
> v2.3 修订：闭合 Cron→Eval→Cron 反馈环（cron agent 启动时读 eval 报告）；E1 增加升级标记（ESCALATE→Planner）；C3 追加计划完成检测；三个断裂环全部闭合
> v2.2 修订：Fast Gate 去掉 pytest → H9 push_gate；H4 降级为纯事实记录；H6 永不 block；E1 形式化 Default-FAIL 判定表；C2 Phase 1 只读报告；C5 收缩去 ruff 重复项；Session 命名修正（checkpoint.json）
> 涉及文件：`.claude/settings.local.json`（修改——hooks 段 + 权限矩阵 + CronCreate × 7）、`.claude/scheduled_tasks.json`（自动生成——durable cron 持久化）、`.claude/hooks/*`（新建 9 个 hook + 7 个可选 verify）、CronCreate × 7、`.claude/file_map.json`（新建，C2 自动维护 + 引导期手动创建）、`.claude/heartbeats/`（新建，cron 心跳目录）、`docs/` 精简、CLAUDE.md 重写
> 前置：无强制依赖。依赖 superpowers 的 `using-git-worktrees` + `verification-before-completion` skill。
> 注意：P39 先行——先修好维护管道，再跑 P38 审查流水线。

---

## 一、问题概述

### 1.1 当前状态

项目有完整的 CLAUDE.md 指导 + 18模块×6文件文档系统 + 20+计划管理矩阵，但：

| 问题 | 根因 | 证据 |
|------|------|------|
| CLAUDE.md 版本号 v1.10.0 实际 v2.0.0 | 无强制同步机制 | `_version.py:2.0.0` vs `CLAUDE.md:7:v1.10.0` |
| 本周聚焦 9 天未更新 | 纯人工维护，遗忘即腐烂 | `00-本周聚焦.md` 声称"当前会话：启动 P19"，实际 P19 已完成 |
| 18/20 审计文件空壳 | "审计后修改"的约定从未执行 | 全部 `03-审计.md` 写"首次建档，未审计" |
| 模块状态矩阵 P0 与实际开发脱节 | 人工维护跟不上开发速度 | 矩阵 P0=P18/P26-28/P31，但最近 33 次提交是 P8/P19/P33/打包 |
| 7 条全局约定中 5 条被违反 | 约定无 enforcement 层 | PR 限 gacha_simulator/ → 被 .spec/pyproject.toml 提交绕过 |

**根因：当前 harness 只有 guidance 层（CLAUDE.md）没有 enforcement 层（hooks），没有自治维护层（cron agent），没有独立审查层（evaluator agent）。**

### 1.2 核心需求

- 从 "人维护文档" 切换到 "agent 维护文档，人只写设计意图"
- Hook 强制执行那些机器可以判断的规则（版本号、提交格式、文档同步）
- Cron agent 接管周期性维护（本周聚焦、矩阵同步、腐烂检测）
- 独立 evaluator agent 做批判性审查（不参与生成，只读+报告）
- Planner 由 AI 主导——用户给出种子方向，AI 细化为可执行计划

---

## 二、目标架构：Anthropic 三层模型

### 2.1 映射关系

```
Anthropic Managed Agents 模型               GachaStat 实现
─────────────────────────────────────────────────────────────────
Session (追加事件日志, 崩溃不丢)      → Claude Code transcript JSONL
                                        + git history（commit 级事件）
                                        + 05-笔记（agent 写的时间线记录）
                                        + --session-id 断点续传
Harness (控制循环, 无状态)            → Hooks + Cron Agents + Skills
                                        + checkpoint.json (Harness 恢复快照)
Sandbox (隔离执行, 崩溃不影响上层)     → Worktree (using-git-worktrees)
                                        + max_turns 熔断

注：checkpoint.json 是 Harness 层的恢复快照，不是 Session 日志。
     Session 日志由 Claude Code 自身的 transcript 机制维护。
```

### 2.2 四层 Agent 架构

```
┌─────────────────────────────────────────────────────┐
│                 Planner (AI)                         │
│  用户给种子方向 → Agent 细化成可执行计划              │
│  触发：/plan <seed> 或 自然语言指令                   │
│  输出：计划文件 + 矩阵注册                            │
└─────────────────────┬───────────────────────────────┘
                      │ 计划文件
                      ▼
┌─────────────────────────────────────────────────────┐
│              Generator (Claude Code)                 │
│  写代码、修bug、实施计划                              │
│  ┌──────────────────────────────────────────────┐  │
│  │ Fast Gate (H7, commit) + Push Gate (H9, push) │  │
│  │  ruff + commit格式 → H7 阻止; pytest → H9 阻止 │  │
│  └──────────────────────────────────────────────┘  │
│  隔离：Worktree（破坏性操作）                        │
│  熔断：max_turns + 超时保护                          │
│  恢复：--session-id 断点续传                         │
└─────────────────────┬───────────────────────────────┘
                      │ 代码变更 + commit
                      ▼
┌─────────────────────────────────────────────────────┐
│  Deep Evaluator (独立 Cron Agent, 只读, 每6h)        │
│  独立上下文窗口 → 不污染生成上下文                    │
│  读 diff → 架构审查 + 质量审查 + 计划一致性 + 副作用  │
│  输出：04-收件箱/eval-{timestamp}.md                  │
│  不参与生成，以批驳为默认立场                          │
└─────────────────────┬───────────────────────────────┘
                      │ 审查报告
                      ▼
┌─────────────────────────────────────────────────────┐
│  Generator 下次会话 SessionStart 自动注入报告         │
│  Claude 读报告 → 自行决定是否修复                     │
└─────────────────────────────────────────────────────┘
```

### 2.3 Harness 七层

| 层 | 机制 | 确定性 | 职责 |
|----|------|--------|------|
| **Guidance** | CLAUDE.md + memory + skills | 模型可能忽略 | 惯例、偏好、项目上下文 |
| **Enforcement** | Hooks (exit 2 = 硬阻止) | ✅ 确定性 | ruff、pytest、commit 格式、危险操作拦截 |
| **Logging** | PostToolUse hooks | ✅ 确定性 | 自动追加 05-笔记、变更追踪 |
| **Periodic** | Cron agents (6个) | ✅ 确定性触发 | 版本对齐、矩阵同步、每周聚焦、腐烂检测、代码质量、心跳监控 |
| **Fast Gate** | H7 (commit) + H9 (push) | ✅ 确定性 | commit 前 ruff+目录边界 (ms级)；push 前 pytest (分钟级) |
| **Deep Eval** | Cron agent (每6h, 只读) | ✅ 确定性触发 | 独立上下文、架构审查、计划一致性 |
| **Long-Run** | Session+Worktree+熔断 | 按需 | 长时自主任务：断点续传、上下文管理、崩溃恢复 |

---

## 三、实施：七阶段

### 阶段依赖与并行策略

七阶段线性编号但实际依赖是网状的——不按正确顺序动工会导致返工：

```
阶段 1 (Hooks) ────────── 基础层，所有后续阶段依赖 ────────────┐
     │                                                         │
     ├──→ 阶段 2 (Cron) ──→ 阶段 3 (Evaluator) ──→ 阶段 6 (文档精简) ──→ 阶段 7 (CLAUDE.md重写)
     │         │                   │                               │
     │         └──→ 阶段 4 (长时运行) ←─────────────┘              │
     │                                                             │
     └──→ 阶段 5 (Planner Skill) ──── 独立，可与 1-4 并行 ────────┘

并行策略：
  第1轮：阶段 1 全部（9 hooks）+ 阶段 5（Planner skill）── 同时开工
  第2轮：阶段 2（6 cron）── 依赖阶段 1 完成
  第3轮：阶段 3（Evaluator）+ 阶段 4（长时运行）── 均依赖阶段 2 的 cron 基础设施
  第4轮：阶段 6（文档精简）── 依赖阶段 3（E1 接管审计职能）
  第5轮：阶段 7（CLAUDE.md 重写）── 依赖阶段 6（三文件体系确定后）

跨阶段约束（需特别注意）：
  - H5 sync_version.py 的行为在阶段 7 前后不同 → 采用自适应检测（见阶段 1 H5 条目），无需手动切换
  - H4 log_change.py 的路径映射依赖阶段 6 的三文件体系 → 映射表外置为 file_map.json，C2 自动维护
  - C2 的 Phase 1→2 升级必须在阶段 3（E1 运行 2 周+）之后才能评估（见阶段 2 C2 升级门控）
  - 阶段 6 删除 03-审计.md 前需确认 E1 已产出 ≥3 份审查报告（审计职能已接管）
```


### 阶段 1：Hook 强制层（9 个脚本）

**目标：** Hooks 只做确定性 enforcement——机器能 100% 判断的规则。不做需要"理解代码意图"的事，后者交给 Deep Evaluator。

**⚠️ 前置——worktree+hooks 兼容性烟雾测试（在部署全部 hooks 之前执行）：**

| 步骤 | 操作 | 验证点 |
|------|------|--------|
| 1a | 只安装 H1 `inject_state.py`（其余 hooks 暂不部署） | 确认 SessionStart hook 在主仓库正常触发 |
| 1b | `EnterWorktree` 创建一个临时 worktree | 确认 H1 在 worktree 内是否同样触发 |
| 1c | 在 worktree 内执行 `Write` + `Bash(git commit)` | 确认 PostToolUse、PreToolUse 事件在 worktree 内是否正常触发 hook |
| 1d | 检查 `.claude/hooks/` 在 worktree 内是否可见 | 若不可见 → 在 `settings.local.json` 中将 hook 路径改为绝对路径 |
| 1e | `ExitWorktree` 清理测试 worktree | 确认无残留 |

**判定：** 若 1b/1c 任一步骤中 hook 不触发 → 在 settings 中使用绝对路径 `C:/Users/.../.../.claude/hooks/` 指向主仓库 hooks 目录。若 1c 中 git commit 在 worktree 内不触发 PreToolUse → 此为 Claude Code 已知限制，需在 H3/H5/H7 描述中追加"仅主仓库有效"注解，并接受 worktree 内 commit 不受 hook 约束的风险（worktree 的隔离性本身就是安全边界——合并回主分支时 H7/H9 二次检查）。

| # | Hook | 事件 | 逻辑 | exit 2 条件 |
|---|------|------|------|-------------|
| H1 | `inject_state.py` | SessionStart | 输出最近 10 条 git log + 本周聚焦摘要 + P0 列表 + Deep Evaluator 最新报告。同时搜索 `.claude/worktrees/*-checkpoint.json` 和 `.claude/checkpoint.json` → 存在则注入"上次未完成任务"摘要。**优雅降级**：若 `04-收件箱/eval-*.md` 不存在（E1 尚未部署或尚无产出）→ 静默跳过，不报错、不输出"找不到报告"。同理，checkpoint 不存在时静默跳过 | 永不（纯注入） |
| H2 | `safety_gate.py` | PreToolUse(Bash) | 拦截 `rm -rf /`、`git push --force main`、生产环境操作。**紧急旁路**：检测项目根目录 `HARNESS_BYPASS` 文件 → 存在则 H7/H9 降级为 warn-only（exit 0 + stderr），H2 自身仍拦截危险操作。C4 检测到旁路文件超过 30 分钟自动删除。H1 注入时高亮提醒"⚠️ 当前处于旁路模式" | 匹配危险模式 |
| H3 | `check_commit_msg.py` | PreToolUse(Bash(git commit:*)) | 校验 commit message 是否符合 Conventional Commits | 不匹配 `feat\|fix\|refactor\|...` |
| H4 | `log_change.py` | PostToolUse(Write\|Edit) | 修改 gacha_simulator/ 或 docs/ 下文件 → 追加 `{时间} \| {操作} \| {文件路径}` 到对应模块 05-笔记（纯事实记录，不生成摘要——语义摘要由 C3 周报时从 git log 提取） | 永不（纯记录） |
| H5 | `sync_version.py` | PreToolUse(Bash(git commit:*)) | 自适应检测 CLAUDE.md 格式——若 CLAUDE.md 含硬编码版本号（如 `v1.10.0`），检查 `_version.py` vs `CLAUDE.md` vs `技术栈.md` 三者一致性；若 CLAUDE.md 不含硬编码版本号（阶段 7 后格式），改为检查 `_version.py` vs `技术栈.md` 一致，并验证 CLAUDE.md 含版本号引用格式（`见 _version.py`）。**无需阶段标记**——hook 通过 grep 版本号模式自动判断当前格式 | 不一致 / 引用格式缺失 |
| H6 | `check_doc_rot.py` | Stop | 扫描所有模块的 05-笔记最后更新日期 → 超过 7 天标记 | 永不（只输出提醒到 stderr；Stop hook 不能 block 会话结束） |
| H7 | `fast_gate.py` | PreToolUse(Bash(git commit:*)) | 提交前跑 `ruff check` + 检查变更文件是否在 gacha_simulator/ 目录内 | ruff 报错 / 文件在限制目录外 |
| H9 | `push_gate.py` | PreToolUse(Bash(git push:*)) | push 前跑 `pytest -q`（不含覆盖率，只跑失败用例） | pytest 失败 → exit 2 |
| H8 | `save_context.py` | PreCompact | 保存当前任务状态、关键决策、进行中计划。**路径自适应**：若当前在 worktree 内 → 写入主仓库 `.claude/worktrees/{task-name}-checkpoint.json`（worktree 可能被 force-remove，不能存内部）；若在主仓库 → 写入 `.claude/checkpoint.json`。H8 通过检测 `git worktree list` 判断当前位置 | 永不（纯保存） |

**设计原则（来自 Anthropic）：**
- Hooks **不做代码审查**——那是 Deep Evaluator 的事。Hook 做审查会在每次 Stop 阻塞 30 秒+，破坏写代码节奏
- Hooks **不在同一上下文做自我评价**——LLM 对自己的输出评价有正向偏差，审查必须由独立 Agent 执行
- H8 是长时运行的**上下文管理基础设施**——PreCompact 保存关键状态，恢复时 inject_state 读取
- **Cron 会话同样受 hooks 约束**——CronCreate 触发的 Claude Code 会话与用户会话共享 hook 配置；C1-C4 的 `git commit` 必经 H7（ruff check），C5/E1 只读无 commit 需求
- **Fast Gate 只跑 ruff**——pytest（分钟级）在 push gate (H9) 异步检查，不在 commit 路径阻塞。amend/merge commit 仍触发 H7，但 ruff 毫秒级不构成干扰

**脚本位置：** `.claude/hooks/*.py`（9 个文件，每个 ~40-80 行）

**H4 实现说明：** 映射表**不硬编码在 hook 脚本中**。改为独立配置文件 `.claude/file_map.json`，H4 读取该文件。映射规则：(1) `gui/{panel}_panel.py` → `panels/{面板名}/`；(2) `core/` 下文件按子系统名映射到 `subsystems/{子系统}/`；(3) `service/` → `subsystems/模拟服务层/`；(4) 未匹配文件写全局 `docs/01-活跃/05-笔记.md`。

**`file_map.json` 引导期（C2 Phase 2 之前 ~2 周）：** 阶段 1 实施时手动创建初始 `file_map.json`，覆盖当前 18 模块的代码→文档映射。引导期内若新增/删除面板或子系统文件，需手动更新映射。引导期结束后（C2 升级至 Phase 2），映射由 C2 从模块状态矩阵自动生成，不再需要手动维护。引导期手动映射的完整性由 C2 Phase 1 的矩阵偏差报告间接检查——若映射缺失，H4 的 `log_change.py` 会将变更写入全局 `05-笔记.md`（catch-all 行为），C2 下次扫描时会报告"已记录变更但无对应模块映射"。

**`file_map.json` 维护责任（C2 Phase 2 起）：** C2 `matrix-syncer` 升级到 Phase 2 后，在每次同步模块状态矩阵时自动更新 `file_map.json`——从矩阵的"面板概览"和"子系统概览"两表自动生成映射。这样面板增删改时只需更新矩阵，映射自动同步。格式示例：
```json
{
  "gacha_simulator/gui/analysis_panel.py": "docs/01-活跃/panels/统计分析/05-笔记.md",
  "gacha_simulator/core/strategy.py": "docs/01-活跃/subsystems/策略系统/05-笔记.md",
  "gacha_simulator/service/batch_simulator.py": "docs/01-活跃/subsystems/模拟服务层/05-笔记.md"
}
```

### 阶段 2：Cron 自治层（6 个定时 Agent）

**目标：** 周期性维护任务全自动化，agent 有写入权。

**Cron 会话的反馈闭环（关键——无此则 cron 错误累加）：**
- Cron agent 同样是 Claude Code 会话 → H1 `inject_state.py` 在 SessionStart 自动注入最新 E1 审查报告 + 本周聚焦 + P0 列表
- **每个 cron agent 的 prompt 首条指令：** "先检查 `04-收件箱/` 中是否有针对你上次产出的审查报告（按 agent 名搜索）。如有 FAIL/WARN，优先处理后再执行常规任务。"
- 对 C1-C4 有写入权的 agent，此指令是强制性的——不允许在 eval 报告中有未处理的 FAIL 时继续产出

| # | 名称 | 频率 | 权限 | 任务描述 |
|---|------|------|------|---------|
| C1 | `doc-syncer` | 每天 5:07 | Write(docs/) + Bash(git) | 读取 `_version.py` + `main.py` Tab 列表 → 对比 CLAUDE.md + 技术栈.md → 不一致则直接修复 → `git commit -m "docs: [auto] CLAUDE.md/技术栈版本同步"` |
| C2 | `matrix-syncer` | 每天 5:37 | **Phase 1：Read only**（首 ≥2 周）；Phase 2：Write(docs/) + Bash(git) | Phase 1（只报告）：扫描 docs/01-活跃/ 全部 P 编号计划文件 → 对比模块状态矩阵 → 不一致写入 `04-收件箱/matrix-drift-{date}.md`。Phase 2（升级门控满足后）：直接修复 + commit `[auto]` |
| C3 | `weekly-writer` | 每天 9:07 | Write(docs/) + Bash(git) | **每日运行，仅周一产出**（prompt 首行："若今天不是周一，立即退出，不做任何操作"——规避 CronCreate 7 天自动过期）。（周一执行时）：(1) 扫描上周 git log → 汇总完成/进行中/新增计划 → 写入 `00-本周聚焦.md` → 标记过期冻结项。(2) **计划完成检测**：扫描全部 P 编号计划文件，若最近 2 周无关联 commit 且对应 `理论.md` 无 P0/P1 条目 → 标记为"建议归档"→ 写入本周聚焦的 `## 待确认归档` 区。(3) 完成以上后 commit `[auto]` |
| C4 | `stale-detector` | 每天 6:07 | Write(docs/) | 扫描全部 05-笔记 + 04-问题 + 计划文件 → 标记超过 7 天无活动的模块 → 写入 `04-收件箱/stale-{date}.md`（只报告不修复） |
| C5 | `quality-reviewer` | 每天 10:07 | Read only | **每日运行，仅周一产出**（prompt 首行："若今天不是周一，立即退出，不做任何操作"——规避 CronCreate 7 天自动过期）。（周一执行时）：读取最近一周新增/修改的 `gacha_simulator/` 代码 → 审查 ruff 做不了的语义级问题：(1)重复代码模式（语义重复，非字面重复） (2)架构分层违反（core → gui 反向引用） (3)过度耦合（单文件 >800 行） (4)缺失的边界检查 → 输出 `04-收件箱/quality-{date}.md`。注：函数长度/嵌套深度等确定性规则在 ruff 配置（H7 毫秒级检查），C5 不重复 |
| C6 | `heartbeat-monitor` | 每天 8:07 | Read only | 扫描 `.claude/heartbeats/` 下各 cron agent 心跳文件 → 超过预期频率 2 倍未更新则写入 `04-收件箱/heartbeat-alert-{date}.md`。H1 注入最新心跳警报。C4 运行时清理超过 14 天的心跳文件 |

**C2 升级门控（Phase 1 → Phase 2）**：C2 **不能自行决定升级**——必须满足全部三个条件后由人工触发：

| 条件 | 验证方式 |
|------|---------|
| ① 连续 ≥4 份矩阵偏差报告经人工确认无误 | 人工在 `04-收件箱/matrix-drift-*.md` 末尾追加 `✅ CONFIRMED` 行 |
| ② E1 连续 2 周未对 C2 产出标记 FAIL | E1 报告自动判断（grep `C2.*FAIL`） |
| ③ 人工明确发出升级指令 | 在 `04-收件箱/` 放入 `UPGRADE-C2` 文件（内容可为空），C2 检测到后升级 |

升级后若 E1 连续 3 次报告 C2 产出 FAIL → 自动降级回 Phase 1（只读），并向 `04-收件箱/` 写入 `DOWNGRADE-C2-{date}.md` 说明降级原因。

**Cron agent 心跳规范**：

每个 cron agent 在每次运行结束时 touch `.claude/heartbeats/{agent-name}.txt`。
C6 检测规则：C1/C2/C3/C4/C5（每天运行）→ 超过 48h 未更新 = 警报；E1（每 6h）→ 超过 18h 未更新 = 警报。注：C3/C5 在非周一仅做心跳 touch 不产出，因此心跳仍每日更新——C6 按每日频率判断。
这解决了"cron 静默失败无产出则无人知晓"的盲区。

### 阶段 3：Fast Gate + Deep Evaluator 双层审查

**设计依据（Anthropic 实际做法）：** Evaluator 必须是**结构上独立、权限上隔离的 Agent**。Hooks 不做审查——审查需要独立上下文窗口（避免正向偏差）和深度分析（避免 token 竞争）。

#### 3a. Fast Gate（Hook，确定性检查）

| # | 实现 | 触发 | 逻辑 |
|---|------|------|------|
| FG | `fast_gate.py` (H7) | PreToolUse(git commit) | `ruff check` + 目录限制检查 → exit 2 硬阻止 |
| PG | `push_gate.py` (H9) | PreToolUse(git push) | `pytest -q`（不含覆盖率，只跑失败用例）→ exit 2 硬阻止 |

**设计理由：** pytest 是分钟级操作，不能放在 commit 路径（破坏写代码节奏）。commit gate 只做毫秒级检查（ruff），test suite 在 push 时异步执行。这与 Anthropic 的"Fast Gate = 秒级"原则一致。

特点：commit gate 毫秒级完成；push gate 分钟级但只在 push 时触发。两者都是确定性规则，不涉及代码意图理解。

#### 3b. Deep Evaluator（独立 Cron Agent，只读）

| # | 名称 | 频率 | 权限 | 任务描述 |
|---|------|------|------|---------|
| E1 | `deep-evaluator` | 每 6h | **Read only** | 读取最近间隔内的 commit diff → 独立上下文审查：(1)代码变更是否匹配关联计划 (2)架构分层是否违反 (3)副作用评估 (4)测试覆盖充分性 (5)文档是否同步 → 输出 `04-收件箱/eval-{timestamp}.md` |

**为什么每 6h 而不是每天：**
- 每天一次意味着上午的代码要等到次日才被审查——上下文遗忘
- 每 6h 保证任何时段提交的代码当天就能收到审查报告
- Token 成本可控：每次只审查增量 diff，不是全量代码

**关键约束：**
- Evaluator **永远不能有 Write/Edit/Bash(git commit)** 权限。只读+报告
- **独立上下文窗口**——不共享 Generator 的上下文，避免 LLM 自我评价的正向偏差
- 修复动作由 Generator（下次会话的 Claude Code）在 SessionStart 读到最新报告后自行决定
- H1 `inject_state.py` 在 SessionStart 时自动注入最新 eval 报告摘要

**E1 Default-FAIL 判定表**（形式化合约——不再模糊"批判性审查"，每个维度有明确 FAIL 条件）：

| 维度 | 检查方法 | FAIL 条件 |
|------|---------|-----------|
| **架构分层** | grep `from gacha_simulator.gui` 在 core/ 目录 | 发现反向引用 → FAIL |
| **架构分层** | grep `from gacha_simulator.core` 在 gui/ 非面板文件 | 面板外引用 → WARN |
| **PR 边界** | git diff 检查变更文件列表 | 文件在 tests/ / pyproject.toml / README.md 中 → FAIL |
| **测试覆盖** | 新增函数/类 vs tests/ 中对应新增的 test | 新增公共接口无测试 → WARN |
| **文档同步** | 变更涉及 core/ API → 检查对应 `模块.md` 是否更新 | API 变更但实施文档未更新 → WARN |
| **副作用** | git diff 分析变更行是否触及其他面板的调用路径 | 可能影响其他面板但未在 commit message 声明 → WARN |
| **计划一致性** | 变更文件路径 vs 模块状态矩阵中标记为 `in_progress` 的模块 | 变更了非当前活跃模块且无解释 → INFO（不判定失败，仅供参考） |

判定规则：任一 FAIL → 报告标题标记 `⚠️ FAIL`。仅 WARN → 报告标题标记 `ℹ️ REVIEW`。全通过 → `✅ CLEAN`。

**E1 升级标记**（反馈闭环的关键——E1 不止审查 Generator，也审查 Cron 的产出，且能将设计级问题升级到 Planner）：

| 检测条件 | 升级标记 | 含义 |
|----------|---------|------|
| 同一文件（非 `04-收件箱/`）连续 3 次 eval 出现 FAIL | `🔴 ESCALATE: 需 Planner 重规划` | 不是代码修修补补能解决的——设计有根本问题 |
| 检测到 `[auto]` commit 被后续 commit 显式 revert | `🟡 ESCALATE: cron agent {name} 产出被回滚` | 该 cron agent 持续产出错误内容，需调整其 prompt 或降级为只读 |
| 连续 2 次 eval 均无 FAIL 且无新增 WARN | `🟢 DE-ESCALATE: 可考虑减少审查频率或放宽约束` | 信号：当前约束可能过紧 |

升级标记出现在报告标题中 → H1 注入时高亮 → Generator 读到 `ESCALATE` 时应触发 Planner（`/plan` skill）而非自行修复。这是 E1→Planner 的唯一信号路径。

### 阶段 4：长时运行支持（Session/Harness/Sandbox 解耦）

**目标：** 让 Agent 能长时间自主运行——崩溃了能恢复、上下文不会爆、不会无限循环。

**设计依据（Anthropic Managed Agents 核心架构）：**

```
┌────────────────────────────────────────────┐
│ Session (事件日志, 独立存活)                │
│  → git history + --session-id 断点续传      │
│  → 05-笔记 按时间线记录每次操作             │
│  → 即使 Harness 崩溃，日志完整保留          │
├────────────────────────────────────────────┤
│ Harness (控制循环, 无状态)                  │
│  → Hooks 捕获错误 → exit 2 → Claude 重试   │
│  → CronCreate 定时唤醒 + 检查状态           │
│  → PreCompact 保存关键状态后再压缩上下文    │
│  → Cron 检测到崩溃 → 从 checkpoint.json (主仓库) 恢复 │
├────────────────────────────────────────────┤
│ Sandbox (隔离执行, 崩溃不影响上层)          │
│  → Worktree 隔离（已有 using-git-worktrees）│
│  → max_turns 熔断保护                        │
│  → 超时保护（CronCreate timeout）            │
│  → 崩溃后 Harness 从 Session 日志恢复重试    │
└────────────────────────────────────────────┘
```

#### 4a. 断点续传

| 机制 | 实现 |
|------|------|
| 会话标记 | 长时任务启动时 `--session-id <task-name>`，崩溃后同一 session-id 重连 |
| 状态保存 | H8 `save_context.py` 在 PreCompact 时保存当前任务进度、已完成的步骤、关键决策 → 主仓库 `.claude/worktrees/{task-name}-checkpoint.json`（worktree 内运行）或 `.claude/checkpoint.json`（主仓库运行）。**永远不存入 worktree 内部路径** |
| 状态恢复 | H1 `inject_state.py` 在 SessionStart 时搜索 `.claude/worktrees/*-checkpoint.json` + `.claude/checkpoint.json` → 存在则注入"上次未完成的任务：{描述}，当前进度：{步骤}，请继续" |
| Git 屏障 | 每完成一个逻辑步骤 commit 一次 `[auto] checkpoint: {步骤}`，崩溃后 git log 能看到最后完成的位置 |

#### 4b. 上下文窗口管理

| 机制 | 实现 |
|------|------|
| PreCompact 保存 | H8 在压缩前提取：当前任务描述、已完成的步骤、关键的架构决策、待修复的 bug → 写入主仓库 JSON（路径同上：worktree 感知） |
| SessionStart 恢复 | H1 注入压缩后的摘要 → 3-5 行精炼状态，而非原始上下文 |
| 分段执行 | 长任务拆为多个 Cron 触发——每段做完 commit + 写状态，下段从状态恢复 |

#### 4c. 熔断保护

| 机制 | 实现 | 默认值 |
|------|------|--------|
| `max_turns` | Cron agent 的单次执行最大轮数 | 50 |
| 超时 | CronCreate 的 timeout 参数 | 30 min |
| 循环次数 | 自愈循环（test → fix → retest）上限 | 3 轮 |
| 冻结文件 | H2 `safety_gate.py` 检测项目根目录 `AGENT_FREEZE` 文件 → exit 2 阻止所有操作 | 紧急冻结 |

#### 4d. Worktree 生命周期

| 阶段 | 操作 |
|------|------|
| 创建 | 长时任务启动时 `git worktree add ../task-{name} -b feat/{name}`。同时在主仓库创建 `.claude/worktrees/{name}-checkpoint.json` 空文件 |
| 执行 | Agent 在 worktree 内操作，不影响主分支。H8 每次 PreCompact 时将 checkpoint 写入主仓库路径（非 worktree 内） |
| 合并 | 任务完成 → `git merge feat/{name}` → `git worktree remove ../task-{name}` → 删除 `.claude/worktrees/{name}-checkpoint.json` |
| 回收 | C4 `stale-detector` 检测超过 3 天未活跃的 worktree → 写入报告提醒清理。同时报告孤儿 checkpoint（worktree 已删但 checkpoint 残留） |
| 失败回滚 | 任务失败 → 保留 checkpoint.json（已在主仓库）→ `git worktree remove --force` 丢弃 worktree → 下次 SessionStart 时 H1 注入 checkpoint 提示"上次任务 {name} 失败，进度已保留" |
| 孤儿恢复 | 检测到 `.claude/worktrees/{name}-checkpoint.json` 存在但对应 worktree 不存在 → H1 注入"发现未完成的任务 {name}，checkpoint 存在但 worktree 已清理。使用 `--session-id {name}` 从 checkpoint 恢复" |

#### 4e. 已知限制（设计边界，非缺陷）

以下限制是**有意为之**——完全自动化代码生成在人不在场时风险不可接受。这些是设计边界而非待修缺陷。

| 限制 | 说明 | 设计理由 |
|------|------|---------|
| **无自动任务启动** | 没有 cron/skill 自动触发 `EnterWorktree` + `--session-id` 开始长任务。任务启动必须由人发出指令 | 人确认"这个计划可以开始实施了"是必要的安全边界——AI 不应自行决定开始修改代码 |
| **崩溃后需人重连** | `--session-id` 重连是手动操作。C6 检测 cron 静默但不自动重启 user task | Claude Code 当前不支持 cron-triggered session resumption；且自动重连可能掩盖系统性崩溃原因 |
| **worktree 与 hooks 交互未穷举验证** | `EnterWorktree` 后 `.claude/hooks/` 是否跟随、PreToolUse 事件在 worktree 内是否正常触发——需在阶段 1/4 实施时实测 | 取决于 Claude Code 的 worktree 实现细节，非计划层面可预判。若 hooks 不跟随 → 在 settings 中配置绝对路径 |
| **并行 worktree 无锁协调** | 两个 worktree 同时修改同一文件会产生合并冲突，无预检机制 | 当前项目为单人开发，并发冲突概率极低。若未来需要 → C4 扩展为"检测并行 worktree 修改重叠文件 → 警报" |
| **长任务无独立心跳** | C6 监控 cron agent 但不监控 user task（user task 的心跳即 git commit 本身） | user task 由人主动启动和监控，与无人值守的 cron 不同。若 user task 长时间无 commit → H6 Stop 提醒 + C4 过期检测足以覆盖 |

---

### 阶段 5：Planner Skill（1 个自定义 Skill）

**目标：** AI 主导的计划生成——用户给种子方向，agent 细化为可执行计划。

```
用户: /plan 给所有面板加导出CSV功能
           ↓
Planner Agent:
  1. 搜索影响面（哪些面板、哪些文件）
  2. 评估复杂度 → 决定是单一P编号还是需要拆分
  3. 写入计划文件 docs/01-活跃/panels/{模块}/P{n} {名称}.md
  4. 注册到 模块状态矩阵
  5. 输出: "已创建 P40 CSV导出功能计划（{路径}），涉及4个面板，预估3个阶段"
```

**实现：** 创建 `.claude/skills/plan/SKILL.md`，复用 `superpowers:brainstorming` + `superpowers:writing-plans` 的组合模式，但追加项目特有的计划文件模板和矩阵注册步骤。

### 阶段 6：文档精简

**目标：** 把 210 个文件减到 agent 和人都能可持续维护的量，同时新增 agent 可解析的结构化元素。

#### 6a. 文件合并

| 操作 | 从 | 到 | 理由 |
|------|----|----|------|
| 删除 | `04-收件箱/` (空目录) | 改为 agent 写入目标（见 6b） | 从未被人使用，但 agent 需要（C2/C4/C5/E1 的输出目录） |
| 删除 | 全部 `03-审计.md` (20个) | 替代机制：(1)E1 每 6h 产出审查 → `04-收件箱/eval-*.md`；(2)C5 每周产出质量审查 → `04-收件箱/quality-*.md`；(3)人审查时在 PR/commit message 中写 `Audit: {注记}` | "审计后修改"从未发生；agent 持续审查 + 人即时注记替代 |
| 删除 | `验收清单.md` (302行，63未勾选) | `pytest --cov` 覆盖率报告 | 手动验收清单无法维护 |
| 合并 | `00-档案.md` + `02-实施.md` | `模块.md` | 设计意图+代码位置→同一文件，Claude Code 读一个文件即了解模块全貌 |
| 合并 | `01-理论.md` + `04-问题.md` | `理论.md` | 假设/局限+已知缺陷→同一文件 |
| 保留 | `05-笔记.md` | agent 自动维护（H4 记录事实 + C3 周报补充语义） | 人不再手动写 |
| 精简 | `全局约定.md` | 砍掉已被 harness 强制执行的条目（PR 边界、commit 格式、版本号位置），保留仍为约定的条目（策略命名、GDR 调用规范） | 约定文件的唯一价值是"机器判不了但人需要知道的事" |

**结果：** 18 模块 × 3 文件 = 54 文件（减半），每个文件有明确的写入责任方。

#### 6b. Agent 元数据头规范（新增——harness 阶段必需）

C2（矩阵同步）需要从计划文件中提取 P 编号、归属模块、状态——不能依赖 LLM 语义理解，必须是 grep 能精确命中的结构化格式。

**所有计划文件（`P{n} *.md`）首行强制包含元数据头：**

```markdown
<!-- META: P{n} | module:{模块文件夹名} | status:{designing|in_progress|completed|shelved} | last:YYYY-MM-DD -->
```

示例：
```markdown
<!-- META: P39 | module:00-meta | status:designing | last:2026-06-11 -->
```

**约束：**
- C2 用 `grep -r '^<!-- META:' docs/` 精确提取所有 P 编号元数据，不依赖 LLM 理解
- H5 检查 `last` 日期——超过 30 天且 status≠completed → 提醒
- Planner skill 创建计划文件时自动写入正确的 META 行

#### 6c. 04-收件箱/ 生命周期规范（新增）

收件箱是 agent 间唯一的异步通信渠道——Cron 产出、E1 审查、Cron 自我修正全走这里。必须有明确的写入规范和自动清理策略。

| 规范项 | 内容 |
|--------|------|
| **目录** | `docs/01-活跃/04-收件箱/`（模块级问题/待办在对应模块的 `理论.md` 中维护，不单独设收件箱文件） |
| **命名** | `{agent}-{YYYY-MM-DD}.md`——C2→`matrix-drift-*.md`、C4→`stale-*.md`、C5→`quality-*.md`、E1→`eval-{YYYY-MM-DD}-{HHMM}.md`（含日期+时间以便排序） |
| **最大存活** | 14 天。C4 每次运行时删除超过 14 天的报告（不归档——收件箱是 transient channel，不是永久记录） |
| **读取者** | H1 注入最新 3 份 eval 报告摘要 + 最新 1 份其他报告；Cron agent 启动时 grep 自己名字在收件箱中检索针对自己的报告 |
| **写入者** | C2(Phase 1)、C4、C5、E1。C1/C3 写 docs/ 其他位置不走收件箱 |

#### 6d. 全局约定.md 精简（新增）

当前 `全局约定.md` 包含大量已被 harness 强制执行的规则。精简为两段：

1. **"已被 harness 强制执行"**（只列清单，不重复规则——规则在 hook 脚本中）：
   - H2: 危险命令拦截
   - H3: Conventional Commits
   - H5: 版本号一致性
   - H7: ruff check + 目录边界
   - H9: pytest

2. **"仍需人遵守的约定"**（机器判不了的）：
   - Pride Versioning 语义（何时 bump MAJOR/MINOR/PATCH）
   - 策略命名规范
   - GDR 调用规范（禁止绕过 `make_gdr_calculator`）
   - 计划文件增量修改、不整段删除

#### 6e. 合并执行策略（新增——18 模块的批量合并操作规范化）

当前 18 模块 × 6 文件 = 108 文件的合并重组，手工操作容易出错。采用 **agent pipeline 批量执行**：

```
pipeline(
  18 个模块目录,
  stage1: 读取 00-档案.md + 02-实施.md → 合并写入 模块.md（档案内容在前，实施内容在后，章节间用 --- 分隔）
  stage2: 读取 01-理论.md + 04-问题.md → 合并写入 理论.md（理论内容在前，问题内容在后）
  stage3: 验证——grep 检查 模块.md 中不包含 "02-实施.md" 引用（自引用断链）
)

以上 pipeline 完成后，批量删除旧文件：
  find docs/01-活跃 -name "00-档案.md" -delete
  find docs/01-活跃 -name "02-实施.md" -delete
  find docs/01-活跃 -name "01-理论.md" -delete
  find docs/01-活跃 -name "04-问题.md" -delete
```

**合并约束：**
- 合并时不创造新内容，只做拼接+格式统一（标题层级调整）
- 若两个源文件存在同名章节 → stage1/stage2 agent 追加 `[合并]` 标记，由人在合并后审查
- 合并完成后运行 `grep -rn "00-档案\|02-实施\|01-理论\|04-问题" docs/01-活跃/` 确认零引用（除 `模块.md` 和 `理论.md` 自身的说明性文本外）

#### 6f. 阶段 6→7 过渡验证（防止 CLAUDE.md 引用已删除文件）

阶段 6 删除/合并大量文件后，阶段 7 重写 CLAUDE.md 前需运行验证：

```bash
# 检查 CLAUDE.md 是否引用已删除的文件
grep -rn "03-审计\|验收清单\|六文件\|00-档案\|02-实施\|04-问题" CLAUDE.md
# 如有命中 → 先更新引用再执行阶段 7 重写

# 检查 CLAUDE.md 是否引用旧文件名（已被合并）
grep -rn "00-档案\|02-实施" CLAUDE.md
# 如有命中 → 替换为"模块.md"引用
```

此验证步骤确保阶段 7 不会基于已过时的文件引用进行重写。

### 阶段 7：CLAUDE.md 重写

**目标：** 重构为三层结构——砍掉已被 harness 接管和 cron 维护的内容，保留 AI 真正需要在上下文中知道的信息，新增 harness 使用指南。

#### 7a. 当前问题

当前 CLAUDE.md (207 行) 存在三类问题：

| 问题 | 示例 | 占比 |
|------|------|------|
| **死亡内容**（已被 harness/cron 接管的维护指令） | "每次会话结束写 05-笔记"→ H4 自动做；"每周清理更新本周聚焦"→ C3 自动做；六文件体系→已改为三文件；审计后修改→已删除 | ~35% |
| **冗余内容**（在 docs/ 中有权威源的信息） | 已知问题 ×3（在各模块 `理论.md` 中重复维护）；未完成计划（指向矩阵）；版本号（硬编码 v1.10.0） | ~15% |
| **完全缺失** | Harness 架构说明、如何与 hooks/cron/evaluator 交互、Planner skill 调用方法 | ~20% |

净效果：207 行中 ~50% 无用或重复，而 harness 生态完全未被记录。

#### 7b. 新三层结构

```
CLAUDE.md (~120 行)
│
├── 第一层：项目事实（~40 行）
│   ├── 技术栈（Python/PyQt6/Plotly/pytest——稳定信息）
│   ├── 架构分层 + 数据流（从当前版精确保留）
│   ├── 版本号引用：「版本号见 _version.py，技术栈版本号由 C1 cron 自动同步至此文件」
│   └── Tab 列表引用：「当前 Tab 列表见 main.py，由 C1 cron 自动同步」
│
├── 第二层：架构约束（~50 行）
│   ├── 策略系统接口（select_action(ctx) 签名）
│   ├── GDR 调用规范（禁止绕过 make_gdr_calculator，权重从 ConfigStore 自动提取）
│   ├── 并行模拟架构（_wk_init + Pool 模式）
│   ├── 配置文件格式（从当前版精确保留）
│   └── 扩展指南（添加新 GDR/策略/停止条件/面板——从当前版精确保留）
│
└── 第三层：Harness 使用指南（~30 行）【全新】
    ├── Hooks（9 个）：列表 + 触发时机 + 被阻止时该如何修正
    ├── Cron agents（6 个）：每个职责一句话 + 产出位置
    ├── Deep Evaluator：报告在 04-收件箱/eval-*.md，SessionStart 自动注入
    ├── Planner：/plan <种子> → AI 细化 + 写计划文件 + 注册矩阵
    └── 故障排查：commit 被 H7 阻止 → 跑 ruff check；push 被 H9 阻止 → 跑 pytest
```

#### 7c. 删除清单

| 删除内容 | 当前行数 | 替代 |
|----------|---------|------|
| "每次会话结束更新 05-笔记" | 177 | H4 自动记录事实 + C3 周报补充语义 |
| "每周清理时更新本周聚焦" | 180 | C3 自动写入 |
| "审计后修改"约定 | 158-164 | 审计文件已删除；E1 持续审查替代 |
| 六文件体系描述 | 160-163 | 改为三文件（模块.md + 理论.md + 05-笔记.md） |
| 已知问题 ×3 | 182-186 | 指向各模块 `理论.md`（原 04-问题.md 的内容） |
| 未完成计划 | 188-190 | 保留指向矩阵，但去掉"见各模块 04-问题.md" |
| 版本号硬编码 v1.10.0 | 7 | 改为「见 `_version.py`，C1 cron 自动同步」 |
| Tab 列表硬编码 | 132 | 改为「见 `main.py`，C1 cron 自动同步」 |
| 文档维护工作流整段 | 175-180 | 全部由 cron agent 接管 |

#### 7d. 重写后验证标准

- [ ] `grep "每次会话\|每周清理\|审计后修改\|六文件\|手动维护" CLAUDE.md` 零命中
- [ ] `grep "harness\|hook\|cron\|evaluator\|/plan" CLAUDE.md` 至少 10 行
- [ ] 版本号在 CLAUDE.md 中不以硬编码数字出现
- [ ] 新 CLAUDE.md 行数 ≤ 130 行（比当前 207 行减少 ~35%）

---

## 四、文件清单

### 新建文件

```
.claude/hooks/
├── inject_state.py          ~60行  SessionStart 上下文注入
├── safety_gate.py           ~40行  PreToolUse 危险操作拦截（含 HARNESS_BYPASS 紧急旁路）
├── check_commit_msg.py      ~50行  PreToolUse 提交信息校验
├── log_change.py            ~80行  PostToolUse 自动追加05-笔记（读 file_map.json）
├── sync_version.py          ~70行  PreToolUse(git commit) 版本号/Tab列表一致性（自适应新/旧 CLAUDE.md 格式）
├── check_doc_rot.py         ~50行  Stop 文档腐烂检测
├── fast_gate.py             ~50行  PreToolUse(git commit) ruff+目录限制
├── push_gate.py             ~40行  PreToolUse(git push) pytest
├── save_context.py          ~50行  PreCompact 保存会话状态
├── verify_stage1.py         ~40行  （可选）阶段 1 验收自动检查
├── verify_stage2.py         ~40行  （可选）阶段 2 验收自动检查
├── verify_stage3.py         ~30行  （可选）阶段 3 验收自动检查
├── verify_stage4.py         ~40行  （可选）阶段 4 验收自动检查
├── verify_stage5.py         ~30行  （可选）阶段 5 验收自动检查
├── verify_stage6.py         ~40行  （可选）阶段 6 验收自动检查
└── verify_stage7.py         ~40行  （可选）阶段 7 验收自动检查

.claude/skills/plan/
└── SKILL.md                 规划 skill 定义

.claude/checkpoint.json       主仓库会话的 Harness 恢复快照（H8/H1 维护，非 Session 日志）
.claude/worktrees/            worktree 会话的 checkpoint 存储目录（H8 写入 {name}-checkpoint.json，H1 搜索全部；任务完成后清理）
.claude/file_map.json         代码路径→文档路径映射（C2 从模块状态矩阵自动生成）
.claude/heartbeats/           cron agent 心跳目录（每个 agent 运行结束时 touch 时间戳文件）

docs/02-待办/
└── P39 Harness工程——Anthropic三层自治架构建造计划.md  ← 本文件
```

### 修改文件

```
.claude/settings.local.json  追加 hooks 段 + 7 个 CronCreate 注册（C1-C6 + E1）
CLAUDE.md                    重写（阶段7）
docs/00-meta/模块状态矩阵.md 注册 P39 + 更新 P38 状态
```

### 删除文件

```
docs/01-活跃/**/03-审计.md   ×18  全删
docs/00-meta/验收清单.md      ×1   全删
```

### 合并文件（18模块 × 2 → 18模块 × 1 + 保留）

```
每个模块下：
  00-档案.md + 02-实施.md → 模块.md  （新）
  01-理论.md + 04-问题.md → 理论.md  （新）
  05-笔记.md              → 保留（agent维护）
```

---

## 五、验收标准

### 阶段 1（Hook 强制层）

- [ ] `SessionStart` 注入 git log + P0 列表 + Deep Evaluator 最新报告
- [ ] `git commit` 时 ruff check 不过 → exit 2 阻止（毫秒级）
- [ ] `git commit` 时版本号不一致 → exit 2 阻止
- [ ] `git commit` 时 Conventional Commits 格式不匹配 → exit 2 阻止
- [ ] `git push` 时 pytest 不过 → exit 2 阻止（分钟级，只在 push 时异步）
- [ ] 修改 gacha_simulator/ 下文件后对应 05-笔记 自动追加
- [ ] Stop 时文档腐烂检测 >7天 → 提醒
- [ ] PreCompact 时状态保存到 checkpoint.json

### 阶段 2（Cron 自治层）

- [ ] C1 成功自动修复 CLAUDE.md/技术栈版本号并 commit `[auto]`
- [ ] C2 Phase 1 成功产出矩阵偏差报告（只读）；Phase 2 成功后自动修复并 commit `[auto]`
- [ ] C3 成功自动写入本周聚焦（含计划完成检测与归档建议）并 commit `[auto]`
- [ ] C4 成功检测过期条目并写入报告
- [ ] C5 成功产出代码质量报告
- [ ] Cron agent 启动时通过 H1 注入 eval 报告 → 优先处理针对自己上次产出的 FAIL/WARN 后再执行常规任务

### 阶段 3（双层审查）

- [ ] Fast Gate commit 前 ruff/目录检查 <1 秒（毫秒级）
- [ ] Deep Evaluator 每 6h 产出审查报告 `04-收件箱/eval-{timestamp}.md`
- [ ] SessionStart 自动注入最新 eval 报告
- [ ] Evaluator 无 Write/Edit 权限（验证：尝试写入时被拒绝）
- [ ] 连续 3 次 FAIL 触发 ESCALATE 标记 → H1 注入 → Generator 识别后触发 Planner
- [ ] `[auto]` commit 被 revert 触发 cron 降级标记

### 阶段 4（长时运行）

- [ ] `--session-id` 重连后能从断点继续
- [ ] PreCompact → SessionStart 恢复后任务上下文不丢失
- [ ] max_turns=50 触发熔断，不再继续
- [ ] Worktree 创建 → 执行(H8 checkpoint 外存) → 合并 → 回收(含 checkpoint 清理) 流程完整
- [ ] Worktree 失败回滚：checkpoint 保留在主仓库，worktree 已清理，H1 能检测孤儿 checkpoint 并提示恢复
- [ ] H8 在 worktree 内运行时 checkpoint 写入主仓库路径（验证：worktree force-remove 后 checkpoint 仍存在）
- [ ] AGENT_FREEZE 文件存在时所有操作被阻止

### 阶段 5（Planner）

- [ ] `/plan <种子>` 自动产出符合模板的计划文件
- [ ] 计划自动注册到模块状态矩阵

### 阶段 6（文档精简）

- [ ] docs/ 目录从 210 文件降至 ~60 文件
- [ ] 全部计划文件首行含 META 元数据头（`grep -r '^<!-- META:' docs/` 命中所有 P 编号计划）
- [ ] `04-收件箱/` 命名规范生效（全部 agent 产出符合 `{agent}-{date}.md` 格式）
- [ ] C4 成功自动清理超过 14 天的收件箱报告
- [ ] 18 模块合并执行完成——`模块.md` + `理论.md` + `05-笔记.md` 三文件制生效
- [ ] `grep -rn "00-档案\|02-实施\|01-理论\|04-问题" docs/01-活跃/` 零命中（旧文件名引用已清除）
- [ ] `全局约定.md` 精简为"harness 强制执行清单" + "仍需人遵守的约定"两段
- [ ] `验收清单.md` 已删除，pytest --cov 为唯一质量门禁

### 阶段 7（CLAUDE.md 重写）

- [ ] CLAUDE.md 行数 ≤ 130 行（比当前 207 行减少 ~35%）
- [ ] `grep "每次会话\|每周清理\|审计后修改\|六文件\|手动维护" CLAUDE.md` 零命中
- [ ] `grep "harness\|hook\|cron\|evaluator\|/plan" CLAUDE.md` ≥ 10 行
- [ ] 版本号、Tab 列表在 CLAUDE.md 中不以硬编码形式出现（指向 `_version.py` / `main.py`）
- [ ] 第三层（Harness 使用指南）包含 hooks 列表 + cron 职责一览 + E1 报告读取方式 + Planner 调用方法 + 故障排查

### 自动化验证脚本（建议）

每个阶段完成后运行对应验证脚本，自动检查可机器验证的验收标准项：

```
.claude/hooks/
├── verify_stage1.py   检查 hooks 段在 settings.local.json 中 + 9 个 hook 脚本存在且可 import + ruff check 通过
├── verify_stage2.py   检查 6 个 cron 注册 + 心跳文件存在 + 各 agent 产出格式正确
├── verify_stage3.py   检查 E1 cron 注册为只读 + 04-收件箱/ 中有 eval-*.md 产出
├── verify_stage4.py   检查 checkpoint.json 存在 + worktree 生命周期正确
├── verify_stage5.py   检查 /plan skill 文件存在 + 计划模板含 META 行
├── verify_stage6.py   检查 docs/ 文件数 ≤ 60 + 全部计划文件含 META 头 + 三文件制生效（旧文件名零引用）+ 全局约定.md 精简为两段
└── verify_stage7.py   检查 CLAUDE.md 行数 ≤ 130 + 硬编码版本号零命中 + harness 引用 ≥ 10 行
```

验证脚本是**可选**的——每个脚本 ~30-50 行，可在对应阶段实施完成后编写。不阻塞主实施流程。

### E1 收件箱命名空间预留（P38 兼容）

P38（计划审查工作流——对抗验证流水线）后续接入时，其产出写入 `04-收件箱/peer-review-{plan}-{date}.md`。与 E1 的 `eval-{date}-{time}.md` 共享收件箱但命名前缀不同——无需协调即可并行。C4 的 14 天自动清理对两者一视同仁。

---

## 六、风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| Cron agent 幻觉污染文档 | 中 | 所有 agent commit 带 `[auto]` 前缀，`git log --grep=[auto]` 一键审查；Deep Evaluator 独立检查 agent 产出 |
| Cron agent 静默失败（无产出） | 中 | C6 心跳监控——超过预期频率 2 倍未更新则写入收件箱警报；H1 注入最新警报 |
| Hook exit 2 过度阻止 | 低 | H2 紧急旁路（`HARNESS_BYPASS` 文件）→ H7/H9 降级为 warn-only，30 分钟后 C4 自动删除；H5 自适应检测 CLAUDE.md 格式；H6 永不 block（只提醒）；H7 ruff 可先配 `--exit-zero` 仅报告 |
| Deep Evaluator 独立上下文仍可能有偏差 | 低 | Evaluator 以批驳为默认立场（prompt 指令："假设这些变更都有问题，找出证据"） |
| 长时运行 session 泄漏 | 低 | C4 stale-detector 每 24h 扫描活跃 session/worktree，超 3 天未活跃报告 |
| 上下文压缩丢失关键信息 | 中 | PreCompact 保存时按优先级排序：当前任务 > 架构决策 > bug 修复 > 一般变更；SessionStart 恢复时只注入前 3 项 |
| 与 P38 冲突 | 低 | P39 先行修好管道，P38 后续接入；收件箱命名空间预留（`eval-*` vs `peer-review-*`），无需协调 |
| 文档精简丢失历史 | 低 | 删除前 git 保留历史；合并时原文件内容移至新文件的对应章节 |
| H4 映射表过时导致日志写入错误位置 | 低 | 映射表外置为 `file_map.json`，C2 从模块状态矩阵自动维护，面板增删改时自动同步 |
| CronCreate 7 天自动过期导致 C3/C5 停摆 | 中 | C3/C5 改为"每天运行 + 周一产出"，非周一立即退出（毫秒级，几乎零 token 消耗）。所有 cron agent 使用 `durable: true` 持久化到 `.claude/scheduled_tasks.json` |
| worktree 内 hooks 不触发导致绕过 enforcement | 中 | 阶段 1 第一步 smoke test 验证。若 hooks 不跟随 worktree → settings 中配置绝对路径。若 PreToolUse(Bash(git commit)) 在 worktree 内不触发 → 接受此限制（合并回主分支时 H7/H9 二次检查）。见 §四 4e 已知限制 |
| 阶段 6 批量合并在 18 模块中产生内容冲突 | 低 | 合并 pipeline 只拼接不创造新内容；冲突章节追加 `[合并]` 标记供人审查；合并后 grep 验证断链。见 §三 6e 合并执行策略 |

---

## 七、成本估算

以下基于 Claude Code 的中等规模会话估算（实际值因上下文长度、diff 大小有 ±30% 波动）：

### 7a. 各 Cron Agent 单次 token 估算

| Agent | 频率 | 单次 ~token | 月均 ~token | 备注 |
|-------|------|------------|-------------|------|
| C1 `doc-syncer` | 每天 | 3-5K | 120K | 读 3 个文件 + 对比 + 可能 commit |
| C2 `matrix-syncer` | 每天 | 8-12K | 300K | 扫描全部 P 编号 + 对比矩阵 |
| C3 `weekly-writer` | 每天* | 0.3K/15K | 70K | 非周一几乎零消耗（仅退出）；周一 15K |
| C4 `stale-detector` | 每天 | 3-5K | 120K | 扫描日期 + 写入报告 |
| C5 `quality-reviewer` | 每天* | 0.3K/20K | 85K | 非周一几乎零消耗；周一 20K |
| C6 `heartbeat-monitor` | 每天 | 2-3K | 75K | 扫描心跳文件 |
| E1 `deep-evaluator` | 每 6h | 10-18K | 800K | 取决于间隔内 commit 数量 |
| **合计** | — | — | **~1,570K/月** | 约 1.6M token/月 |

\* C3/C5 每日运行但仅周一产出。非周一消耗 ~300 token（仅判断星期几 + 退出）。

### 7b. 降频策略（成本敏感场景）

| 场景 | 调整 | 月均节省 |
|------|------|---------|
| 项目进入维护期（周 commit < 3） | E1 降为每天 2 次（12h 间隔） | ~400K |
| 单人开发、无持续活跃 | C4/C6 降为每 2 天 1 次 | ~100K |
| 文档已稳定、无新增计划 | C2 降为每 3 天 1 次 | ~200K |

降频通过修改 CronCreate 的 cron 表达式实现，无需改动 agent prompt。

### 7c. 一次性实施成本

| 项目 | 预估 token |
|------|-----------|
| 阶段 1：9 个 hook 脚本编写 | ~80K |
| 阶段 2：6 个 cron agent prompt 调试 | ~60K |
| 阶段 3：E1 prompt 调试（含判定表调优） | ~40K |
| 阶段 4：checkpoint + worktree 流程调试 | ~30K |
| 阶段 5：Planner skill 编写 | ~20K |
| 阶段 6：18 模块合并 pipeline 执行 | ~50K |
| 阶段 7：CLAUDE.md 重写 | ~15K |
| **合计** | **~295K**（一次性） |

---

## 八、settings.local.json 权限矩阵草案

以下为 `settings.local.json` 中每个 cron agent 所需的最小权限集。部署时按此矩阵配置，避免授予超出职责的权限。

```jsonc
// .claude/settings.local.json — cron agent 权限段
{
  "permissions": {
    "C1:doc-syncer": {
      "allow": [
        "Read(gacha_simulator/_version.py)",
        "Read(CLAUDE.md)",
        "Read(docs/**/技术栈.md)",
        "Edit(CLAUDE.md)",
        "Edit(docs/**/技术栈.md)",
        "Bash(git commit -m 'docs: [auto]*')"
      ]
    },
    "C2:matrix-syncer": {
      "Phase 1 (Read only)": {
        "allow": [
          "Read(docs/01-活跃/**)",
          "Read(docs/00-meta/模块状态矩阵.md)",
          "Grep(docs/01-活跃/)",
          "Write(docs/01-活跃/04-收件箱/matrix-drift-*.md)"
        ]
      },
      "Phase 2 (Write)": {
        "allow": [
          "Edit(docs/00-meta/模块状态矩阵.md)",
          "Write(.claude/file_map.json)",
          "Bash(git commit -m 'docs: [auto]*')"
        ]
      }
    },
    "C3:weekly-writer": {
      "allow": [
        "Read(docs/01-活跃/**)",
        "Read(docs/00-meta/模块状态矩阵.md)",
        "Write(docs/01-活跃/00-本周聚焦.md)",
        "Bash(git log --since=*)",
        "Bash(git commit -m 'docs: [auto]*')"
      ]
    },
    "C4:stale-detector": {
      "allow": [
        "Read(docs/01-活跃/**)",
        "Write(docs/01-活跃/04-收件箱/stale-*.md)",
        "Bash(find docs/01-活跃/04-收件箱/ -mtime +14 -delete)"
      ]
    },
    "C5:quality-reviewer": {
      "allow": [
        "Read(gacha_simulator/**/*.py)",
        "Write(docs/01-活跃/04-收件箱/quality-*.md)"
      ]
      // 注意：只读代码，只写报告。无 Edit/Bash 权限
    },
    "C6:heartbeat-monitor": {
      "allow": [
        "Read(.claude/heartbeats/)",
        "Write(docs/01-活跃/04-收件箱/heartbeat-alert-*.md)"
      ]
    },
    "E1:deep-evaluator": {
      "allow": [
        "Read(gacha_simulator/**/*.py)",
        "Read(docs/**/*.md)",
        "Bash(git log --since=*)",
        "Bash(git diff *)",
        "Write(docs/01-活跃/04-收件箱/eval-*.md)"
      ]
      // 注意：严禁 Edit/Bash(git commit)。只读+报告
    }
  }
}
```

**权限原则：**
- C1/C3 需要 Bash(git commit) —— 版本同步 / 本周聚焦写入
- C2 Phase 1 只写收件箱 / Phase 2 追加 Edit(矩阵) + Bash(git commit)
- C4 只写收件箱 + 清理过期文件
- C5/E1/C6 **只读 + 只写报告** —— 永远不能修改源码或 commit
- 所有 Write 目标限制在 `docs/01-活跃/04-收件箱/` 或指定的 docs/ 文件

---

## 九、参考

- Anthropic: [Claude Code Hooks](https://claude.com/blog/how-to-configure-hooks) + [Dynamic Workflows](https://claude.com/blog/a-harness-for-every-task) + [Managed Agents](https://www.anthropic.com/engineering)
- Anthropic 内部: Planner-Generator-Evaluator 3-agent harness + Sprint Contracts (27-criteria)
- Google ADK: Evaluator-Optimizer loop + static guard rails
- OpenAI Agents SDK: Sandbox + Manifest + snapshot recovery
- ECC: [Autonomous Agent Harness](https://github.com/affaan-m/ECC) — cron + memory + subagents blueprint
- `anthropics/cwc-long-running-agents`: Default-FAIL contract + fresh-context evaluator + agent-maintained handoff
