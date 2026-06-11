// P38 — 计划审查对抗验证流水线（全阶段：0 分类 → 1 扇出 → 2 对抗 → 3 门控 → 4 审计 → 汇总）
// 用法: /workflow plan-review "docs/01-活跃/panels/最差影响/P31 最差影响分析剩余缺陷改进计划.md"
// skip_stages 由分类器动态决定：simple 计划可能跳过阶段 1/4；greenfield 跳过阶段 4

export const meta = {
  name: 'plan-review',
  description: '五阶段对抗验证流水线——自动审查计划文件并直接修改',
  phases: [
    { title: 'Classify', detail: '阶段 0：分类器分析复杂度/变更性质/维度清单' },
    { title: 'Impact', detail: '阶段 1：扇出影响面——N agent 并行检查 N 维度' },
    { title: 'Find', detail: '阶段 2：发现者读计划+靶向代码，输出问题列表' },
    { title: 'Fix', detail: '阶段 2：修复者修改计划文件' },
    { title: 'Verify', detail: '阶段 2：验证者逐项 PASS/FAIL/PARTIAL' },
    { title: 'Gate', detail: '阶段 3：可行性门控——6 项深度检查' },
    { title: 'Audit', detail: '阶段 4：代码审计——逐条映射 + 全链条逻辑检查' },
    { title: 'Matrix Sync', detail: '阶段 5：矩阵同步——对比计划元数据 ↔ 模块状态矩阵' },
    { title: 'Summary', detail: '汇总输出——追加审查记录到计划文件' },
  ],
}

// ═══════════════════════════════════════════════════════════════
// Schema 定义
// ═══════════════════════════════════════════════════════════════

const CLASSIFY_SCHEMA = {
  type: "object",
  properties: {
    plan_identity: {
      type: "object",
      properties: {
        file: { type: "string" }, module: { type: "string" },
        p_number: { type: "string" }, priority: { type: "string" },
      },
      required: ["file", "module", "p_number"],
    },
    complexity: { type: "string", enum: ["simple", "medium", "complex"] },
    change_nature: { type: "string", enum: ["evolutionary", "breaking", "greenfield"] },
    dimensions: {
      type: "array",
      items: {
        type: "object",
        properties: {
          type: { type: "string", enum: ["subsystem", "panel", "dynamic"] },
          name: { type: "string" }, rationale: { type: "string" },
        },
        required: ["type", "name"],
      },
    },
    recommendation: {
      type: "object",
      properties: {
        enable_fan_out: { type: "boolean" },
        max_adversarial_rounds: { type: "number" },
        max_gate_retries: { type: "number" },
      },
      required: ["max_adversarial_rounds"],
    },
    defect_count: { type: "number" },
    excluded: {
      type: "array",
      items: {
        type: "object",
        properties: { name: { type: "string" }, rationale: { type: "string" } },
        required: ["name"],
      },
    },
    skip_stages: { type: "array", items: { type: "string" } },
  },
  required: ["plan_identity", "complexity", "recommendation"],
}

const IMPACT_SCHEMA = {
  type: "object",
  properties: {
    dimension: { type: "string" },
    findings: {
      type: "array",
      items: {
        type: "object",
        properties: {
          id: { type: "string" },
          severity: { type: "string", enum: ["高", "中", "低"] },
          blocking: { type: "boolean" },
          description: { type: "string" },
          affected_files: { type: "array", items: { type: "string" } },
          rationale: { type: "string" },
        },
        required: ["id", "severity", "description"],
      },
    },
    no_findings: { type: "boolean" },
  },
  required: ["dimension", "findings"],
}

const FINDER_SCHEMA = {
  type: "object",
  properties: {
    new_issues: {
      type: "array",
      items: {
        type: "object",
        properties: {
          id: { type: "string" },
          dimension: { type: "string" },
          severity: { type: "string", enum: ["阻塞", "高风险", "中风险", "低风险"] },
          blocking: { type: "boolean" },
          title: { type: "string" },
          description: { type: "string" },
          affected_files: { type: "array", items: { type: "string" } },
          relevant_code_snippet: { type: "string" },
          suggested_fix_direction: { type: "string" },
        },
        required: ["id", "dimension", "severity", "description"],
      },
    },
    no_new_issues: { type: "boolean" },
    summary: { type: "string" },
  },
  required: ["new_issues", "no_new_issues"],
}

const FIXER_SCHEMA = {
  type: "object",
  properties: {
    modified_sections: { type: "array", items: { type: "string" } },
    applied_labels: { type: "array", items: { type: "string" } },
    skipped_issues: {
      type: "array",
      items: {
        type: "object",
        properties: { issue_id: { type: "string" }, reason: { type: "string" } },
        required: ["issue_id", "reason"],
      },
    },
    conflicts: {
      type: "array",
      items: {
        type: "object",
        properties: { description: { type: "string" }, resolution: { type: "string" } },
      },
    },
    write_success: { type: "boolean" },
    summary: { type: "string" },
  },
  required: ["modified_sections", "applied_labels", "write_success"],
}

const VERIFIER_SCHEMA = {
  type: "object",
  properties: {
    verifications: {
      type: "array",
      items: {
        type: "object",
        properties: {
          issue_id: { type: "string" },
          verdict: { type: "string", enum: ["PASS", "FAIL", "PARTIAL"] },
          evidence: { type: "string" },
          unresolved_items: { type: "array", items: { type: "string" } },
          reason: { type: "string" },
        },
        required: ["issue_id", "verdict"],
      },
    },
    overall: { type: "string", enum: ["ALL_PASS", "HAS_FAIL", "HAS_PARTIAL"] },
    summary: { type: "string" },
  },
  required: ["verifications", "overall"],
}

