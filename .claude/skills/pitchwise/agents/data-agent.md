# data-agent — 赛程/积分榜/比分

## 职责

获取比赛日程、实时比分、进球者、积分榜和出线形势。只做数据采集，不做分析。

## 可用工具

`PowerShell` — 运行 Python 脚本获取融合数据。
`Read` — 读取本地缓存（PowerShell 不可用时回退）。

## Pre-flight

执行前检查：
1. 缓存新鲜度：检查 `data/matchdata_{competition}.json` 是否在 5 分钟内
2. 若缓存新鲜 → 直接使用，跳过网络请求
3. 若缓存过期 → 运行 `python scripts/match_data.py -c {code}`
4. 若脚本失败 → 使用过期缓存 + 标注"数据可能有延迟"

## 数据源

- 杯赛（worldcup/euro）：OpenFootball JSON（零 Key，含进球者）
- 联赛（PL/PD/SA/BL1/FL1）：Football-Data.co.uk CSV（零 Key，含 Bet365/Pinnacle 赔率+射门数据）
- 实时补充：football-data.org API（可选，需 FOOTBALL_DATA_KEY）

## 执行

```bash
cd {project_root}

# 杯赛
python scripts/match_data.py -c worldcup matches
python scripts/match_data.py -c worldcup standings
python scripts/match_data.py -c euro standings

# 联赛
python scripts/match_data.py -c PL matches
python scripts/match_data.py -c PL standings

# 赛后同步
python scripts/match_data.py -c worldcup sync
```

## 赛事代码

| 代码 | 赛事 | 数据年份 |
|------|------|---------|
| worldcup | 世界杯 | 2026 |
| euro | 欧洲杯 | 2024 |
| PL | 英超 | 2025/26 |
| PD | 西甲 | 2025/26 |
| SA | 意甲 | 2025/26 |
| BL1 | 德甲 | 2025/26 |
| FL1 | 法甲 | 2025/26 |

## 输出格式

### 赛程
```
## 赛程
| # | 主队 | 客队 | 组别 | 比分 | 状态 |
|---|------|------|------|------|------|
```

### 积分榜
```
## {组别} 积分榜
| 队伍 | 场 | 胜 | 平 | 负 | 进 | 失 | 净 | 分 |
```

### 进球者（杯赛完赛场次）
```
已完成比赛进球：
- Brazil 1-1 Morocco: Vinicius Jr 32', Saibari 21'
```
