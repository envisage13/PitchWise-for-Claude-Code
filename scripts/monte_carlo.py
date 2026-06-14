"""
蒙特卡洛锦标赛模拟器
基于当前积分榜 + 剩余赛程，模拟 N 次完整锦标赛，输出冠军概率和晋级概率。

用法:
  python scripts/monte_carlo.py --competition worldcup --runs 10000
  python scripts/monte_carlo.py -c worldcup -n 5000 --json
"""
import json
import math
import random
import argparse
from datetime import datetime
from collections import defaultdict

try:
    from scripts.match_data import get_data, COMPETITIONS
except ImportError:
    from match_data import get_data, COMPETITIONS


# ============ 2026 世界杯淘汰赛对阵表 ============
# Round of 32: 固定对阵 (group winners + best 3rd placers)
WC2026_R32_MAP = [
    # (match_slot, description)
    (1,  "1A vs 3CDEF"),    # Winner A vs 3rd C/D/E/F
    (2,  "1B vs 3ACDE"),    # Winner B vs 3rd A/C/D/E
    (3,  "1C vs 3ABDF"),    # etc.
    (4,  "1D vs 3BCEF"),
    (5,  "1E vs 3ABDF"),
    (6,  "1F vs 3ACDF"),
    (7,  "1G vs 3ABCE"),
    (8,  "1H vs 3BCDF"),
    (9,  "1I vs 3CEFH"),
    (10, "1J vs 3DFGI"),
    (11, "1K vs 3EGHJ"),
    (12, "1L vs 3FHIK"),
    (13, "2A vs 2B"),
    (14, "2C vs 2D"),
    (15, "2E vs 2F"),
    (16, "2G vs 2H"),
    (17, "2I vs 2J"),
    (18, "2K vs 2L"),
    (19, "2A vs 2L"),   # Placeholder - actual depends on 3rd-place allocation
    (20, "2B vs 2K"),
    (21, "2C vs 2J"),
    (22, "2D vs 2I"),
    (23, "2E vs 2H"),
    (24, "2F vs 2G"),
]

# Simplified: top-16 from groups → seeded bracket
# R32: group winners + runners-up + 8 best 3rd-place teams
# For simplicity, we use a seeded bracket structure


# ============ 核心模拟引擎 ============

def _poisson_score(home_lambda: float, away_lambda: float) -> tuple:
    """泊松分布模拟比分"""
    home_goals = 0
    away_goals = 0
    # Poisson via inverse transform
    for lam, is_home in [(home_lambda, True), (away_lambda, False)]:
        L = math.exp(-lam)
        p = 1.0
        k = 0
        while p > L:
            k += 1
            p *= random.random()
        goals = k - 1
        if is_home:
            home_goals = goals
        else:
            away_goals = goals
    return home_goals, away_goals