const GATE_SCHEMA = {
  type: "object",
  properties: {
    checks: {
      type: "array",
      items: {
        type: "object",
        properties: {
          id: { type: "string" },
          verdict: { type: "string", enum: ["PASS", "NEEDS_SPLIT", "NEEDS_CLARIFY", "FAIL"] },
          detail: { type: "string" },
          split_suggestions: { type: "array", items: { type: "object" } },
          clarify_suggestions: { type: "array", items: { type: "object" } },
        },
        required: ["id", "verdict", "detail"],
      },
    },
    overall: { type: "string", enum: ["PASS", "NEEDS_FIX", "FAIL"] },
    failures_blocking: { type: "array", items: { type: "string" } },
    summary: { type: "string" },
  },
  required: ["checks", "overall"],
}

const AUDIT_MAP_SCHEMA = {
  type: "object",
  properties: {
    mappings: {
      type: "array",
      items: {
        type: "object",
        properties: {
          item_number: { type: "number" },
          plan_description: { type: "string" },
          code_location: { type: "string" },
          current_logic: { type: "string" },
          plan_requirement: { type: "string" },
          modification_approach: { type: "string" },
          upstream_downstream: { type: "string" },
          risk: { type: "string" },
        },
        required: ["item_number", "plan_description", "code_location"],
      },
    },
    conflicts: {
      type: "array",
      items: {
        type: "object",
        properties: {
          item_a: { type: "number" },
          item_b: { type: "number" },
          description: { type: "string" },
        },
      },
    },
    transitive_gaps: {
      type: "array",
      items: {
        type: "object",
        properties: {
          changed_item: { type: "number" },
          affected_caller: { type: "string" },
          gap: { type: "string" },
        },
      },
    },
    summary: { type: "string" },
  },
  required: ["mappings"],
}

const AUDIT_EXECUTION_SCHEMA = {
  type: "object",
  properties: {
    execution_path: {
      type: "array",
      items: {
        type: "object",
        properties: {
          step: { type: "string" },
          check_point: { type: "string" },
          type_break: { type: "boolean" },
          null_break: { type: "boolean" },
          permission_break: { type: "boolean" },
          signal_break: { type: "boolean" },
          file_break: { type: "boolean" },
          detail: { type: "string" },
        },
        required: ["step", "check_point"],
      },
    },
    blocking_breaks: { type: "number" },
    overall: { type: "string", enum: ["CLEAN", "HAS_BREAKS"] },
    summary: { type: "string" },
  },
  required: ["execution_path", "blocking_breaks", "overall"],
}

const MATRIX_SYNC_SCHEMA = {
  type: "object",
  properties: {
    plan_metadata: {
      type: "object",
      properties: {
        p_number: { type: "string" },
        name: { type: "string" },
        file_path: { type: "string" },
        status: { type: "string" },
        description: { type: "string" },
      },
      required: ["p_number", "name"],
    },
    matrix_row_found: { type: "boolean" },
    changes_made: { type: "array", items: { type: "string" } },
    stale_predecessors: { type: "array", items: { type: "string" } },
  },
  required: ["matrix_row_found", "changes_made"],
}


// ═══════════════════════════════════════════════════════════════
// Agent 提示词模板
// ═══════════════════════════════════════════════════════════════

function IMPACT_AGENT_PROMPT(planFilePath, dimension) {
  return `你是影响面分析员，只负责检查【${dimension.name}】这一个维度。

## 计划文件
路径: ${planFilePath}

## 你的任务
阅读计划中提出的修改方案，逐条判断它们是否会影响【${dimension.name}】维度。
不要修改计划文件，只输出发现。

## 检查方向
${dimension.type === 'subsystem' ? `- 计划修改是否会影响 ${dimension.name} 的模块边界？
- 是否需要修改 ${dimension.name} 的公共接口/注册表/配置？
- ${dimension.name} 的调用方是否需要适配？` : ''}
${dimension.type === 'panel' ? `- 计划修改是否触及 ${dimension.name} 面板的 UI 控件？
- 是否需要修改 ${dimension.name} 的信号/槽连接？
- ${dimension.name} 的 ChartWebView/数据流是否需要适配？` : ''}
${dimension.type === 'dynamic' ? `- 根据维度名称 "${dimension.name}" 自行判断检查方向
- 重点关注计划未覆盖的间接影响` : ''}

## 输出
- 每个发现带 severity (高/中/低)、blocking (true/false)、affected_files、rationale
- 若无发现 → no_findings: true`
}

