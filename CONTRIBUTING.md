# Pull Request 规范

## 代码变更范围

**只允许修改 `gacha_simulator/` 目录下的文件。**

`gacha_simulator/` 是项目的主代码文件夹，直接包含 `main.py` 入口文件。所有代码变更必须限制在此目录内。

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
```

### 禁止修改的路径

以下目录和文件**不应**在 PR 中变更：

| 路径 | 说明 |
|------|------|
| `docs/` | 文档目录（计划、设计规范、交接文档等） |
| `tests/` | 测试目录（单元测试、测试输出等） |
| `output/` | 示例输出图表 |
| `pyproject.toml` | 项目配置文件 |
| `README.md` | 项目说明文件 |
| `理论参考.svg` | 理论参考图 |

## 提交前检查清单

- [ ] 所有变更文件位于 `gacha_simulator/` 目录内
- [ ] 未误删或移动 `gacha_simulator/` 外的文件
- [ ] 未修改文档、测试、配置文件（除非有明确需求并单独说明）

## 例外情况

如需修改禁止路径中的文件，请在 PR 描述中**单独说明理由**，并建议拆分为独立的 PR。