# 球队实力基准 (进攻指数, 防守指数)，基于 FIFA 排名 + 博彩市场
# 1.0=平均, 进攻越高越强, 防守越低越强(越低失球)
TEAM_BASELINE = {
    "Brazil": (2.0, 0.7), "Argentina": (1.9, 0.7), "France": (1.9, 0.8),
    "Spain": (1.8, 0.7), "England": (1.8, 0.8), "Germany": (1.7, 0.8),
    "Portugal": (1.7, 0.9), "Netherlands": (1.6, 0.9),
    "Belgium": (1.5, 0.9), "Croatia": (1.4, 1.0), "Uruguay": (1.5, 0.9),
    "Colombia": (1.4, 1.0), "Morocco": (1.2, 1.0), "Mexico": (1.3, 1.0),
    "USA": (1.3, 1.0), "Switzerland": (1.2, 1.0), "Austria": (1.2, 1.1),
    "Senegal": (1.2, 1.1), "Japan": (1.2, 1.1), "South Korea": (1.2, 1.1),
    "Iran": (1.1, 1.1), "Australia": (1.1, 1.2), "Sweden": (1.2, 1.1),
    "Poland": (1.1, 1.2), "Czech Republic": (1.1, 1.2), "Turkey": (1.2, 1.2),
    "Egypt": (1.1, 1.2), "Algeria": (1.1, 1.2), "Ghana": (1.1, 1.2),
    "Ivory Coast": (1.1, 1.2), "Tunisia": (1.0, 1.2), "Scotland": (1.1, 1.2),
    "Norway": (1.1, 1.2), "Canada": (1.1, 1.3), "Qatar": (1.0, 1.3),
    "Saudi Arabia": (1.0, 1.3), "Iraq": (0.9, 1.4), "Ecuador": (1.0, 1.3),
    "Paraguay": (1.0, 1.3), "South Africa": (0.9, 1.3),
    "Haiti": (0.7, 1.6), "Panama": (0.8, 1.5),
    "Cape Verde Islands": (0.7, 1.6), "Curaçao": (0.5, 2.0),
    "Bosnia & Herzegovina": (0.9, 1.4), "DR Congo": (0.8, 1.5),
    "Jordan": (0.7, 1.7), "Uzbekistan": (0.8, 1.5),
    "New Zealand": (0.7, 1.6),
}


def _team_strength(team: dict) -> tuple:
    """从基线数据 + 已赛结果估算球队攻击力/防守力"""
    team_name = team.get("team", "")
    played = max(team.get("played", 0), 0)
    gf = team.get("goals_for", 0)
    ga = team.get("goals_against", 0)

    # 基线
    base_gf, base_ga = TEAM_BASELINE.get(team_name, (1.0, 1.3))

    if played == 0:
        return base_gf, base_ga

    # 混合基线 + 实际数据（实际数据权重随场次增加）
    actual_weight = min(played / 5, 0.6)  # 最多 60% 权重给实际数据
    base_weight = 1.0 - actual_weight

    actual_gf = gf / played
    actual_ga = ga / played

    return (
        base_gf * base_weight + actual_gf * actual_weight,
        base_ga * base_weight + actual_ga * actual_weight,
    )


def _resolve_group_table(table: list) -> list:
    """按 积分→净胜球→进球→随机 排序"""
    table.sort(key=lambda t: (
        -t["points"],
        -(t["goals_for"] - t["goals_against"]),
        -t["goals_for"],
        random.random(),
    ))
    return table


def _pick_best_thirds(groups: dict) -> list:
    """从 12 个小组中选出 8 个成绩最好的第 3 名"""
    thirds = []
    for g_name, table in groups.items():
        if len(table) >= 3:
            third = table[2]
            thirds.append({
                "team": third["team"],
                "tla": third["tla"],
                "group": g_name,
                "points": third["points"],
                "gd": third["goals_for"] - third["goals_against"],
                "gf": third["goals_for"],
            })

    thirds.sort(key=lambda t: (-t["points"], -t["gd"], -t["gf"], random.random()))
    return thirds[:8]