function FINDER_PROMPT(planFilePath, classification, pendingUnresolved, seenIssueKeys, impactFindings) {
  const dimSection = (classification.dimensions || [])
    .map(d => `- **${d.type}/${d.name}**: ${d.rationale || ''}`)
    .join('\n')

  const unresolvedSection = pendingUnresolved && pendingUnresolved.length > 0
    ? `## 上一轮未解决的问题（必须优先处理）\n${JSON.stringify(pendingUnresolved, null, 2)}\n`
    : ''

  const seenSection = seenIssueKeys && seenIssueKeys.length > 0
    ? `## 前轮已发现的等价问题（不要重复报告）\n${seenIssueKeys.map(k => `- ${k}`).join('\n')}\n`
    : ''

  const impactSection = impactFindings && impactFindings.length > 0
    ? `## 阶段 1 影响面发现（需在计划中响应）\n${JSON.stringify(impactFindings, null, 2)}\n`
    : ''

  return `你是计划审查发现者（Finder）。唯一职责：阅读计划文件 + 靶向代码，输出问题列表。**只发现不修改。**

## 计划文件
路径: ${planFilePath}
复杂度: ${classification.complexity} | 变更性质: ${classification.change_nature}

${unresolvedSection}
${seenSection}
${impactSection}

## 审查维度

### 1. 影响面追踪
逐条检查阶段 1 的发现是否在计划中有响应。未响应的阻塞项 → 标记为 ISSUE。

### 2. 事实验证
计划提到的函数/类/方法名是否真实存在？Read 打开计划列出的 .py 文件，对比计划描述与实际签名。

### 3. 逻辑闭合
步骤顺序是否合理？A 的输出类型与 B 的输入类型是否匹配？修改是否会破坏调用链？

### 4. 边界覆盖
空状态/极值/用户中断/配置缺失——是否逐一考虑？

### 5. 兼容策略
${classification.change_nature === 'breaking'
    ? '是否提供迁移路径/废弃警告/版本号变更？'
    : '旧配置/旧缓存/旧API是否仍可用？'}

### 6. 文档同步
是否标注需更新的文档文件和章节？API 变更是否提到 CLAUDE.md？

### 7. 前置依赖
模块状态矩阵中前置计划的状态是否正确？

### 8. 根因深度
修复方案针对症状还是根因？评估：症状修复 / 机制修复 / 架构修复。

## 输出要求
- 每个问题附带 relevant_code_snippet（原始代码片段，供修复者验证）
- 每个问题附带 suggested_fix_direction（1-2 句建议）
- id 格式: ISSUE-XXX（三位数字）
- 无新发现且无遗留 → no_new_issues: true

## 分类器维度
${dimSection}

## 约束
- Read 计划文件 + 靶向代码，不扩展搜索
- 不修改任何文件
- 描述模糊 → 标记低风险，不猜测`
}

function FIXER_PROMPT(planFilePath, issues, changeNature, complexity) {
  const issuesJson = JSON.stringify(issues, null, 2)

  let repairMode = 'conservative'
  if (complexity === 'complex' || changeNature === 'breaking') {
    repairMode = 'aggressive'
  } else if (complexity === 'medium') {
    repairMode = 'moderate'
  }

  const modeInstructions = {
    conservative: '最小改动——只改受影响段落，保留章节结构，不删内容。',
    moderate: '可重组段落、重写不清表述，保留章节标题。',
    aggressive: '可重组章节结构、重写段落、添加新建议、调整优先级。不可改变核心架构决策。',
  }

  return `你是计划修复者（Fixer）。唯一职责：根据问题列表修改计划文件。

## 计划文件: ${planFilePath}

## 问题列表
${issuesJson}

## 修复模式: ${repairMode}
${modeInstructions[repairMode]}

## 规则
1. Read 打开计划文件 → 逐条处理每个 ISSUE
2. 优先用 relevant_code_snippet 验证问题，仅在缺失时自行读代码
3. 每条修复标注: \`<!-- REVIEW-R1-FIX: ISSUE-XXX -->\`
4. 冲突 → 选保守方案，标注 \`⚠️ 待人工裁决\`
5. 使用 Edit 直接修改计划文件
6. 返回 modified_sections, applied_labels, skipped_issues, write_success`
}

function VERIFIER_PROMPT(planFilePath, originalIssues) {
  return `你是计划验证者（Verifier）。唯一职责：逐项验证修复是否到位。

## 计划文件: ${planFilePath}

## 原始问题: ${JSON.stringify(originalIssues, null, 2)}

## 流程
1. Read 打开计划文件
2. 对每个 ISSUE-XXX：定位 \`<!-- REVIEW-R1-FIX: ISSUE-XXX -->\` → 对照原始问题 → 判决

## 判决
- PASS: 需提供证据（修改后文本片段）
- FAIL: "表面修复" / 过度修复 / 方向错误
- PARTIAL: 部分修复——列出 resolved_items 和 unresolved_items

默认立场：不信任修复——需确凿证据才给 PASS/PARTIAL。`
}

function GATE_PROMPT(planFilePath, classification) {
  return `你是可行性门控器（Gate）。对计划运行 6 项深度检查。**只诊断不修改。**

## 计划文件: ${planFilePath}
复杂度: ${classification.complexity} | 变更性质: ${classification.change_nature}

## 6 项检查

### 1. 变更粒度
- L1: 每个任务 ≤ 1h？过大 → NEEDS_SPLIT（输出拆分建议）
- L2: 描述模糊 → NEEDS_CLARIFY（输出澄清建议）

### 2. 文件清单
- L1: 每步标注文件+函数
- L2: 随机抽样 3 个文件验证代码一致性

### 3. 依赖顺序
- L1: 步骤依赖无环
- L2: 输入/输出类型匹配

### 4. 风险缓解
- L1: 阻塞项全响应
- L2: 缓解可操作 + 严重度匹配

### 5. 回滚路径
- L1: 有回滚策略
- L2: 每步可独立回滚

### 6. 测试策略
- L1: 每步有验收方式
- L2: 验收含具体输入/期望输出 + 覆盖边界

## 输出
- PASS: 该项通过
- NEEDS_SPLIT: 任务太大需拆分（附 split_suggestions）
- NEEDS_CLARIFY: 描述模糊需澄清（附 clarify_suggestions）
- FAIL: 根本性缺失、无法给出具体修改建议

overall: PASS | NEEDS_FIX (有 NEEDS_SPLIT/CLARIFY) | FAIL (无法诊断出修改方案)`
}

