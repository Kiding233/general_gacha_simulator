#!/usr/bin/env python3

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QWidget, QLabel,
    QTextBrowser, QDialogButtonBox, QHBoxLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于 GachaStat")
        self.setMinimumSize(700, 550)
        self.resize(750, 600)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title_label = QLabel("GachaStat")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header.addWidget(title_label)

        from .._version import VERSION_DISPLAY
        ver_label = QLabel(VERSION_DISPLAY)
        ver_font = QFont()
        ver_font.setPointSize(14)
        ver_label.setFont(ver_font)
        ver_label.setStyleSheet("color: #666;")
        header.addWidget(ver_label)
        header.addStretch()
        layout.addLayout(header)

        subtitle = QLabel("蒙特卡洛抽卡模拟与多维分析工具")
        subtitle.setStyleSheet("color: #888; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.addTab(self._create_about_tab(), "关于")
        tabs.addTab(self._create_version_tab(), "版本历史")
        tabs.addTab(self._create_config_guide_tab(), "配置文件指南")
        tabs.addTab(self._create_algorithms_tab(), "算法说明")
        layout.addWidget(tabs)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)

    def _create_about_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml("""
        <h3>GachaStat</h3>
        <p>一个灵活的蒙特卡洛抽卡模拟与多维分析工具，支持多种保底机制、策略配置和统计分析。</p>

        <h4>核心功能</h4>
        <ul>
            <li><b>灵活的模拟引擎</b>：支持多池、多保底、多策略的抽卡模拟</li>
            <li><b>保底机制</b>：软保底（线性/指数/阶梯提升）、硬保底、多保底并行</li>
            <li><b>策略系统</b>：6 种策略（按需追卡、指定池配额、保底预留、目标即停、指定池追卡、固定次数）+ 策略比较面板</li>
            <li><b>停止条件系统</b>：6 种停止条件（所有池结束、固定次数、资源阈值、目标达成、抽到指定卡、时间限制）</li>
            <li><b>广义出率（GDR）</b>：13 种可配置的广义出率指标</li>
            <li><b>脆弱性分析</b>：核密度回归估计条件失败概率</li>
            <li><b>退路搜索</b>：最小资源/最大目标/Pareto 前沿</li>
            <li><b>最差影响分析</b>：条件分布下尾分位数评估</li>
            <li><b>前进法/后退法</b>：目标卡集合优化</li>
            <li><b>资源搜索</b>：二分搜索最小资源量</li>
            <li><b>风险分析</b>：VaR/CVaR、经验分布、条件分布</li>
            <li><b>权重配置</b>：抽取意愿/错失代价/出卡价值三维权重</li>
        </ul>

        <h4>技术栈</h4>
        <ul>
            <li>Python 3.10+</li>
            <li>PyQt6（GUI）</li>
            <li>NumPy（数值计算）</li>
            <li>Matplotlib（可视化）</li>
            <li>statsmodels（核密度回归）</li>
        </ul>

        <h4>许可证</h4>
        <p>本项目拟采用 <b>GNU General Public License v3.0 (GPLv3)</b>，但最终许可方式尚未确定。</p>
        <p>GPLv3 允许自由使用、修改和分发，但要求衍生作品必须以相同许可证开源。</p>
        """)
        layout.addWidget(browser)
        return widget

    def _create_version_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)

        from .._version import VERSION_HISTORY
        rows = ""
        for ver, date, desc in VERSION_HISTORY:
            rows += f"<tr><td><b>{ver}</b></td><td>{date}</td><td>{desc}</td></tr>"

        browser.setHtml(f"""
        <h3>版本历史</h3>
        <table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;'>
        <tr style='background:#f0f0f0;'><th>版本</th><th>日期</th><th>说明</th></tr>
        {rows}
        </table>

        <h4>版本号规则 — Pride Versioning</h4>
        <p>版本号格式：<b>PROUD.DEFAULT.SHAME</b></p>
        <ul>
            <li><b>PROUD</b>：做出让你自豪的变更时递增（递增时重置后两位为 0）</li>
            <li><b>DEFAULT</b>：普通发布时递增</li>
            <li><b>SHAME</b>：修复令人尴尬的 bug 时递增</li>
        </ul>
        <p>每次递增高位时，低位归零。PROUD 递增时 DEFAULT 和 SHAME 归零；DEFAULT 递增时 SHAME 归零。</p>
        """)
        layout.addWidget(browser)
        return widget

    def _create_config_guide_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml("""
        <h3>配置文件指南</h3>
        <p>所有配置文件使用 <code>|</code> 分隔，<code>#</code> 开头为注释，空行忽略。</p>

        <h4>resources.txt — 资源定义</h4>
        <pre>resource_id | 显示名称</pre>
        <p>示例：<code>draw_resource | 抽卡资源</code></p>

        <h4>cards.txt — 卡牌定义</h4>
        <pre>card_id | 名称 | 稀有度</pre>
        <p>示例：<code>ssr_char1 | 角色A | ssr</code></p>

        <h4>schedule.txt — 池子排期</h4>
        <pre>pool_id | 名称 | 开始天 | 结束天 | 费用 | 分布文件 | 绑定(k=v;k=v) | 目标卡(逗号分隔,可选:数量)</pre>
        <p>示例：<code>pool_c1 | 角色池1 | 0 | 21 | draw_resource:160 | pools/character_pool.txt | ssr=ssr_char1;sr=sr1;r=r1 | ssr_char1:1</code></p>
        <p><b>绑定键</b>：ssr, ssr_alt, ssr_alt1, ssr_alt2, featured, offrate, sr, r, rerun_of, exchange_card</p>

        <h4>pity.txt — 保底机制</h4>
        <pre>pity: 名称 | type=soft|hard | 参数... | target=id:权重,... | reset=any_ssr|featured_ssr|never | pools=匹配模式</pre>
        <p>软保底参数：<code>start=N end=N func=linear|exp|step</code></p>
        <p>硬保底参数：<code>threshold=N</code></p>
        <p>示例：<code>pity: ssr_soft | type=soft | start=74 end=90 func=linear | target=ssr:1 | reset=any_ssr | pools=*</code></p>

        <h4>gains.txt — 资源增益</h4>
        <pre>[规则类型: 参数]
resource_id: 数量
day: 天数 | resource_id: 数量, resource_id: 数量</pre>
        <p>规则类型：<code>every_n_days:N</code>, <code>weekly:day</code>, <code>monthly_day:day</code>, <code>monthly_week:week,day</code></p>

        <h4>initial_resources.txt — 初始资源</h4>
        <pre>resource_id | 数量</pre>

        <h4>targets.txt — 目标卡</h4>
        <pre>card_id | 数量 | 池子ID(逗号分隔)</pre>

        <h4>weights.txt — 权重配置（可选）</h4>
        <pre>card_id | desire_weight | miss_cost_weight | card_value</pre>
        <p>默认值均为 1.0。desire_weight 影响前进法排序，miss_cost_weight 影响后退法排序，card_value 影响出卡价值计算。</p>

        <h4>池子分布文件（pools/*.txt）</h4>
        <pre>[层级键]: 概率        # 定义层级概率
[层级键]=[子键1,子键2]  # 定义子层级
[叶键]=绑定键          # 映射到 schedule.txt 中的绑定</pre>
        <p>示例：</p>
        <pre>[1]:0.006
[1]=[featured,offrate]
[featured]:0.5
[offrate]:0.5
[featured]=ssr
[offrate]=ssr_alt
[2]:0.051
[2]=sr
[3]:0.943
[3]=r</pre>
        """)
        layout.addWidget(browser)
        return widget

    def _create_algorithms_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml("""
        <h3>算法说明</h3>

        <h4>蒙特卡洛模拟</h4>
        <p>核心模拟引擎采用蒙特卡洛方法，通过大量随机抽样估计概率分布。标准误 SE = σ/√N，其中 N 为模拟次数。</p>

        <h4>广义出率（GDR）计算</h4>
        <p>支持 13 种 GDR 指标，从 compact 模拟结果中计算：</p>
        <ul>
            <li><b>简单目标达成率</b>：已获得目标卡数 / 需求总数</li>
            <li><b>目标卡收集率</b>：已收集的目标卡种数 / 目标卡总种数</li>
            <li><b>全部目标达成</b>：是否获得全部目标卡（0/1）</li>
            <li><b>SSR收集率</b>：已收集SSR种数 / SSR总种数</li>
            <li><b>资源剩余</b>：初始 + 获得 - 消耗</li>
            <li><b>额外目标卡</b>：超出需求的目标卡数</li>
            <li><b>非保底抽卡数</b>：非保底触发的抽卡次数</li>
            <li><b>保底抽卡数</b>：保底触发的抽卡次数</li>
            <li><b>资源转化效率</b>：目标卡数 / 消耗资源</li>
            <li><b>每池下池出卡率</b>：每个池子下池时出目标卡的概率</li>
            <li><b>专武角色比</b>：已抽角色对应的专武数 / 已抽角色数</li>
            <li><b>加权满意度</b>：desire_weight × 获得 - miss_cost_weight × 未获得</li>
            <li><b>总出卡价值</b>：card_value 之和</li>
        </ul>

        <h4>脆弱性分析</h4>
        <p>对每个池子，使用<b>局部线性核回归</b>（statsmodels.KernelReg, reg_type='ll'）估计条件失败概率 P(失败 | 资源剩余)。当核回归失败时，回退到<b>Nadaraya-Watson 高斯核平滑</b>。识别条件失败概率超过阈值的连续区间为"脆弱性区间"。</p>

        <h4>退路搜索</h4>
        <p>三种搜索模式：</p>
        <ul>
            <li><b>最小资源</b>：两阶段二分搜索——先倍增找上界，再二分精确定位最小资源量</li>
            <li><b>最大目标</b>：逐步移除目标卡（按 miss_cost_weight 升序），每步计算最小资源</li>
            <li><b>Pareto 前沿</b>：遍历目标卡子集，计算资源-目标卡数的 Pareto 最优边界</li>
        </ul>

        <h4>前进法 / 后退法</h4>
        <ul>
            <li><b>前进法</b>：从空集开始，按 desire_weight 降序逐个添加目标卡，直到成功率低于阈值</li>
            <li><b>后退法</b>：从全集开始，按 miss_cost_weight 升序逐个移除目标卡，直到成功率高于阈值</li>
        </ul>

        <h4>最差影响分析</h4>
        <p>基于条件资源分布（按成功/失败分组），计算失败组资源的 α 分位数（VaR），评估最差情况下剩余资源能支撑多少个后续池子。使用蒙特卡洛模拟估计连续通关池数的分布。</p>

        <h4>风险分析</h4>
        <ul>
            <li><b>VaR</b>（Value at Risk）：经验分布的 α 分位数</li>
            <li><b>CVaR</b>（Conditional VaR / Expected Shortfall）：底部 α 尾部的均值</li>
            <li><b>经验 CDF</b>：排序数组的二分搜索</li>
            <li><b>条件分布</b>：按阈值分组后的子分布</li>
        </ul>

        <h4>经验分布</h4>
        <p>分位数计算使用<b>线性插值法</b>：对排序后的样本，在相邻秩之间线性插值。直方图分箱使用<b>IQR 自适应法</b>：当四分位距/全距 &lt; 0.05 时（集中分布），使用 50-200 个 bin；否则使用 30 个 bin。</p>

        <h4>转移矩阵</h4>
        <p>计算相邻池子之间成功/失败状态的 2×2 转移概率矩阵，用于分析池间成败依赖关系。</p>
        """)
        layout.addWidget(browser)
        return widget