def simulate_tournament(competition: str = "worldcup", data: dict = None) -> dict:
    """单次锦标赛模拟，返回冠军和各级晋级队伍"""
    if data is None:
        data = get_data(competition, force_refresh=True)

    cfg = COMPETITIONS[competition]
    is_tournament = cfg.get("is_tournament", True)
    if not is_tournament:
        return {"error": "仅支持锦标赛模式"}

    # 1. 从当前数据计算各队实力
    standings = data.get("standings", [])
    team_power = {}
    for g in standings:
        for t in g["table"]:
            gf_rate, ga_rate = _team_strength(t)
            team_power[t["team"]] = {
                "tla": t["tla"],
                "gf_rate": gf_rate,
                "ga_rate": ga_rate,
                "group": g["group"],
            }

    # 2. 模拟剩余小组赛
    groups = defaultdict(list)
    completed_matches = set()

    for m in data["matches"]:
        group = m.get("group", "")
        if not group:
            continue

        home = m["home_team"]
        away = m["away_team"]
        match_key = frozenset([home, away])

        # 初始化队伍
        for team in [home, away]:
            if team not in team_power:
                base_gf, base_ga = TEAM_BASELINE.get(team, (1.0, 1.3))
                team_power[team] = {
                    "tla": m.get(f"{'home' if team == home else 'away'}_tla", team[:3].upper()),
                    "gf_rate": base_gf,
                    "ga_rate": base_ga,
                    "group": group,
                }

        if m["home_score"] is not None and m["away_score"] is not None:
            # 已完赛，使用真实结果
            gs_h, gs_a = m["home_score"], m["away_score"]
            completed_matches.add(match_key)
        else:
            # 模拟
            h_power = team_power[home]
            a_power = team_power[away]

            # 进攻力 = 己方进攻 × 对方防守弱点
            home_lambda = h_power["gf_rate"] * a_power["ga_rate"] / 1.2
            away_lambda = a_power["gf_rate"] * h_power["ga_rate"] / 1.2

            # 主队优势 15%
            home_lambda *= 1.15

            gs_h, gs_a = _poisson_score(home_lambda, away_lambda)

        # 计分
        for group_name in [group]:
            g = groups[group_name]
            # 找到或创建队伍
            home_entry = None
            away_entry = None
            for entry in g:
                if entry["team"] == home:
                    home_entry = entry
                if entry["team"] == away:
                    away_entry = entry

            if home_entry is None:
                home_entry = {"team": home, "tla": team_power[home]["tla"],
                              "played": 0, "won": 0, "draw": 0, "lost": 0,
                              "goals_for": 0, "goals_against": 0, "points": 0}
                g.append(home_entry)
            if away_entry is None:
                away_entry = {"team": away, "tla": team_power[away]["tla"],
                              "played": 0, "won": 0, "draw": 0, "lost": 0,
                              "goals_for": 0, "goals_against": 0, "points": 0}
                g.append(away_entry)

            home_entry["played"] += 1
            away_entry["played"] += 1
            home_entry["goals_for"] += gs_h
            home_entry["goals_against"] += gs_a
            away_entry["goals_for"] += gs_a
            away_entry["goals_against"] += gs_h

            if gs_h > gs_a:
                home_entry["won"] += 1
                home_entry["points"] += 3
                away_entry["lost"] += 1
            elif gs_h < gs_a:
                away_entry["won"] += 1
                away_entry["points"] += 3
                home_entry["lost"] += 1
            else:
                home_entry["draw"] += 1
                home_entry["points"] += 1
                away_entry["draw"] += 1
                away_entry["points"] += 1

    # 3. 排序小组 + 选出晋级队伍
    for g_name in groups:
        _resolve_group_table(groups[g_name])

    winners = []
    runners_up = []
    for g_name in sorted(groups.keys()):
        table = groups[g_name]
        if len(table) >= 1:
            winners.append({"team": table[0]["team"], "tla": table[0]["tla"], "group": g_name})
        if len(table) >= 2:
            runners_up.append({"team": table[1]["team"], "tla": table[1]["tla"], "group": g_name})

    best_thirds = _pick_best_thirds(groups)

    # 4. 淘汰赛
    # 简化：32 支队伍随机种子对阵（实际有固定对阵表）
    knockout_teams = winners + runners_up + [
        {"team": t["team"], "tla": t["tla"], "group": t["group"]}
        for t in best_thirds
    ]
    random.shuffle(knockout_teams)

    # 保证 2 的幂
    while len(knockout_teams) & (len(knockout_teams) - 1) != 0:
        knockout_teams.pop()

    round_names = {
        32: "Round of 32", 16: "Round of 16", 8: "Quarter-finals",
        4: "Semi-finals", 2: "Final",
    }

    champion = None
    while len(knockout_teams) > 1:
        next_round = []
        for i in range(0, len(knockout_teams), 2):
            t1 = knockout_teams[i]
            t2 = knockout_teams[i + 1]

            p1 = team_power.get(t1["team"], {"gf_rate": 1.0, "ga_rate": 1.3})
            p2 = team_power.get(t2["team"], {"gf_rate": 1.0, "ga_rate": 1.3})

            # 淘汰赛无主队优势，中立场地
            lambda1 = p1["gf_rate"] * p2["ga_rate"] / 1.2
            lambda2 = p2["gf_rate"] * p1["ga_rate"] / 1.2

            gs1, gs2 = _poisson_score(lambda1, lambda2)

            # 平局 → 加时 → 点球（简化：50/50）
            if gs1 == gs2:
                if random.random() < 0.5:
                    gs1 += 1
                else:
                    gs2 += 1

            winner = t1 if gs1 > gs2 else t2
            next_round.append(winner)

            if len(knockout_teams) == 2:
                champion = winner

        knockout_teams = next_round

    return {
        "champion": champion,
        "winners": winners,
        "runners_up": runners_up,
        "groups": {g: [t["team"] for t in table] for g, table in groups.items()},
    }