function CODE_AUDIT_MAP_PROMPT(planFilePath) {
  return `你是代码审计员（4a: 代码映射）。逐条将计划的修改条目映射到实际代码。

## 计划文件: ${planFilePath}

## 任务
Read 打开计划文件 → 从「实施路线」/「方案」章节逐条提取修改条目 → 对每条：
1. Read 对应的 .py 文件
2. 定位要修改的代码位置（文件:行号）
3. 记录当前逻辑（3-5 句话，不猜测）
4. 分析上下游影响（谁调用它 / 它调用谁）
5. 评估风险（行数 / 接口破坏 / 级联改动）

## 冲突检测
逐对检查修改条目间矛盾（A 改签名，B 以旧签名调用）。

## 传递缺口
A 改了 → A 的调用方 B 也需改 → 计划没提 B → 标记为 gap。

## 输出
mappings: 逐条映射
conflicts: 冲突项
transitive_gaps: 传递缺口`
}

function CODE_AUDIT_EXEC_PROMPT(planFilePath, auditMappings) {
  return `你是代码审计员（4b: 全链条逻辑审计）。

## 计划文件: ${planFilePath}

## 4a 代码映射结果
${JSON.stringify(auditMappings, null, 2)}

## 任务
沿数据流逐环节模拟完整执行路径。在每个修改点停下来验证：

### 断裂类型
- **类型断裂**: 上游输出 type X，下游期望 type Y，无转换
- **空值断裂**: 上游可能返回 None，下游直接调 .attr
- **权限断裂**: 子线程尝试访问 GUI 控件
- **信号断裂**: 信号签名变化但槽函数未同步
- **文件断裂**: 路径逻辑与项目路径系统不一致

## 输出
execution_path: 逐步骤检查结果
blocking_breaks: 阻塞断裂数
overall: CLEAN / HAS_BREAKS`
}

function MATRIX_SYNC_PROMPT(planFilePath, planIdentity) {
  return `你是矩阵同步员。对比计划文件元数据与模块状态矩阵，更新不一致项。

## 计划文件
路径: ${planFilePath}
P编号: ${planIdentity.p_number || '未知'}

## 任务

### 1. 提取计划元数据
Read 打开计划文件，从 META 头（\`<!-- META: ... -->\`）和标题提取：
- P编号、名称、状态、一句话描述、所属模块路径

### 2. 对比模块状态矩阵
Read 打开 docs/00-meta/模块状态矩阵.md
- 在「三、活跃计划索引」或「02-待办」中定位该 P 编号的行
- 逐字段对比：名称、文件路径、状态、一句话描述
- 不一致 → 使用 Edit 更新该行

### 3. 检查前置依赖
- 计划标注的前置计划（如「前置：P18」）→ 检查其在矩阵中的状态是否滞后
- 滞后项记录到 stale_predecessors

### 状态映射
META status → 矩阵显示:
- in_progress → 🔄 实施中
- done / completed → ✅ 已完成
- designing → 📋 设计中
- blocked → 🔴 阻塞

### 输出
- matrix_row_found: 是否在矩阵中找到对应行
- changes_made: 实际修改的字段列表（如["状态: 设计中→已完成", "名称修正"]）
- stale_predecessors: 状态滞后的前置计划编号列表`
}


// ═══════════════════════════════════════════════════════════════
// 主流程
// ═══════════════════════════════════════════════════════════════

const planFilePath = Array.isArray(args) ? args[0] : (args || null)
if (!planFilePath) {
  log('用法: /workflow plan-review "docs/01-活跃/panels/{模块}/P{n} {名称}.md"')
  throw new Error('缺少计划文件路径参数')
}

log(`审查目标: ${planFilePath}`)

// ── 幂等性预检 ──────────────────────────────────────────────
const idempotencyResult = await agent(
  `你是幂等性检测员。Read 打开计划文件 ${planFilePath}，检测以下内容：

1. 文件是否已有 \`<!-- REVIEW-FIX:\` 或 \`<!-- REVIEW-R\` 标注？
2. 文件是否已有「自动化审查记录」章节（含 \<details\> 折叠区）？
3. 文件是否已有「⚠️ 自动化审查阻塞项」章节？

处理规则：
- 若存在旧的 REVIEW-FIX 标注 → 使用 Edit 将它们全部重编号为 \`<!-- REVIEW-FIX-PREV: -->\`，避免与新一轮混淆
- 若存在「自动化审查记录」→ 将最近的 \<details\> 区块标题改为「第 N-1 次审查（上次）」，无需额外操作
- 若存在「⚠️ 自动化审查阻塞项」→ 使用 Edit 删除该章节（默认行为：重新开始）
- 若以上均不存在 → 无操作

返回: { had_previous_review: true/false, had_block_section: true/false, actions_taken: ["..."] }`,
  {
    label: 'idempotency-check',
    phase: 'Classify',
    schema: {
      type: "object",
      properties: {
        had_previous_review: { type: "boolean" },
        had_block_section: { type: "boolean" },
        actions_taken: { type: "array", items: { type: "string" } },
      },
      required: ["had_previous_review"],
    },
  }
)

if (idempotencyResult) {
  if (idempotencyResult.had_previous_review) {
    log(`检测到第 N 次运行——上次审查标注已折叠 (${(idempotencyResult.actions_taken || []).join(', ')})`)
  }
  if (idempotencyResult.had_block_section) {
    log('检测到旧阻塞项章节——已清理（重新开始）')
  }
}

// ── 阶段 0: 分类器 ──────────────────────────────────────────
phase('Classify')

