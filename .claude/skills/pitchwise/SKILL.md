---
name: pitchwise
description: >
  AI足球预测+竞彩投注策略。融合赔率+数据+战术+数学模型的完整分析系统。
  当用户提到预测、分析比赛、看赔率、怎么买、投注方案、串关、串子、能回本吗、
  世界杯、欧洲杯、英超、西甲、意甲、德甲、法甲、竞彩、体彩、比分预测、胜平负、
  买彩票时，都应该使用此skill。
  即使没有明确说"预测"，只要在讨论足球比赛的结果可能性、赔率分析、投注建议、
  预算分配、风险控制，也应该激活此skill。
---

# PitchWise — AI 足球预测 Skill

## 设计原则

```
┌──────────────────────────────────────────────┐
│  客观数据层（Python 计算，不允许编造）         │
│  ─────────────────────────────               │
│  赔率概率 · 泊松比分 · H2H统计 · 近期状态     │
│  预期进球 · Kelly价值 · 市场分歧 · 积分榜     │
├──────────────────────────────────────────────┤
│  战术分析层（LLM 推理，标注 [analyzed]）       │
│  ─────────────────────────────               │
│  阵型克制 · 关键对位 · 风格匹配               │
│  场地效应 · 出线形势 · 伤病影响               │
├──────────────────────────────────────────────┤
│  表达层（LLM，标注每一条数据的来源类型）        │
│  [computed] = Python 计算，不可伪造           │
│  [sourced]  = WebSearch，标注具体来源          │
│  [analyzed] = LLM 推理，允许发挥知识           │
└──────────────────────────────────────────────┘
```

**核心约束：数字必须来自脚本。战术可以推理。每一条信息标注来源类型。**

## 能力

一场足球比赛的完整预测，输出：**数学指标 + 战术分析 + 综合推荐**。

数据部分（`prediction_engine.py` 计算）：
- 赔率隐含概率、泊松比分分布、预期进球、进球区间概率
- 近期状态统计、H2H 统计模式、Kelly 价值检测

分析部分（LLM 推理）：
- 战术解读、关键对位、风险提示、综合推荐

## 适用赛事

| 赛事 | 代码 | 赔率源 | 数据源 | 情报 |
|------|------|--------|--------|------|
| 世界杯 2026 | worldcup | 500.com | OpenFootball | WebSearch |
| 欧洲杯 2024 | euro | 500.com | OpenFootball | WebSearch |
| 英超 2025/26 | PL | 500.com | Football-Data.co.uk | WebSearch |
| 西甲 2025/26 | PD | 500.com | Football-Data.co.uk | WebSearch |
| 意甲 2025/26 | SA | 500.com | Football-Data.co.uk | WebSearch |
| 德甲 2025/26 | BL1 | 500.com | Football-Data.co.uk | WebSearch |
| 法甲 2025/26 | FL1 | 500.com | Football-Data.co.uk | WebSearch |

> 联赛模式：Football-Data.co.uk 提供 Bet365/Betfair/Pinnacle 多家赔率 + 射门/角球/犯规数据，零 API Key，零限流。
> 杯赛模式：OpenFootball 提供进球者+分钟+半场比分，零 API Key。

## 资源

- `agents/odds-agent.md` —— 赔率采集（500.com）
- `agents/data-agent.md` —— 赛程/积分榜/比分（OpenFootball + Football-Data.co.uk）
- `agents/form-agent.md` —— 阵容/伤病/战术情报（WebSearch）
- `agents/h2h-agent.md` —— 历史交锋数据（WebSearch）
- `references/team-mapping.md` —— 中文↔英文↔TLA 队名映射
- `references/prompt-templates.md` —— 预测 prompt 模板

---

## 部署配置

### 1. Python 依赖

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

### 2. 环境变量

复制 `.env.example` 为 `.env`，按需填写：

```bash
DEEPSEEK_API_KEY=            # 可选，使用外部 LLM 时填写
FOOTBALL_DATA_KEY=           # 可选，增强实时数据
```

### 3. Sub-agent 权限（关键）

编辑 `~/.claude/settings.json`，在 `permissions.allow` 中添加 **PowerShell + WebSearch + WebFetch**：

```json
{
  "permissions": {
    "allow": [
      "PowerShell",
      "WebSearch",
      "WebFetch"
    ]
  }
}
```

> 项目级 `settings.local.json` 对 sub-agent 不生效。必须加在全局设置。

---

## 工作流

