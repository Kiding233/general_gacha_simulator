#!/usr/bin/env python3

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QWidget, QLabel,
    QTextBrowser, QDialogButtonBox, QHBoxLayout,
)
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
            <li><b>策略系统</b>：6 种策略（按需追卡、指定池配额、保底预留、目标即停、指定池追卡、固定次数）</li>
            <li><b>停止条件系统</b>：6 种停止条件（所有池结束、固定次数、资源阈值、目标达成、抽到指定卡、时间限制）</li>
            <li><b>广义出率（GDR）</b>：17 种可配置的广义出率指标</li>
            <li><b>过程分析</b>：逐池事件推断（7种事件类型）+ AA/BB/AB/BA 四种交叉统计</li>
            <li><b>Bootstrap 稳定性分析</b>：置信区间计算（BCa/GPD/Hill），零额外模拟成本</li>
            <li><b>脆弱性分析</b>：局部逻辑回归估计条件失败概率，识别资源脆弱区间</li>
            <li><b>方案搜索</b>：三合一搜索面板——最少资源（二分搜索）、最多目标卡（前进法/后退法）、资源-目标权衡曲线</li>
            <li><b>比较分析</b>：L1 描述统计 → L2 随机占优 → L3 假设检验（KS/MWU/ttest + Holm/BH校正）→ L4 帕累托前沿，四层递进策略比较</li>
            <li><b>数据管理</b>：模拟结果持久化存储（JSON）、可比性指纹检查、多数据集管理</li>
            <li><b>最差影响分析</b>：条件分布下尾分位数评估</li>
            <li><b>风险分析</b>：VaR/CVaR、经验分布、条件分布</li>
            <li><b>权重配置</b>：抽取意愿/错失代价/出卡价值三维权重</li>
        </ul>

        <h4>技术栈</h4>
        <ul>
            <li>Python 3.10+</li>
            <li>PyQt6（GUI）</li>
            <li>NumPy / SciPy（数值计算）</li>
            <li>Plotly（交互式可视化）</li>
            <li>PyInstaller（应用打包，onedir 分发）</li>
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
        <p><b>费用语法</b>：<code>资源ID:数量</code>。多资源可用 <code>&gt;</code>（大于号）或 <code>,</code>（逗号）分隔，表示按书写顺序的<b>强制优先级</b>——先尝试排在前面的资源，不够再回退到后续资源。</p>
        <p>示例：<code>exchange_currency:5 &gt; draw_resource:160</code> 表示优先消耗兑换货币，不足时再用抽卡资源。</p>
        <p><code>&amp;</code> 表示同时需要多种资源（AND），<code>()</code> 用于分组。完整示例：<code>(draw_resource:160 &gt; exchange_currency:5) &amp; stardust:10</code></p>
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
        <p>支持 17 种 GDR 指标，均从 CompactResult 中 O(1) 计算。标有 <b>↓</b> 的指标 lower_is_better（值越低越好）。</p>
        <p><b>多资源类型支持</b>（v2.0）：资源剩余、资源消耗、目标卡出卡效率、每目标卡资源消耗 4 个指标支持按资源类型展开（如「资源剩余 (抽卡资源)」「资源剩余 (兑换货币)」）。GDR 下拉框中选中不同资源类型的指标后，公式中的 <code>resource_id</code> 自动联动切换，从 CompactResult 的对应字段读取数据。</p>

        <h5>目标达成类</h5>
        <ul>
            <li><b>简单目标达成率</b> = &Sigma; min(抽到数<sub>i</sub>, 需求量<sub>i</sub>) / &Sigma; 需求量<sub>i</sub></li>
            <li><b>目标卡收集率</b> = 至少抽到1张的目标卡种类数 / 目标卡总种类数</li>
            <li><b>抽出全部目标卡</b> = 所有目标卡均满足需求量 → 1.0，否则 → 0.0（二值）</li>
            <li><b>SSR收集率</b> = 至少抽到1张的SSR种类数 / SSR总种类数</li>
        </ul>

        <h5>资源效率类</h5>
        <ul>
            <li><b>资源剩余</b> = 模拟结束时的 <code>final_resources[resource_id]</code>（<code>resource_id</code> 由 GDR key 中 <code>:</code> 后的部分指定，默认 <code>draw_resource</code>）</li>
            <li><b>资源消耗</b> <b>↓</b> = 模拟期间消耗的 <code>total_consumed[resource_id]</code></li>
            <li><b>目标卡出卡效率</b> = &Sigma; min(抽到数<sub>i</sub>, 需求量<sub>i</sub>) / 资源消耗量。分母取 <code>total_consumed[resource_id]</code></li>
            <li><b>每目标卡资源消耗</b> <b>↓</b> = 资源消耗量 / &Sigma; min(抽到数<sub>i</sub>, 需求量<sub>i</sub>)（与出卡效率互为倒数，分母为0时返回NaN）</li>
            <li><b>抽数转化效率</b> = (角色/武器池实际抽数 &times; 每抽成本) / 资源消耗量。<b>固定使用 <code>draw_resource</code>，不参与多资源类型展开。</b>原因：分子（实际抽数 × 每抽成本）和分母（资源消耗）处于同一资源体系（抽卡资源），衡量的是抽卡资源体系内部的转化效率；兑换货币有独立的获取/消耗路径，不存在「抽数」与「兑换货币消耗」之间的转化关系，公式本身对兑换货币无意义。</li>
            <li><b>额外目标卡</b> = &Sigma; max(抽到数<sub>i</sub> - 需求量<sub>i</sub>, 0)</li>
        </ul>
        <p><b>⚠ 语义警示</b>：「目标卡出卡效率」和「每目标卡资源消耗」使用 <code>exchange_currency</code>（兑换货币）时的解释力取决于兑换货币是否用于获取目标卡。若兑换货币仅用于兑换非目标卡，则这两个指标的分母（兑换货币消耗量）与分子（目标卡获得量）不在同一因果链上，指标数值可能不反映实际出卡效率。建议仅在兑换池产出目标卡时使用兑换货币维度的这两个指标。</p>

        <h5>抽卡过程类</h5>
        <ul>
            <li><b>非保底抽卡数</b> = 总抽数 - 保底触发次数</li>
            <li><b>保底抽卡数</b> = 保底触发次数</li>
            <li><b>目标卡出数</b> = &Sigma; 抽到数<sub>i</sub>（不按需求量截断，含溢出）</li>
            <li><b>每池下池出卡率</b> = &Sigma;<sub>各池</sub> (池内目标卡抽到次数) / 有抽卡记录的池数</li>
        </ul>

        <h5>加权综合类</h5>
        <ul>
            <li><b>加权满意度</b> = &Sigma;<sub>i</sub> [ min(抽到<sub>i</sub>, 需求<sub>i</sub>) &times; 抽取意愿<sub>i</sub> - max(需求<sub>i</sub>-抽到<sub>i</sub>, 0) &times; 错失代价<sub>i</sub> ]</li>
            <li><b>总出卡价值</b> = &Sigma; (抽到数<sub>i</sub> &times; 出卡价值权重<sub>i</sub>)</li>
            <li><b>专武角色比</b> = 已获取专武数 / 已获取角色数（仅当对应角色至少持有1张时计入专武；需配置角色-武器对应表）</li>
        </ul>

        <h4>脆弱性分析</h4>
        <p>对每个池子，使用<b>局部逻辑回归</b>（纯 numpy 向量化闭式解，Silverman 自适应带宽）估计条件失败概率 P(失败 | 资源剩余)。当数据不足时，回退到<b>Nadaraya-Watson 高斯核平滑</b>。识别条件失败概率超过阈值的连续区间为"脆弱性区间"。支持 r_grid 边界自适应扩展和 LLR 边界偏差缓解。</p>

        <h4>过程分析</h4>
        <p>对每次模拟的每个池子推断事件类型（7种）：保底命中（pity_hit）、提前出货（early_hit）、未出（miss）、跳过（skip）、忽略（ignore）、兑换（exchange）、未兑换（no_exchange）。四种交叉统计：</p>
        <ul>
            <li><b>AA（事件模式）</b>：事件序列的联合分布，支持 raw/sequence/set/count_set/custom 五种模式</li>
            <li><b>BB（成败模式）</b>：池子成败序列的联合分布</li>
            <li><b>AB（事件→成败）</b>：给定事件模式下各池成败的条件概率</li>
            <li><b>BA（成败→事件）</b>：给定成败模式下事件发生的条件概率</li>
        </ul>

        <h4>Bootstrap 稳定性分析</h4>
        <p>对已有模拟结果做有放回重抽样（B=1000），估计统计量的抽样分布和置信区间，<b>零额外模拟成本</b>。支持四种方法：</p>
        <ul>
            <li><b>标准 Bootstrap</b>：百分位法，一阶准确 O(1/√n)</li>
            <li><b>BCa</b>：偏差校正加速 Bootstrap，二阶准确 O(1/n)，校正偏态</li>
            <li><b>m-out-of-n</b>：厚尾分布下的一致性改进</li>
            <li><b>参数 GPD Bootstrap</b>：尾部分位数的参数化方法，从拟合广义 Pareto 分布抽样</li>
        </ul>
        <p>自动厚尾检测（Hill 估计量）+ 总变差（TVD）衡量分布估计稳定性。</p>

        <h4>方案搜索</h4>
        <p>统一搜索引擎，两种起点 × 四种模式：</p>
        <ul>
            <li><b>起点选择</b>：完整时间线（从第一个池开始）或 退路点（从指定池开始，模拟已消耗部分资源）</li>
            <li><b>最少资源</b>：在成功率 ≥ 阈值约束下，二分搜索最小额外资源投入——先翻倍找上界（15次），再二分精确定位</li>
            <li><b>最多目标卡</b>：在固定资源预算下最大化目标卡数量——前进法（按 desire_weight 降序逐个添加，直到成功率低于阈值）或后退法（按 miss_cost_weight 升序逐个移除，直到成功率高于阈值）</li>
            <li><b>Pareto 权衡曲线</b>：枚举目标集大小，每步搜索满足阈值的最少资源，描绘资源投入与目标数量的权衡边界（贪心近似）</li>
        </ul>

        <h4>最差影响分析</h4>
        <p>基于条件资源分布（按成功/失败分组），计算失败组资源的 α 分位数（VaR），评估最差情况下剩余资源能支撑多少个后续池子。使用蒙特卡洛模拟估计连续通关池数的分布。</p>

        <h4>风险分析</h4>
        <ul>
            <li><b>VaR</b>（Value at Risk）：极端分位数（p &le; 0.1 或 p &ge; 0.9）使用<b>广义 Pareto 分布（GPD）外推</b>（Pickands-Balkema-de Haan 定理），非极端分位数使用经验分位数（线性插值）</li>
            <li><b>CVaR</b>（Conditional VaR / Expected Shortfall）：极端尾部（&alpha; &le; 0.1）使用 GPD 外推，非极端尾部使用经验尾部均值</li>
            <li><b>经验 CDF</b>：排序数组的二分搜索</li>
            <li><b>条件分布</b>：按阈值分组后的子分布，同样享受 EVT 精度提升</li>
        </ul>

        <h4>经验分布</h4>
        <p>分位数计算根据分位水平自动选择方法：非极端分位数（0.1 &lt; p &lt; 0.9）使用<b>线性插值法</b>；极端分位数（p &le; 0.1 或 p &ge; 0.9）使用<b>广义 Pareto 分布（GPD）外推</b>，基于 Pickands-Balkema-de Haan 定理（超额分布收敛到 GPD）。直方图分箱使用<b>IQR 自适应法</b>：当四分位距/全距 &lt; 0.05 时（集中分布），使用 50-200 个 bin；否则使用 30 个 bin。</p>

        <h4>EVT 尾部拟合</h4>
        <p>极端分位数的经验估计标准误高（5% 分位数标准误约为中心分位数的 28 倍）。EVT 尾部拟合通过以下方式改善精度：</p>
        <ul>
            <li><b>Peaks Over Threshold（POT）</b>：选取超过自适应阈值的超额值，拟合广义 Pareto 分布</li>
            <li><b>自适应阈值</b>：保证 100-500 个超额样本，样本量越大阈值越高（Coles 2001「阈值尽可能高」原则）</li>
            <li><b>上下尾统一处理</b>：上尾直接拟合标准 POT；下尾通过取负法（Y = -X）转换为右尾问题，统一公式消除歧义</li>
            <li><b>MLE 正则性检查</b>：拟合后检查形状参数 &xi;，&xi; &lt; -1 强制回退经验方法（Smith 1985）</li>
            <li><b>0 行 GUI 改动</b>：在 EmpiricalDistribution 核心层集成，所有面板自动受益</li>
        </ul>

        <h4>转移矩阵</h4>
        <p>计算相邻池子之间成功/失败状态的 2×2 转移概率矩阵，用于分析池间成败依赖关系。</p>
        """)
        layout.addWidget(browser)
        return widget