const grepSignalResult = await agent(
  `你是改动目标信号提取器。Read 计划文件 ${planFilePath}，从「实施路线」/「方案」/「步骤」等实施章节中提取**计划明确要修改的符号**。

## 要提取的（改动目标）
- 计划说"修改/重构/新增/删除/归一化/重命名/拆出/合并"的函数名、类名、方法名
- 计划说"新增文件"中要创建的函数/类

## 不提取的（工具/手段）
- 实施过程中调用的现有 API / Qt 方法 / 标准库（即使出现在实施步骤中）
- 只在背景描述、现状分析、代码示例中出现的符号
- 计划明确说不改的符号

## 示例
- 「将 _build_resource_gain() 中的日历展开代码删除，改为调用 expand_gain_rules_to_schedule()」
  → 提取: _build_resource_gain, expand_gain_rules_to_schedule
  → 不提取: fromordinal（标准库）, blockSignals（调用现有 Qt 方法）
- 「_refresh_from_store_impl() 中增加 blockSignals(True) 包裹 date_edit 赋值」
  → 提取: _refresh_from_store_impl
  → 不提取: blockSignals（Qt 方法，仅被调用）、date_edit（UI 控件属性）

对每个提取的符号，grep -l 搜索其在代码库中的文件分布。返回 { symbols: [{ name, found_in_files }] }`,
  {
    label: 'grep-signal',
    phase: 'Classify',
    schema: {
      type: "object",
      properties: {
        symbols: {
          type: "array",
          items: {
            type: "object",
            properties: {
              name: { type: "string" },
              found_in_files: { type: "array", items: { type: "string" } },
            },
            required: ["name", "found_in_files"],
          },
        },
      },
      required: ["symbols"],
    },
  }
)

const grepSummary = grepSignalResult
  ? `${grepSignalResult.symbols.length} 个符号在 ${new Set(grepSignalResult.symbols.flatMap(s => s.found_in_files)).size} 个文件中发现`
  : 'Grep 信号: 不可用'

log(grepSummary)

const classifyPrompt = `你是计划分类器。分析以下计划文件。

## 计划文件路径: ${planFilePath}

## Grep 扫描信号
${grepSummary}
${grepSignalResult ? JSON.stringify(grepSignalResult.symbols.slice(0, 20), null, 2) : ''}

Read 打开计划文件，输出分类结果。

### 任务
1. plan_identity: P编号/模块路径/优先级
2. complexity: simple(≤2文件/无架构变更) | medium(3-5文件/跨模块) | complex(>5文件/架构变更)
3. change_nature: evolutionary | breaking | greenfield
4. dimensions: 受影响子系统/面板/动态维度，每个附 rationale
5. excluded: 明确排除的默认维度及理由（如"并行模拟"与计划无关）
6. defect_count: 计划中列出的缺陷/修复条目总数（从"实施路线"/"方案"章节统计）
7. recommendation: max_adversarial_rounds(simple→2,medium→3,complex→4), max_gate_retries(simple→1,medium→2,complex→3)
8. skip_stages: greenfield→["code_audit"]; simple+无.py→["fan_out_impact","code_audit"]; simple+1面板→["fan_out_impact"]

脚本层自动校验: 涉及≥5 .py但complexity=simple→修正为medium；缺陷数≥6但complexity≠complex→修正为complex；计划提及的.py不在维度中→追加面板维度；分类器排除的维度在grep信号中出现→恢复维度`

const classification = await agent(classifyPrompt, {
  label: 'classifier',
  phase: 'Classify',
  schema: CLASSIFY_SCHEMA,
})

if (!classification) throw new Error('分类器返回 null——无法继续')

// 脚本层校验
let autoCorrected = false
const planPyFiles = grepSignalResult
  ? [...new Set(grepSignalResult.symbols.flatMap(s => s.found_in_files).filter(f => f.endsWith('.py')))]
  : []

if (planPyFiles.length >= 5 && classification.complexity === 'simple') {
  log(`⚠️ complexity simple→medium（${planPyFiles.length} 个 .py 文件）`)
  classification.complexity = 'medium'
  autoCorrected = true
}