用户全程自然语言交互，不接触任何命令、脚本或代码。所有技术操作由 skill 在后台自动完成。

### Step 0 — 自动更新数据 + 核对时间（每次预测前强制执行）

**预测之前必须先同步最新数据并核对比赛时间。** 后台静默执行：

1. 获取当前北京时间（UTC+8）
2. 同步已完赛比分，更新预测命中记录
3. 刷新竞彩赔率（如缓存超过 6 小时）
4. 刷新积分榜和赛程（如缓存超过 5 分钟）

执行完成后告知用户：
```
数据已刷新 (14:32 BJT)
今日 4 场比赛: 2 场待开赛, 1 场进行中, 1 场已完赛
```

**时间敏感判断：**

| 比赛状态 | 距开赛 | 系统行为 |
|---------|--------|---------|
| 已完赛 | — | 展示结果，不提供预测 |
| 进行中 | 开赛后 | 列出比分，不提供新预测 |
| < 15 分钟 | 即将开赛 | 正常预测 + 标注"即将开赛，数据可能延迟" |
| 15 分钟 ~ 2 小时 | 临近 | 正常预测 |
| > 2 小时 | 充裕 | 正常预测 |

> 如果用户要求预测的比赛已经开赛或完赛，诚实告知，不编造"赛前预测"。

### Step 1 — 理解用户意图

用户用自然语言表达，系统自动识别赛事、队伍、赔率：

| 用户说法 | 系统识别 |
|---------|---------|
| "荷兰 vs 日本 这场怎么看" | 世界杯 F组，自动获取赔率 |
| "帮我看看今晚的比赛" | 列出今日赛程，让用户选 |
| "阿森纳能赢吗" | 英超，自动匹配对手 |
| "皇马 vs 巴萨" | 西甲，自动获取赔率 |
| "谁最可能夺冠" | 触发蒙特卡洛模拟 |
| "最近预测准不准" | 显示命中率统计 |
| "同步一下" | 赛后比分同步 |

信息不全时（缺失赔率、赛事），系统自动从数据源补全，不追问用户。

### Step 2 — 后台并行采集

系统自动启动 4 个后台 agent 并行获取数据。用户看到"正在收集数据..."，3-10 秒完成。

### Step 3 — 数学计算 + 战术分析

自动运行预测引擎计算客观指标（隐含概率、泊松比分、Kelly价值），同时 LLM 进行战术解读。两者整合。

### Step 4 — 输出报告

展示预测结果。每项标注来源：[computed] 数学计算 / [sourced] 网络搜索 / [analyzed] LLM推理。

### Step 5 — 自动保存

预测自动写入 `data/predictions.csv`（追加模式，不可修改）。无需用户操作。

### 特殊场景

| 用户说 | 系统做 |
|-------|--------|
| "统计" | 显示命中率、按结果分类准确率 |
| "历史" | 显示最近预测记录 |
| "同步" | 赛后比分同步 |
| "夺冠概率" | 蒙特卡洛 5000 次模拟 |
| "怎么买"/"投注方案" | 生成混合过关方案（SPF+总进球+半全场+比分） |
| "串关"/"来个串子"/"能过关吗" | SPF稳胆 2串1 / 多玩法混合串关 |
| "能回本吗"/"风险多大" | 展示盈亏情景分析 + 蒙特卡洛资金曲线 |

## 不存在这些命令

Agent 不得调用以下不存在的功能。如果用户要求，解释暂不支持：

| 幻觉命令 | 替代方案 |
|---------|---------|
| `~python scripts/train_model.py~` | 本 skill 不做 ML 模型训练，使用 Claude 推理 |
| `~python scripts/live_odds.py~` | 赔率来自 500.com 静态抓取，无实时推送 |
| `~python scripts/place_bet.py~` | 不支持下注，仅做分析预测 |
| `~python scripts/player_stats.py~` | 球员个人数据通过 WebSearch 获取 |
| `~python scripts/injury_report.py~` | 伤病信息包含在 form-agent 的 WebSearch 中 |
| `~/pitchwise train~` | 无训练命令，预测由 Claude 推理完成 |
| `~/pitchwise bet~` | 不支持投注，仅分析 |

---

## 限制

- 预测结果仅供娱乐参考，不构成投注建议
- 不承诺盈利，不使用"稳赚""必胜"等词语
- 赔率以中国竞彩官方为准，系统获取的数据可能存在延迟
- 所有"推荐""比分"均为赛前推断，标注为推断
- 用户需自行遵守当地法律法规
