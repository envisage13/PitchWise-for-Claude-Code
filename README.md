# PitchWise for Claude Code

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)

**Claude Code Skill** — 融合竞彩赔率 + 实时数据 + 赛前情报 + 历史交锋的 AI 足球预测系统。支持世界杯、欧洲杯、五大联赛。

---

## 快速开始

### 前置条件

- Claude Code 已安装
- Python 3.10+
- 全局权限配置（见下）

### 安装

```bash
git clone https://github.com/YOUR_USERNAME/PitchWise.git
cd PitchWise
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env         # 按需编辑
```

### 权限配置

编辑 `~/.claude/settings.json`：

```json
{
  "permissions": {
    "allow": ["PowerShell", "WebSearch", "WebFetch"]
  }
}
```

### 使用

在 Claude Code 中，全程自然语言：

```
荷兰 vs 日本 这场怎么看           → 自动获赔率+数据+预测
帮我看看今晚有什么比赛            → 列出赛程
最近预测准不准                    → 命中率统计
谁最可能夺冠                      → 蒙特卡洛模拟
同步一下                          → 赛后自动匹配比分
```

无需输入任何命令、路径或参数。系统自动完成数据更新、赔率获取和数学计算。

---

## 架构

```
用户: "预测荷兰 vs 日本"
         │
    SKILL.md 解析 → 并行启动 4 个 sub-agent
         │
    ┌────┴────┬────────┬────────┐
    ▼         ▼        ▼        ▼
 odds-agent  data    form     h2h
 500.com   OpenFtbl  WebSrch  WebSrch
    │         │        │        │
    ▼         ▼        ▼        ▼
   赔率    积分榜   阵容伤病  历史交锋
    │         │        │        │
    └────┬────┴────────┴────────┘
         ▼
   predictor-agent (Claude 推理)
         │
         ▼
   结构化预测 + 隐含概率对比
```

## 数据源

| 数据 | 来源 | 特点 |
|------|------|------|
| 竞彩赔率 | 500.com | 中文队名，GB2312 |
| 杯赛比分/进球者 | OpenFootball | 零 Key, CC0 |
| 联赛比分/赔率/数据 | Football-Data.co.uk | 零 Key, Bet365+Pinnacle+射门 |
| 赛前情报 | WebSearch | Claude 原生 |
| 历史交锋 | WebSearch | Claude 原生 |

## 支持赛事

| 赛事 | 代码 | 数据年份 |
|------|------|---------|
| 世界杯 | worldcup | 2026 |
| 欧洲杯 | euro | 2024 |
| 英超 | PL | 2025/26 |
| 西甲 | PD | 2025/26 |
| 意甲 | SA | 2025/26 |
| 德甲 | BL1 | 2025/26 |
| 法甲 | FL1 | 2025/26 |

## 项目结构

```
.claude/skills/matchpredict/     # Skill 定义
├── SKILL.md                     # 主入口
├── agents/                      # 5 个 sub-agent
└── references/                  # 模板 + 映射表
scripts/                         # Python 工具脚本
├── match_data.py               # 统一数据接口
├── odds500_scraper.py          # 500.com 赔率
├── storage.py                  # CSV 存储
└── ...
data/                            # 历史数据 + 缓存
```

## 许可

MIT License.

## 免责声明

预测结果仅供娱乐参考，不构成投注建议。请遵守当地法律法规。