const dimNames = (classification.dimensions || []).map(d => d.name)
const missingPanels = planPyFiles
  .filter(f => f.includes('gui/') && f.endsWith('_panel.py'))
  .map(f => f.replace(/.*gui\//, '').replace('_panel.py', ''))
  .filter(p => !dimNames.some(d => d.includes(p)))

if (missingPanels.length > 0) {
  log(`⚠️ 追加 ${missingPanels.length} 个遗漏面板维度: ${missingPanels.join(', ')}`)
  classification.dimensions.push(...missingPanels.map(p => ({
    type: 'panel', name: p, rationale: '脚本层自动追加',
  })))
  autoCorrected = true
}

// 缺陷数校验：≥6 但 complexity ≠ complex → 自动修正
const defectCount = classification.defect_count || 0
if (defectCount >= 6 && classification.complexity !== 'complex') {
  log(`⚠️ complexity ${classification.complexity}→complex（${defectCount} 个缺陷/条目）`)
  classification.complexity = 'complex'
  autoCorrected = true
}

// 排除维度恢复：分类器排除的维度在 grep 信号中出现 → 恢复
const excludedDims = classification.excluded || []
const restoredDims = []
for (const excl of excludedDims) {
  const foundInGrep = grepSignalResult
    ? grepSignalResult.symbols.some(s => s.found_in_files.some(f => f.toLowerCase().includes(excl.name.toLowerCase())))
    : false
  if (foundInGrep) {
    restoredDims.push(excl.name)
    classification.dimensions.push({
      type: 'subsystem', name: excl.name,
      rationale: `脚本层恢复——分类器排除但 grep 信号中发现 ${excl.name} 相关代码`,
    })
  }
}
if (restoredDims.length > 0) {
  log(`⚠️ 恢复 ${restoredDims.length} 个被排除的维度: ${restoredDims.join(', ')}`)
  autoCorrected = true
}

const maxRounds = classification.recommendation.max_adversarial_rounds || 3
const maxGateRetries = classification.recommendation.max_gate_retries || 2
const globalBacktrackLimit = maxRounds + 2
let totalBacktracks = 0

log(`分类: ${classification.plan_identity.p_number} | ${classification.complexity} | ${classification.change_nature} | rounds=${maxRounds}${autoCorrected ? ' (已自动修正)' : ''}`)
if (classification.skip_stages && classification.skip_stages.length > 0) {
  log(`跳过: ${classification.skip_stages.join(', ')}`)
}

const skipStage = (name) => (classification.skip_stages || []).includes(name)


// ── 阶段 1: 扇出影响面 ──────────────────────────────────────
let allImpactFindings = []

if (!skipStage('fan_out_impact') && classification.dimensions && classification.dimensions.length > 0) {
  phase('Impact')
  log(`扇出 ${classification.dimensions.length} 个维度并行分析`)

  const impactResults = await parallel(
    classification.dimensions.map(dim => () =>
      agent(IMPACT_AGENT_PROMPT(planFilePath, dim), {
        label: `impact:${dim.name}`,
        phase: 'Impact',
        schema: IMPACT_SCHEMA,
      })
    )
  )

  allImpactFindings = impactResults.filter(Boolean).flatMap(r => r.findings || [])
  const blockingCount = allImpactFindings.filter(f => f.blocking).length
  log(`影响面: ${allImpactFindings.length} 个发现 (${blockingCount} 阻塞)`)
} else {
  log('跳过阶段 1 (fan_out_impact)')
}


// ── 阶段 2: 对抗循环 ────────────────────────────────────────
log(`开始对抗循环 (最多 ${maxRounds} 轮)`)
phase('Find')

let dryRounds = 0, totalRounds = 0
let pendingUnresolved = []
const seenIssueKeys = new Set()

while (dryRounds < 2 && totalRounds < maxRounds) {
  totalRounds++
  log(`── 第 ${totalRounds}/${maxRounds} 轮 ──`)

  const finderResult = await agent(
    FINDER_PROMPT(planFilePath, classification,
      pendingUnresolved.length > 0 ? pendingUnresolved : null,
      seenIssueKeys.size > 0 ? [...seenIssueKeys] : null,
      allImpactFindings.length > 0 ? allImpactFindings : null
    ),
    { label: `finder-r${totalRounds}`, phase: 'Find', schema: FINDER_SCHEMA }
  )

  if (!finderResult) { log(`⚠️ Finder 返回 null——跳过`); continue }

  const trulyNewIssues = (finderResult.new_issues || []).filter(issue => {
    const key = `${issue.dimension || ''}::${issue.title || ''}::${(issue.affected_files || []).join(',')}`
    if (seenIssueKeys.has(key)) return false
    seenIssueKeys.add(key)
    return true
  })

  log(`  Finder: ${trulyNewIssues.length} 新 + ${pendingUnresolved.length} 遗留`)

  const hasUnresolved = pendingUnresolved.length > 0
  if (trulyNewIssues.length === 0 && !hasUnresolved) {
    dryRounds++
    log(`  无新发现且无遗留 → dryRounds=${dryRounds}`)
    if (dryRounds >= 2) { log('✅ 收敛'); break }
    continue
  }
  dryRounds = 0

  const issuesToFix = [
    ...trulyNewIssues,
    ...pendingUnresolved.map(item => ({ ...item, source: 'previous_round_unresolved' })),
  ]
  if (issuesToFix.length === 0) continue

  // Fix
  phase('Fix')
  const fixerResult = await agent(
    FIXER_PROMPT(planFilePath, issuesToFix, classification.change_nature, classification.complexity),
    { label: `fixer-r${totalRounds}`, phase: 'Fix', schema: FIXER_SCHEMA }
  )

  if (!fixerResult || !fixerResult.write_success) {
    log(`⚠️ Fixer 失败——问题保留`)
    pendingUnresolved = issuesToFix.map(i => ({
      issue_id: i.id || i.issue_id, description: i.description, dimension: i.dimension,
    }))
    continue
  }

  log(`  Fixer: ${fixerResult.modified_sections.length} 处修改, ${fixerResult.applied_labels.length} 标注`)
  if (fixerResult.conflicts && fixerResult.conflicts.length > 0) {
    log(`  ⚠️ ${fixerResult.conflicts.length} 处冲突`)
  }

  // Verify
  phase('Verify')
  const verifierResult = await agent(
    VERIFIER_PROMPT(planFilePath, issuesToFix),
    { label: `verifier-r${totalRounds}`, phase: 'Verify', schema: VERIFIER_SCHEMA }
  )

  if (!verifierResult) {
    log(`⚠️ Verifier null——假设全部未解决`)
    pendingUnresolved = issuesToFix.map(i => ({
      issue_id: i.id || i.issue_id, description: i.description, dimension: i.dimension,
    }))
    continue
  }

  const pCount = verifierResult.verifications.filter(v => v.verdict === 'PASS').length
  const fCount = verifierResult.verifications.filter(v => v.verdict === 'FAIL').length
  const partCount = verifierResult.verifications.filter(v => v.verdict === 'PARTIAL').length
  log(`  Verifier: ${pCount}P ${fCount}F ${partCount}PART`)

  pendingUnresolved = [
    ...verifierResult.verifications.filter(v => v.verdict === 'FAIL').map(v => {
      const orig = issuesToFix.find(i => (i.id || i.issue_id) === v.issue_id)
      return { issue_id: v.issue_id, description: orig?.description || '', dimension: orig?.dimension || '', fail_reason: v.reason }
    }),
    ...verifierResult.verifications.filter(v => v.verdict === 'PARTIAL' && v.unresolved_items?.length > 0).map(v => {
      const orig = issuesToFix.find(i => (i.id || i.issue_id) === v.issue_id)
      return { issue_id: v.issue_id, description: orig?.description || '', dimension: orig?.dimension || '', sub_items: v.unresolved_items }
    }),
  ]

  phase('Find')
}

// 阶段 2 熔断
if (dryRounds < 2 && totalRounds >= maxRounds) {
  log(`🛑 对抗循环熔断: ${maxRounds} 轮未收敛, ${pendingUnresolved.length} 遗留`)

  await agent(
    `Read 打开 ${planFilePath}，在末尾追加「## ⚠️ 自动化审查阻塞项」章节，列出 ${pendingUnresolved.length} 个未解决问题及详情: ${JSON.stringify(pendingUnresolved)}。标注原因: ${maxRounds} 轮对抗循环未收敛。`,
    { label: 'block-writer', phase: 'Verify' }
  )
}


// ── 阶段 3: 可行性门控 ──────────────────────────────────────
phase('Gate')

let gatePassed = false
let gateFixAttempts = 0

// 门控内部修复循环
while (!gatePassed && gateFixAttempts <= maxGateRetries) {
    const gateResult = await agent(
      GATE_PROMPT(planFilePath, classification),
      { label: gateFixAttempts === 0 ? 'gate' : `gate-retry-${gateFixAttempts}`, phase: 'Gate', schema: GATE_SCHEMA }
    )

    if (!gateResult) {
      log('⚠️ 门控器返回 null——跳过门控')
      gatePassed = true
      break
    }

    const failCount = gateResult.checks.filter(c => c.verdict === 'FAIL').length
    const needsFixCount = gateResult.checks.filter(c => c.verdict === 'NEEDS_SPLIT' || c.verdict === 'NEEDS_CLARIFY').length
    const passCount = gateResult.checks.filter(c => c.verdict === 'PASS').length
    log(`  门控: ${passCount}P ${needsFixCount}NEEDS_FIX ${failCount}FAIL`)

    if (gateResult.overall === 'PASS') {
      log('✅ 可行性门控通过')
      gatePassed = true
      break
    }

    if (gateResult.overall === 'NEEDS_FIX' && gateFixAttempts < maxGateRetries) {
      gateFixAttempts++
      log(`  门控 NEEDS_FIX → 内部修复 ${gateFixAttempts}/${maxGateRetries}`)

      // 门控内部修复循环（修复者+验证者，无 Finder）
      const gateIssues = gateResult.checks
        .filter(c => c.verdict === 'NEEDS_SPLIT' || c.verdict === 'NEEDS_CLARIFY')
        .map(c => ({
          issue_id: `GATE-${c.id}`,
          description: c.detail,
          split_suggestions: c.split_suggestions,
          clarify_suggestions: c.clarify_suggestions,
          dimension: '可行性门控',
        }))

      const gateFixerResult = await agent(
        FIXER_PROMPT(planFilePath, gateIssues, classification.change_nature, classification.complexity),
        { label: `gate-fixer-${gateFixAttempts}`, phase: 'Gate', schema: FIXER_SCHEMA }
      )

      if (!gateFixerResult || !gateFixerResult.write_success) {
        log('  ⚠️ 门控修复失败——重试')
        continue
      }

      const gateVerifierResult = await agent(
        VERIFIER_PROMPT(planFilePath, gateIssues),
        { label: `gate-verifier-${gateFixAttempts}`, phase: 'Gate', schema: VERIFIER_SCHEMA }
      )

      if (gateVerifierResult && gateVerifierResult.overall === 'ALL_PASS') {
        log('  门控修复验证通过 → 重新门控')
      }
      continue
    }

    if (gateResult.overall === 'FAIL' || gateFixAttempts >= maxGateRetries) {
      // 退回阶段 2（完整对抗循环）
      totalBacktracks++
      log(`  门控 FAIL → 退回阶段 2 (${totalBacktracks}/${globalBacktrackLimit})`)

      if (totalBacktracks > globalBacktrackLimit) {
        log(`🛑 全局熔断: ${totalBacktracks} 次退回 > ${globalBacktrackLimit}`)
        await agent(
          `Read ${planFilePath}，追加「⚠️ 自动化审查阻塞项」章节: 全局熔断——${totalBacktracks} 次退回阶段 2，超过上限 ${globalBacktrackLimit}。${JSON.stringify(gateResult.checks.filter(c => c.verdict === 'FAIL'))}`,
          { label: 'block-writer', phase: 'Gate' }
        )
        break
      }

      // 将 FAIL 项转为发现者问题 → 重跑阶段 2（简化为一轮快速修复）
      const failIssues = gateResult.checks
        .filter(c => c.verdict === 'FAIL')
        .map(c => ({
          issue_id: `GATE-FAIL-${c.id}`, description: c.detail, dimension: '可行性门控',
        }))

      const retryFixes = await agent(
        FIXER_PROMPT(planFilePath, failIssues, classification.change_nature, 'aggressive'),
        { label: 'gate-fail-fixer', phase: 'Gate', schema: FIXER_SCHEMA }
      )

      if (retryFixes && retryFixes.write_success) {
        log('  退回修复完成——重新门控')
        gateFixAttempts = 0  // 重置门控内部计数器
      }
      continue
    }
  }

  if (!gatePassed) {
    log('⚠️ 门控未通过——继续后续阶段（门控非硬阻塞）')
  }

  // complex+breaking 警告
  if (gatePassed && classification.complexity === 'complex' && classification.change_nature === 'breaking') {
    log('⚠️ 此为 complex+breaking 计划——建议人工复核后再继续代码审计')
  }


// ── 阶段 4: 代码审计 ────────────────────────────────────────
if (!skipStage('code_audit')) {
  phase('Audit')
  log('开始代码审计')

  // 4a: 代码映射
  const auditMapResult = await agent(
    CODE_AUDIT_MAP_PROMPT(planFilePath),
    { label: 'audit-map', phase: 'Audit', schema: AUDIT_MAP_SCHEMA }
  )

  if (auditMapResult) {
    log(`  4a 代码映射: ${auditMapResult.mappings.length} 条`)
    if (auditMapResult.conflicts && auditMapResult.conflicts.length > 0) {
      log(`  ⚠️ ${auditMapResult.conflicts.length} 处冲突`)
    }
    if (auditMapResult.transitive_gaps && auditMapResult.transitive_gaps.length > 0) {
      log(`  ⚠️ ${auditMapResult.transitive_gaps.length} 个传递缺口`)
    }

    // 4b: 全链条审计
    const auditExecResult = await agent(
      CODE_AUDIT_EXEC_PROMPT(planFilePath, auditMapResult),
      { label: 'audit-exec', phase: 'Audit', schema: AUDIT_EXECUTION_SCHEMA }
    )

    if (auditExecResult) {
      log(`  4b 全链条审计: ${auditExecResult.blocking_breaks} 处阻塞断裂`)

      if (auditExecResult.blocking_breaks > 0) {
        totalBacktracks++
        if (totalBacktracks > globalBacktrackLimit) {
          log(`🛑 全局熔断: ${totalBacktracks}/${globalBacktrackLimit}`)
          await agent(
            `Read ${planFilePath}，追加「⚠️ 自动化审查阻塞项」: 代码审计发现 ${auditExecResult.blocking_breaks} 处阻塞断裂，全局熔断触发。${JSON.stringify(auditExecResult.execution_path.filter(s => s.type_break || s.null_break || s.permission_break || s.signal_break))}`,
            { label: 'block-writer', phase: 'Audit' }
          )
        } else {
          log(`  🔄 退回阶段 2（代码审计阻塞断裂）`)
          // 将断裂点转为发现者问题
          const breakIssues = auditExecResult.execution_path
            .filter(s => s.type_break || s.null_break || s.permission_break || s.signal_break)
            .map((s, i) => ({
              issue_id: `AUDIT-BREAK-${i + 1}`,
              description: `${s.step}: ${s.detail || ''}`,
              dimension: '代码审计',
            }))

          if (breakIssues.length > 0) {
            const breakFixes = await agent(
              FIXER_PROMPT(planFilePath, breakIssues, 'breaking', 'aggressive'),
              { label: 'audit-fixer', phase: 'Audit', schema: FIXER_SCHEMA }
            )
            if (breakFixes && breakFixes.write_success) {
              log(`  审计断裂修复完成: ${breakFixes.modified_sections.length} 处`)
            }
          }
        }
      }
    }
  }
} else {
  log('跳过阶段 4 (code_audit)')
}


// ── 阶段 5: 矩阵同步 ──────────────────────────────────────
phase('Matrix Sync')
log('同步模块状态矩阵')

const matrixSyncResult = await agent(
  MATRIX_SYNC_PROMPT(planFilePath, classification.plan_identity),
  { label: 'matrix-sync', phase: 'Matrix Sync', schema: MATRIX_SYNC_SCHEMA }
)

if (matrixSyncResult) {
  if (matrixSyncResult.matrix_row_found) {
    const changes = matrixSyncResult.changes_made || []
    log(`  矩阵同步: ${changes.length} 处更新${changes.length > 0 ? ' — ' + changes.join(', ') : ''}`)
  } else {
    log('  ⚠️ 未在矩阵中找到该计划行——可能需要手动注册')
  }
  if (matrixSyncResult.stale_predecessors && matrixSyncResult.stale_predecessors.length > 0) {
    log(`  ⚠️ 前置计划状态可能滞后: ${matrixSyncResult.stale_predecessors.join(', ')}`)
  }
} else {
  log('  ⚠️ 矩阵同步 agent 返回 null——跳过')
}


// ── 汇总 ────────────────────────────────────────────────────
phase('Summary')
log('')
log('═══════════════════════════════════════')
log(`审查完成: P${classification.plan_identity.p_number} ${classification.plan_identity.file}`)
log(`复杂度: ${classification.complexity} | 变更性质: ${classification.change_nature}`)
log(`阶段 2: ${totalRounds} 轮对抗循环 → ${dryRounds >= 2 ? '✅ 收敛' : '🛑 熔断'}`)
log(`阶段 3: 可行性门控（6 项检查）`)
log(`阶段 4: 代码审计`)
log(`阶段 5: 矩阵同步`)
log(`累计问题: ${seenIssueKeys.size} 个 | 退回次数: ${totalBacktracks}/${globalBacktrackLimit}`)
log('═══════════════════════════════════════')

// 追加审查记录到计划文件
const reviewDate = '2026-06-11'  // 由 harness 的 argless Date 限制——实际运行时用当前日期
await agent(
  `Read 打开 ${planFilePath}，在文件末尾「自动化审查记录」章节（若存在则追加新条目，否则创建该章节）追加本次审查摘要：

<details>
<summary>第 N 次审查（${reviewDate}）——P38 工作流自动化</summary>

- 复杂度: ${classification.complexity} | 变更性质: ${classification.change_nature}
- 阶段 1 影响面: ${allImpactFindings.length} 个发现
- 阶段 2 对抗循环: ${totalRounds} 轮，${dryRounds >= 2 ? '收敛' : '熔断'}
- 阶段 3 门控: 6 项检查
- 阶段 4 代码审计: ${skipStage('code_audit') ? '跳过' : '已执行'}
- 累计问题: ${seenIssueKeys.size} 个

</details>

使用 Edit 追加。返回 { appended: true }。`,
  { label: 'review-logger', phase: 'Summary', schema: { type: "object", properties: { appended: { type: "boolean" } }, required: ["appended"] } }
)

log('审查记录已追加到计划文件')
