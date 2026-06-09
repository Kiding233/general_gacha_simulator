# 蒙特卡洛策略价值分布比较：完整分析流程手册

> **适用场景**：基于蒙特卡洛模拟获得 $n$ 个策略的价值样本（实数，越高越好），需系统性比较策略表现，并给出统计严谨的排序或筛选建议。
> 
> **核心原则**：策略价值分布的比较是**偏序问题**，而非简单的标量排序。不存在脱离决策者风险偏好的"客观最优"策略。

---

## 目录

1. [第一层：探索性数据分析（EDA）](#第一层探索性数据分析eda)
2. [第二层：随机优势检验（Stochastic Dominance）](#第二层随机优势检验stochastic-dominance)
3. [第三层：风险度量与统计检验](#第三层风险度量与统计检验)
4. [第四层：帕累托前沿构造](#第四层帕累托前沿构造)
5. [第五层：决策者偏好注入与最终排序](#第五层决策者偏好注入与最终排序)
6. [第六层：敏感性分析与稳健性验证](#第六层敏感性分析与稳健性验证)
7. [附录：关键公式与实现细节](#附录关键公式与实现细节)
8. [参考文献](#参考文献)

---

## 第一层：探索性数据分析（EDA）

### 1.1 描述性统计量

对每个策略 $\pi_i$，基于蒙特卡洛样本 $\{v_i^{(k)}\}_{k=1}^m$ 计算：

| 统计量 | 公式 | 诊断价值 |
|--------|------|---------|
| **样本均值** | $\bar{v}_i = \frac{1}{m}\sum_{k=1}^m v_i^{(k)}$ | 一阶矩，长期平均表现 |
| **样本中位数** | $\tilde{v}_i = \text{median}(v_i^{(k)})$ | 典型表现，抗异常值 |
| **样本标准差** | $s_i = \sqrt{\frac{1}{m-1}\sum(v_i^{(k)} - \bar{v}_i)^2}$ | 波动率/总风险 |
| **样本偏度** | $\hat{\gamma}_{1,i}$ | 分布不对称性（右偏=彩票型） |
| **样本峰度** | $\hat{\gamma}_{2,i}$ | 尾部厚度（厚尾=极端风险） |
| **最小值 / 最大值** | $\min(v_i), \max(v_i)$ | 极端情景边界 |

**关键诊断**：若均值显著高于中位数（$\bar{v}_i \gg \tilde{v}_i$），提示**右偏分布**——策略可能具有"大概率平庸/亏损，小概率极高回报"的彩票特征，需警惕下行风险。

### 1.2 可视化诊断

#### (a) 经验累积分布函数（ECDF）叠加图

绘制所有策略的 ECDF：
$$\hat{F}_i(x) = \frac{1}{m}\sum_{k=1}^m \mathbf{1}(v_i^{(k)} \leq x)$$

**解读**：
- 若 $\hat{F}_i(x) \leq \hat{F}_j(x)$ 对所有 $x$ 成立，且至少一处严格不等，则 $\pi_i$ **一阶随机优势（FSD）**于 $\pi_j$。
- 若 ECDF 存在**交叉**，则两策略互不 FSD，进入帕累托前沿分析。

#### (b) 分位数-分位数图（Q-Q Plot）

对重点策略对绘制 Q-Q 图，检验分布形态差异。

#### (c) 箱线图 / 小提琴图

直观展示中位数、四分位距、异常值。

#### (d) CVaR 曲线图

对每个策略，计算不同置信水平下的 $CVaR_\alpha$，绘制曲线：
$$\text{横轴：}\alpha \in [0.01, 0.99], \quad \text{纵轴：}CVaR_\alpha$$

**解读**：若策略 A 的 CVaR 曲线**全面高于**策略 B，则 A 在所有下行风险水平下均更优。

---

## 第二层：随机优势检验（Stochastic Dominance）

### 2.1 理论框架

设策略 $A, B$ 的价值分布分别为 $F_A, F_B$。

| 层级 | 定义 | 经济学含义 | 效用函数类 |
|------|------|-----------|-----------|
| **FSD** | $F_A(x) \leq F_B(x), \forall x$ | 所有单调递增效用者偏好 A | $U' > 0$ |
| **SSD** | $\int_{-\infty}^x F_A(t)dt \leq \int_{-\infty}^x F_B(t)dt, \forall x$ | 所有风险厌恶者偏好 A | $U' > 0, U'' < 0$ |
| **TSD** | SSD + 三阶积分条件 | 考虑偏度（下行保护） | $U''' > 0$ |

**核心性质**：
- FSD $\Rightarrow$ SSD $\Rightarrow$ TSD
- FSD $\Rightarrow \mathbb{E}_A[V] \geq \mathbb{E}_B[V]$（均值高是 FSD 的必要条件，但非充分条件）
- **偏序性**：并非所有策略对都可比较（CDF 交叉时互不占优）

### 2.2 统计检验：Davidson-Duclos Bootstrap 方法

**文献**：Davidson & Duclos (2000), *Journal of Economic Dynamics and Control*。

**检验统计量**（以 SSD 为例）：

定义 $j$ 阶积分分布函数：
$$D_j(x) = F_A^{(j)}(x) - F_B^{(j)}(x)$$

其中：
- $j=1$：$F^{(1)}(x) = F(x)$（原始 CDF）
- $j=2$：$F^{(2)}(x) = \int_{-\infty}^x F(t)dt$
- $j=3$：$F^{(3)}(x) = \int_{-\infty}^x F^{(2)}(t)dt$

**原假设与备择假设**：
- $H_0$：$D_j(x) \leq 0$ 对所有 $x$ 成立（即 A 不占优 B）
- $H_1$：存在某 $x$ 使 $D_j(x) > 0$（A 占优 B）

**Bootstrap 步骤**：

1. 从原始样本中有放回地抽取 $B$ 组 bootstrap 样本（建议 $B = 1000 \sim 5000$）。
2. 对每组 bootstrap 样本，计算经验积分分布函数 $\hat{F}^{(j)*}_A(x)$ 和 $\hat{F}^{(j)*}_B(x)$。
3. 在预设的网格点 $\{x_1, \dots, x_G\}$（覆盖样本取值范围）上计算 $D_j^*(x_g)$。
4. 构建 $D_j(x)$ 的 bootstrap 置信区间。
5. 若下置信界在某点显著大于 0，则拒绝 $H_0$，认为 A 显著 $j$ 阶随机优势于 B。

**多重比较校正**：
由于需在多个网格点 $x_g$ 上同时检验，需控制族错误率（FWER）：
- **Bonferroni 校正**：$\alpha_{\text{point}} = \alpha_{\text{overall}} / G$
- **更优方法**：Bootstrap 联合置信带（基于极值统计量）

### 2.3 几乎随机优势（Almost Stochastic Dominance）

**文献**：Leshno & Levy (2002)。

当违反 FSD 的区域极小且幅度有限时，可定义 AFSD：

设 $S_1 = \{x : F_A(x) > F_B(x)\}$（违反 FSD 的区域），若：
$$\frac{\int_{S_1} [F_A(x) - F_B(x)] dx}{\int_{-\infty}^{\infty} |F_A(x) - F_B(x)| dx} < \varepsilon$$

（$\varepsilon$ 通常取 0.05 或 0.10），则称 A 几乎 FSD B。

**评价**：理论优美但实践中**主观性较强**（$\varepsilon$ 的选择缺乏统一标准）。推荐作为敏感性分析，而非主要决策依据。

---

## 第三层：风险度量与统计检验

### 3.1 经典风险度量

| 度量 | 定义 | 优点 | 缺点 |
|------|------|------|------|
| **VaR$_\alpha$** | $\inf\{x: F(x) \geq \alpha\}$ | 直观，分位数含义清晰 | 非凸，不满足次可加性 |
| **CVaR$_\alpha$ / ES** | $\mathbb{E}[V \mid V \leq VaR_\alpha]$ | 凸、单调、平移不变、正齐次 | 对分布左尾敏感，估计方差大 |
| **谱风险度量** | $\int_0^1 VaR_\tau \phi(\tau) d\tau$ | 最一般的一致性风险度量 | 需指定权重函数 $\phi$ |
| **熵风险度量** | $\frac{1}{\theta}\ln\mathbb{E}[e^{-\theta V}]$ | 考虑整个分布，与 CARA 效用对应 | 参数 $\theta$ 经济含义不直观 |

**CVaR 的蒙特卡洛估计**：
对样本排序 $v_{(1)} \leq v_{(2)} \leq \dots \leq v_{(m)}$，$\alpha m$ 为整数时：
$$\widehat{CVaR}_\alpha = -\frac{1}{\alpha m}\sum_{k=1}^{\alpha m} v_{(k)}$$

（注意符号：若 $V$ 为损失则取负，若 $V$ 为回报则直接取平均。）

### 3.2 分布整体比较检验

| 检验 | 原假设 | 适用场景 | 特点 |
|------|--------|---------|------|
| **Kolmogorov-Smirnov** | $F_A = F_B$ | 整体分布差异 | 对中心差异敏感，尾部不敏感 |
| **Anderson-Darling** | $F_A = F_B$ | 尾部差异 | 加权平方距离，尾部更敏感 |
| **Cramér-von Mises** | $F_A = F_B$ | 整体差异 | 介于 K-S 和 A-D 之间 |
| **Mann-Whitney U** | 位置偏移 | 中位数差异 | 非参数，对异常值稳健 |
| **Welch's t-test** | $\mu_A = \mu_B$ | 均值差异 | 不要求等方差 |

**多重比较校正**（当 $n > 2$ 时）：
- **Holm-Bonferroni**：逐步校正，控制 FWER
- **Benjamini-Hochberg**：控制 FDR，适合探索性分析
- **Nemenyi 检验**：基于 Friedman 检验的事后多重比较

### 3.3 分布型强化学习视角

若策略价值分布可通过分布型 RL 直接建模（而非蒙特卡洛采样），则比较更为精确：

| 方法 | 输出 | 对策略比较的支持 |
|------|------|----------------|
| **C51** | 离散概率质量函数 | 直接计算任意分位点 |
| **QR-DQN** | 分位数函数 | 均匀分位点，支持 VaR/CVaR |
| **IQN** | 隐式分位数网络 | 任意输入分位点，灵活计算谱风险度量 |
| **FQN** | 完整 CDF | 直接比较 CDF 曲线 |

---

## 第四层：帕累托前沿构造

### 4.1 核心问题

随机优势是**偏序关系**（非完全序），因此大量策略对**不可比较**。帕累托前沿的作用是保留"没有任何其他策略严格更优"的策略子集。

### 4.2 非支配集定义

策略 $\pi_i$ 属于 **SSD 帕累托前沿** $\mathcal{P}_{SSD}$，当且仅当：
$$\nexists \pi_j \in \Pi, j \neq i: \quad F_j \succ_{SSD} F_i$$

即：**没有任何其他策略在二阶随机优势意义上严格优于它。**

### 4.3 均值高但不占优的策略在前沿中的角色

**典型情形**：
- 策略 A：均值高，但左尾厚（偶尔灾难性亏损）
- 策略 B：均值略低，但左尾薄（稳健）

**分析**：
- A 不 SSD B：因为 A 的累积积分在左尾区域大于 B（下行风险更差）
- B 不 SSD A：因为 B 的均值更低，若 B SSD A 则必有 $\mathbb{E}_B \geq \mathbb{E}_A$，矛盾

**结论**：A 和 B **同时属于**帕累托前沿。A 凭借期望收益优势，B 凭借风险保护优势。

### 4.4 前沿构造算法

**输入**：$n$ 个策略，每个策略 $m$ 个蒙特卡洛样本。

**步骤**：

1. **两两 SSD 检验**：对每对 $(i, j)$，使用 Davidson-Duclos Bootstrap 检验判断 $F_j \succ_{SSD} F_i$ 是否统计显著（水平 $\alpha = 0.05$）。
2. **支配关系矩阵**：构建 $n \times n$ 矩阵 $D$，其中 $D_{ji} = 1$ 表示 $\pi_j$ 显著 SSD 占优 $\pi_i$。
3. **非支配筛选**：$\mathcal{P} = \{\pi_i \mid \sum_{j \neq i} D_{ji} = 0\}$。

**时间复杂度**：$O(n^2 \cdot B \cdot G \cdot m \log m)$，其中 $B$ 为 bootstrap 次数，$G$ 为网格点数。

**统计稳健性**：若优势在 95% 置信水平下不显著（p值 > 0.05），保守地保留两者。

### 4.5 前沿可视化

- **均值-CVaR 平面**：横轴为 $CVaR_{0.1}$（或 $-\sigma$），纵轴为均值。前沿策略构成**东北边界**。
- **ECDF 叠加图**：前沿内所有策略的 ECDF 曲线，直观展示交叉区域。
- **CVaR-$\alpha$ 曲线图**：展示各前沿策略在不同置信水平下的条件风险价值。

---

## 第五层：决策者偏好注入与最终排序

帕累托前沿回答的是"哪些策略不坏"，而非"哪个策略最好"。要回答后者，必须引入**决策者的风险偏好**。

### 5.1 确定性等价（Certainty Equivalent）方法

**最严谨的方法**。给定效用函数 $U(x)$，计算：
$$CE_i = U^{-1}\left( \frac{1}{m}\sum_{k=1}^m U(v_i^{(k)}) \right)$$

$CE_i$ 表示：决策者愿意以多少**确定性的回报**来交换策略 $\pi_i$ 的随机回报。

#### 常用效用函数族

| 类型 | 公式 | 参数 | 经济含义 |
|------|------|------|---------|
| **CARA** | $U(x) = -\frac{1}{a}e^{-ax}$ | $a > 0$（绝对风险厌恶系数） | 风险态度与财富水平无关 |
| **CRRA** | $U(x) = \frac{x^{1-\gamma}}{1-\gamma}$ | $\gamma > 0$（相对风险厌恶系数） | 风险态度与财富比例相关 |
| **对数** | $U(x) = \ln(x)$ | — | $\gamma = 1$ 的 CRRA 特例 |
| **指数-对数混合** | 分段定义 | — | Friedman-Savage 双凹效用（既买保险又买彩票） |

#### 敏感性分析

对一系列风险厌恶系数 $a \in [a_{\min}, a_{\max}]$（如 $[10^{-4}, 10]$），计算所有前沿策略的 $CE_i(a)$，绘制**偏好曲线**。

**关键输出**：
- 若两条曲线在 $a^*$ 处交叉，则：
  - $a < a^*$（低风险厌恶）：选均值高的策略
  - $a > a^*$（高风险厌恶）：选下行保护好的策略
- $a^*$ 称为**无差异点（Indifference Point）**，明确回答"对什么样的决策者，哪个策略更优"。

### 5.2 谱风险度量排序

选择风险厌恶权重函数 $\phi(\tau)$，计算：
$$\rho_i = \int_0^1 \widehat{CVaR}_\tau(F_i) \phi(\tau) d\tau$$

常用权重函数：
- **指数衰减**：$\phi(\tau) \propto e^{-\gamma \tau}$，$\gamma$ 越大越关注左尾
- **阈值型**：$\phi(\tau) = \mathbf{1}(\tau \leq \alpha)/\alpha$，退化为 $CVaR_\alpha$
- **乐观-悲观**：$\phi(\tau) = \delta(\tau - \alpha)$，退化为 $VaR_\alpha$

直接按 $\rho_i$ 对前沿策略排序。

### 5.3 均值-风险标量化

将双目标显式建模为：
$$\text{得分}_i = \mathbb{E}[V_i] - \lambda \cdot \text{Risk}(V_i)$$

其中 Risk 可选择：
- 方差（Markowitz 经典框架）
- 下半方差（只惩罚下行波动）
- $CVaR_\alpha$（现代风险管理首选）

**操作**：对一系列 $\lambda \in [\lambda_{\min}, \lambda_{\max}]$，计算得分并排序。绘制**排序随风险厌恶参数变化图**。

### 5.4 决策语境约束

| 语境 | 推荐选择 | 理由 |
|------|---------|------|
| **高频重复决策**（如算法交易） | 倾向均值高的策略 | 大数定律生效，长期平均趋近期望 |
| **一次性高风险决策**（如航天、医疗） | 强烈倾向稳健策略 | 灾难约束（Dybvig 约束）优先于期望收益 |
| **存在破产阈值** | 排除左尾穿过阈值的策略 | 生存约束不可违反 |
| **委托-代理问题**（基金经理排名） | 取决于考核指标 | 若考核年度收益则激进策略占优；若考核最大回撤则稳健策略占优 |

---

## 第六层：敏感性分析与稳健性验证

### 6.1 Bootstrap 置信区间

对所有关键统计量（均值、CVaR、CE）构建 Bootstrap 置信区间：

1. 从原始样本中有放回抽取 $B$ 组 bootstrap 样本。
2. 对每组计算目标统计量。
3. 取 $B$ 组统计量的 $(\alpha/2, 1-\alpha/2)$ 分位数作为置信区间。

**解读**：若两策略的 95% 置信区间重叠，则差异统计不显著。

### 6.2 样本量敏感性

- 对 $m' = m/2, m/4, m/8$ 重复分析，检查前沿是否稳定。
- 若前沿随样本量剧烈变化，说明蒙特卡洛样本不足，需增加模拟次数。

### 6.3 风险度量敏感性

- 改变 CVaR 置信水平：$\alpha \in \{0.01, 0.05, 0.10, 0.25, 0.50\}$
- 改变效用函数参数：$a$ 或 $\gamma$ 变化一个数量级
- 检查排序是否发生**翻转（Reversal）**

**稳健性标准**：若排序在合理参数范围内稳定，则结论可信；若频繁翻转，则两策略实质等价，选择应基于非统计因素（如实施成本、可解释性）。

### 6.4 异常值与分布假设

- **Winsorization**：对极端样本进行缩尾处理（如 1% 和 99% 分位数截断），检查结论是否改变。
- **非参数 vs 参数**：比较非参数（经验分布）与参数假设（如正态、对数正态拟合）的结果差异。

---

## 附录：关键公式与实现细节

### A.1 经验积分分布函数（SSD 检验用）

对有序样本 $v_{(1)} \leq v_{(2)} \leq \dots \leq v_{(m)}$：

$$\hat{F}^{(2)}(x) = \frac{1}{m}\sum_{k=1}^m (x - v_{(k)})_+$$

其中 $(\cdot)_+ = \max(\cdot, 0)$。

### A.2 CVaR 的平滑估计

当 $\alpha m$ 非整数时，使用线性插值：

设 $k = \lfloor \alpha m \rfloor$，$\delta = \alpha m - k$，则：
$$\widehat{CVaR}_\alpha = -\frac{1}{\alpha m}\left(\sum_{i=1}^k v_{(i)} + \delta \cdot v_{(k+1)}\right)$$

### A.3 CARA 确定性等价的数值稳定性

当 $a$ 较大或样本值分散时，$e^{-av}$ 可能数值溢出/下溢。使用**对数空间计算**：

$$CE = -\frac{1}{a}\left(\ln\sum_{k=1}^m e^{-av^{(k)}} - \ln m\right)$$

或采用 **log-sum-exp 技巧**：
$$\ln\sum e^{x_k} = x_{\max} + \ln\sum e^{x_k - x_{\max}}$$

### A.4 多重比较校正的 Holm 步骤

对 $L$ 个假设检验，按 p 值从小到大排序 $p_{(1)} \leq p_{(2)} \leq \dots \leq p_{(L)}$：

找到最小的 $j$ 使得 $p_{(j)} > \alpha / (L - j + 1)$，则拒绝所有 $i < j$ 的假设。

---

## 参考文献

1. **Hadar, J., & Russell, W. R.** (1969). Rules for ordering uncertain prospects. *American Economic Review*, 59(1), 25-34.
2. **Hanoch, G., & Levy, H.** (1969). The efficiency analysis of choices involving risk. *Review of Economic Studies*, 36(3), 335-346.
3. **Rothschild, M., & Stiglitz, J. E.** (1970). Increasing risk: I. A definition. *Journal of Economic Theory*, 2(3), 225-243.
4. **Davidson, R., & Duclos, J. Y.** (2000). Statistical inference for stochastic dominance and for the measurement of poverty and inequality. *Econometrica*, 68(6), 1435-1464.
5. **Leshno, M., & Levy, H.** (2002). Preferred by "all" and preferred by "most" decision makers: Almost stochastic dominance. *Journal of Economic Theory*, 107(1), 89-96.
6. **Rockafellar, R. T., & Uryasev, S.** (2000). Optimization of conditional value-at-risk. *Journal of Risk*, 2(3), 21-41.
7. **Rockafellar, R. T., & Uryasev, S.** (2002). Conditional value-at-risk for general loss distributions. *Journal of Banking & Finance*, 26(7), 1443-1471.
8. **Acerbi, C., & Tasche, D.** (2002). On the coherence of expected shortfall. *Journal of Banking & Finance*, 26(7), 1487-1503.
9. **Bellemare, M. G., Dabney, W., & Munos, R.** (2017). A distributional perspective on reinforcement learning. *ICML*.
10. **Dabney, W., Ostrovski, G., Silver, D., & Munos, R.** (2018). Implicit quantile networks for distributional reinforcement learning. *ICML*.
11. **Tamar, A., Glassner, Y., & Mannor, S.** (2015). Policy gradients with variance related risk criteria. *ICML*.
12. **Chow, Y., Tamar, A., Mannor, S., & Pavone, M.** (2015). Risk-sensitive and robust decision-making: a CVaR optimization approach. *NIPS*.
13. **Eftimov, T., Korošec, P., & Seljak, B. K.** (2017). A novel approach to statistical comparison of meta-heuristic stochastic optimization algorithms using deep statistics. *Information Sciences*.
14. **Demšar, J.** (2006). Statistical comparisons of classifiers over multiple data sets. *Journal of Machine Learning Research*, 7, 1-30.
15. **Levy, H.** (2015). *Stochastic Dominance: Investment Decision Making under Uncertainty* (3rd ed.). Springer.
16. **Friedman, M., & Savage, L. J.** (1948). The utility analysis of choices involving risk. *Journal of Political Economy*, 56(4), 279-304.

---

> **最后提醒**：策略价值分布的比较没有"一键最优"的银弹。随机优势提供客观筛选，帕累托前沿保留值得考虑的策略，但最终选择必须回到决策者的风险偏好、约束条件与决策语境。报告结论时，请明确说明："在风险厌恶系数 $a < a^*$ 时，策略 A 更优；反之策略 B 更优"，而非简单的"A 优于 B"。
