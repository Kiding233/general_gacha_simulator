# Pull Request 规范

## 代码变更范围

**主代码变更限制在 `gacha_simulator/` 目录下，同时应同步更新 `docs/` 中的相关文档。**

### 允许修改的路径

```
gacha_simulator/
├── main.py              # GUI 入口
├── run.py               # 自动选择入口
├── cli.py               # CLI 入口
├── _version.py          # 版本信息
├── config/              # 默认配置文件
│   ├── cards.txt
│   ├── gains.txt
│   ├── initial_resources.txt
│   ├── pity.txt
│   ├── resources.txt
│   ├── schedule.txt
│   ├── targets.txt
│   └── pools/
├── core/                # 核心模拟引擎
├── generator/           # 生成器工具
├── gui/                 # PyQt6 GUI 层
├── resources/           # 资源文件（图标等）
├── service/             # 业务逻辑层
└── visualization/       # 可视化配置

docs/                   # 文档目录（计划、设计规范、交接文档等，需要同步更新）
```

### 禁止修改的路径

以下目录和文件**不应**在 PR 中变更：

| 路径 | 说明 |
|------|------|
| `tests/` | 测试目录（单元测试、测试输出等） |
| `output/` | 示例输出图表 |
| `pyproject.toml` | 项目配置文件 |
| `README.md` | 项目说明文件 |
| `理论参考.svg` | 理论参考图 |

## 提交前检查清单

- [ ] 所有代码变更位于 `gacha_simulator/` 目录内
- [ ] 若代码变更影响功能或 API，已同步更新 `docs/` 中的相关文档
- [ ] 未误删或移动 `gacha_simulator/` 外的文件
- [ ] 未修改测试、配置文件（除非有明确需求并单独说明）

## 文档更新要求

修改代码时，以下情况需要同步更新 `docs/` 中的文档：

1. **新增功能**：添加功能说明和使用指南
2. **API 变更**：更新相关的接口文档
3. **设计调整**：更新对应的设计规范
4. **配置变更**：更新默认配置说明

## 例外情况

如需修改禁止路径中的文件，请在 PR 描述中**单独说明理由**，并建议拆分为独立的 PR。