# ============ 多次模拟 ============

def run_simulations(competition: str = "worldcup", n_runs: int = 10000) -> dict:
    """运行 N 次蒙特卡洛模拟，汇总概率"""
    print(f"  运行 {n_runs} 次蒙特卡洛模拟...")

    # 初始化计数器
    champ_count = defaultdict(int)
    winner_count = defaultdict(int)
    runnerup_count = defaultdict(int)
    round32_count = defaultdict(int)

    # 获取一次原始数据（用于球队实力基准）
    data = get_data(competition)

    for i in range(n_runs):
        result = simulate_tournament(competition, data)

        if result.get("champion"):
            champ = result["champion"]["team"]
            champ_count[champ] += 1

        for w in result.get("winners", []):
            winner_count[w["team"]] += 1
        for r in result.get("runners_up", []):
            runnerup_count[r["team"]] += 1

        # 每 1000 次报告进度
        if (i + 1) % 2000 == 0:
            print(f"    ...{i + 1}/{n_runs}")

    # 汇总排名
    teams_ranked = sorted(champ_count.items(), key=lambda x: -x[1])

    return {
        "competition": COMPETITIONS[competition]["name"],
        "n_runs": n_runs,
        "champion_odds": [
            {
                "team": team,
                "wins": wins,
                "probability": round(wins / n_runs * 100, 1),
            }
            for team, wins in teams_ranked[:20]
        ],
        "group_winner_pct": {
            team: round(cnt / n_runs * 100, 1)
            for team, cnt in sorted(winner_count.items(), key=lambda x: -x[1])[:20]
        },
        "advance_to_ko_pct": {
            team: round((winner_count.get(team, 0) + runnerup_count.get(team, 0)) / n_runs * 100, 1)
            for team in sorted(
                set(list(winner_count.keys()) + list(runnerup_count.keys())),
                key=lambda t: -(winner_count.get(t, 0) + runnerup_count.get(t, 0))
            )[:32]
        },
    }


# ============ CLI ============

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="蒙特卡洛锦标赛模拟器")
    parser.add_argument("-c", "--competition", default="worldcup", help="赛事代码")
    parser.add_argument("-n", "--runs", type=int, default=10000, help="模拟次数")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    results = run_simulations(args.competition, args.runs)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"\n  {results['competition']} 蒙特卡洛模拟 ({results['n_runs']:,} 次)")
        print(f"  {'─' * 40}")
        print(f"\n  === 夺冠概率 TOP 10 ===")
        for i, t in enumerate(results["champion_odds"][:10], 1):
            bar = "█" * max(1, int(t["probability"]))
            print(f"  {i:>2}. {t['team']:<20} {t['probability']:>5.1f}% {bar}")

        print(f"\n  === 小组头名概率 TOP 10 ===")
        for team, pct in list(results["group_winner_pct"].items())[:10]:
            print(f"  {team:<20} {pct:>5.1f}%")
