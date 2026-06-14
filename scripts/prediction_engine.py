"""
预测引擎 — 纯数据与数学模型驱动，不做主观推断

基于真实数据计算:
  1. 赔率隐含概率（多家博彩公司平均）
  2. 泊松分布比分概率
  3. 预期进球（基于历史攻防数据）
  4. H2H 统计模式
  5. 近期状态量化
  6. 价值投注检测（Kelly）
  7. 市场 vs 数据分歧检测

用法:
  from scripts.prediction_engine import analyze_match
  result = analyze_match("worldcup", "Netherlands", "Japan", home_odds, draw_odds, away_odds)
"""
import json
import math
import os
from collections import defaultdict
from datetime import datetime
from typing import Optional, Any


# ============ 配置 ============

BOOKMAKERS = ["bet365", "betfair", "pinnacle"]  # 用于市场平均的博彩公司


# ============ 核心计算 ============

def implied_probability(home_odds: float, draw_odds: float, away_odds: float) -> dict:
    """从赔率计算市场隐含概率（去除抽水）"""
    raw_h = 1.0 / home_odds
    raw_d = 1.0 / draw_odds
    raw_a = 1.0 / away_odds
    total = raw_h + raw_d + raw_a

    return {
        "home": round(raw_h / total * 100, 1),
        "draw": round(raw_d / total * 100, 1),
        "away": round(raw_a / total * 100, 1),
        "overround": round((total - 1.0) * 100, 1),  # 庄家抽水率
    }


def expected_goals(home_stats: dict, away_stats: dict) -> dict:
    """基于攻防数据计算预期进球（泊松 lambda）"""
    # 主场进攻力 × 客场防守弱点 / 联赛平均
    home_attack = home_stats.get("goals_for_avg", 1.4)
    home_defense = home_stats.get("goals_against_avg", 1.4)
    away_attack = away_stats.get("goals_for_avg", 1.2)
    away_defense = away_stats.get("goals_against_avg", 1.2)

    league_avg = 1.35  # 足球比赛场均进球基准

    home_xg = (home_attack / league_avg) * (away_defense / league_avg) * league_avg
    away_xg = (away_attack / league_avg) * (home_defense / league_avg) * league_avg

    # 主场优势 ~15%
    home_xg *= 1.15

    return {
        "home_xg": round(home_xg, 2),
        "away_xg": round(away_xg, 2),
        "total_xg": round(home_xg + away_xg, 2),
    }


def poisson_probability(home_lambda: float, away_lambda: float, max_goals: int = 6) -> dict:
    """泊松分布计算各比分概率"""
    # 预计算泊松概率
    home_probs = [_poisson_pmf(i, home_lambda) for i in range(max_goals + 1)]
    away_probs = [_poisson_pmf(i, away_lambda) for i in range(max_goals + 1)]

    scores = []
    home_total = away_total = draw_total = 0

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = home_probs[h] * away_probs[a]
            scores.append({
                "home": h, "away": a,
                "probability": round(p * 100, 2),
            })
            if h > a:
                home_total += p
            elif a > h:
                away_total += p
            else:
                draw_total += p

    # 排序
    scores.sort(key=lambda s: -s["probability"])

    # 进球区间概率
    def goals_in_range(lo, hi):
        return sum(
            p for s in scores
            if lo <= s["home"] + s["away"] <= hi
            for p in [s["probability"] / 100]
        )

    return {
        "result_probability": {
            "home": round(home_total * 100, 1),
            "draw": round(draw_total * 100, 1),
            "away": round(away_total * 100, 1),
        },
        "top_scores": scores[:8],
        "goal_range": {
            "0-1": round(goals_in_range(0, 1) * 100, 1),
            "2-3": round(goals_in_range(2, 3) * 100, 1),
            "4+": round(goals_in_range(4, 99) * 100, 1),
        },
        "most_likely": scores[0] if scores else None,
    }


def _poisson_pmf(k: int, lam: float) -> float:
    """泊松概率质量函数"""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


# ============ 球队统计提取 ============

def extract_team_stats(match_data: dict, team_name: str, lookback: int = 10) -> dict:
    """从比赛数据中提取球队近期统计"""
    matches = match_data.get("matches", [])

    recent = []
    for m in matches:
        if m.get("home_team") != team_name and m.get("away_team") != team_name:
            continue
        if m.get("status") not in ("FINISHED", "FINISHED_ET", "FINISHED_PK"):
            continue
        if m.get("home_score") is None:
            continue
        recent.append(m)

    recent = recent[-lookback:]

    if not recent:
        return {"goals_for_avg": 1.3, "goals_against_avg": 1.3, "played": 0,
                "wins": 0, "draws": 0, "losses": 0, "form": ""}

    gf = ga = wins = draws = losses = 0
    form_chars = []

    for m in recent:
        is_home = m["home_team"] == team_name
        gf += m["home_score"] if is_home else m["away_score"]
        ga += m["away_score"] if is_home else m["home_score"]

        if m["home_score"] == m["away_score"]:
            draws += 1
            form_chars.append("D")
        elif (is_home and m["home_score"] > m["away_score"]) or \
             (not is_home and m["away_score"] > m["home_score"]):
            wins += 1
            form_chars.append("W")
        else:
            losses += 1
            form_chars.append("L")

    played = len(recent)

    return {
        "played": played,
        "goals_for_avg": round(gf / played, 2),
        "goals_against_avg": round(ga / played, 2),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": round(wins / played * 100, 1),
        "form": "".join(form_chars),  # e.g., "WWDWL"
        "form_pts": wins * 3 + draws,  # 近 N 场积分
    }


def extract_h2h_stats(matches: list, team1: str, team2: str, max_matches: int = 10) -> dict:
    """从历史交锋提取统计模式"""
    h2h = []
    for m in matches:
        if m["home_team"] == team1 and m["away_team"] == team2:
            h2h.append({"home": True, **m})
        elif m["home_team"] == team2 and m["away_team"] == team1:
            h2h.append({"home": False, **m})

    h2h = h2h[-max_matches:]

    if not h2h:
        return {"matches": 0}

    t1_wins = t2_wins = draws = 0
    t1_goals = t2_goals = 0
    over25 = 0
    btts = 0  # both teams to score

    for m in h2h:
        is_t1_home = m["home_team"] == team1
        hs = m["home_score"] or 0
        aws = m["away_score"] or 0

        if is_t1_home:
            t1_goals += hs
            t2_goals += aws
            if hs > aws:
                t1_wins += 1
            elif aws > hs:
                t2_wins += 1
            else:
                draws += 1
        else:
            t1_goals += aws
            t2_goals += hs
            if aws > hs:
                t1_wins += 1
            elif hs > aws:
                t2_wins += 1
            else:
                draws += 1

        if hs + aws > 2.5:
            over25 += 1
        if hs > 0 and aws > 0:
            btts += 1

    n = len(h2h)

    return {
        "matches": n,
        "t1_wins": t1_wins,
        "t2_wins": t2_wins,
        "draws": draws,
        "t1_goals": t1_goals,
        "t2_goals": t2_goals,
        "avg_goals": round((t1_goals + t2_goals) / n, 1),
        "over25_rate": round(over25 / n * 100, 1),
        "btts_rate": round(btts / n * 100, 1),
        "t1_win_rate": round(t1_wins / n * 100, 1),
    }


# ============ 价值检测 ============

def kelly_stake(ai_prob: float, odds: float, fraction: float = 0.25) -> dict:
    """Kelly 准则计算建议投注比例"""
    b = odds - 1.0  # 净赔率
    if b <= 0:
        return {"value": False, "edge": 0, "full_kelly": 0, "fractional_kelly": 0}

    q = 1.0 - ai_prob
    f_star = (b * ai_prob - q) / b

    return {
        "value": f_star > 0,
        "edge": round((ai_prob * odds - 1) * 100, 1),  # 期望收益率
        "full_kelly": round(max(0, f_star) * 100, 1),
        "fractional_kelly": round(max(0, f_star * fraction) * 100, 1),
    }


def market_vs_data(market_prob: float, data_prob: float, threshold: float = 5.0) -> str:
    """市场与数据的分歧判断"""
    diff = data_prob - market_prob
    if abs(diff) < threshold:
        return "一致"
    elif diff > 0:
        return "数据高于市场"  # 潜在价值投注
    else:
        return "市场高于数据"  # 市场过度乐观


# ============ 综合分析 ============

def analyze_match(
    competition: str,
    home_team: str,
    away_team: str,
    home_odds: float,
    draw_odds: float,
    away_odds: float,
    match_data: dict = None,
) -> dict:
    """
    完整数学分析。

    返回所有客观指标，不做主观推断。
    大模型可在此基础上进行战术解读和叙事表达。
    """
    result = {
        "match": f"{home_team} vs {away_team}",
        "competition": competition,
        "timestamp": datetime.now().isoformat(),
    }

    # 1. 赔率隐含概率
    imp = implied_probability(home_odds, draw_odds, away_odds)
    result["market"] = {
        "odds": {"home": home_odds, "draw": draw_odds, "away": away_odds},
        "implied_probability": imp,
    }

    # 2. 球队统计
    home_stats = away_stats = {"goals_for_avg": 1.3, "goals_against_avg": 1.3,
                                "played": 0, "wins": 0, "draws": 0, "losses": 0,
                                "win_rate": 0, "form": "", "form_pts": 0}
    h2h_stats = {"matches": 0}

    if match_data:
        home_stats = extract_team_stats(match_data, home_team)
        away_stats = extract_team_stats(match_data, away_team)
        h2h_stats = extract_h2h_stats(match_data["matches"], home_team, away_team)

    result["home_stats"] = home_stats
    result["away_stats"] = away_stats

    # 3. 预期进球 + 泊松比分
    xg = expected_goals(home_stats, away_stats)
    result["expected_goals"] = xg

    poisson = poisson_probability(xg["home_xg"], xg["away_xg"])
    result["poisson"] = poisson
    result["most_likely_score"] = poisson["most_likely"]

    # 4. 市场 vs 数据分歧
    if poisson["result_probability"]["home"] > 0:
        result["market_vs_model"] = {
            "home": market_vs_data(imp["home"], poisson["result_probability"]["home"]),
            "draw": market_vs_data(imp["draw"], poisson["result_probability"]["draw"]),
            "away": market_vs_data(imp["away"], poisson["result_probability"]["away"]),
        }

    # 5. H2H 统计
    result["h2h"] = h2h_stats

    # 6. 价值检测（对概率最高的结果计算 Kelly）
    best_outcome = max(imp.items(), key=lambda x: x[1])
    best_odds = {"home": home_odds, "draw": draw_odds, "away": away_odds}[best_outcome[0]]
    model_prob = poisson["result_probability"][best_outcome[0]]
    result["value_check"] = kelly_stake(model_prob / 100, best_odds)

    return result


# ============ 格式化输出 ============

def format_analysis(result: dict) -> str:
    """将分析结果格式化为可读文本，供大模型消费"""
    m = result["market"]
    imp = m["implied_probability"]
    poisson = result["poisson"]
    xg = result["expected_goals"]
    hs = result["home_stats"]
    aws = result["away_stats"]
    h2h = result["h2h"]

    lines = [
        "## 客观数据与数学模型分析",
        "",
        "> 以下所有数字均由脚本计算，非大模型推断。大模型仅负责在此数据基础上进行战术解读。",
        "",
        f"### 市场数据（来源：500.com）",
        f"- 赔率: 主胜 {m['odds']['home']} / 平局 {m['odds']['draw']} / 客胜 {m['odds']['away']}",
        f"- 市场隐含概率: 主胜 {imp['home']}% / 平局 {imp['draw']}% / 客胜 {imp['away']}%",
        f"- 庄家抽水率: {imp['overround']}%",
        "",
        f"### 预期进球（泊松模型）",
        f"- {result['match'].split(' vs ')[0]} 预期进球: {xg['home_xg']}",
        f"- {result['match'].split(' vs ')[1]} 预期进球: {xg['away_xg']}",
        f"- 合计预期进球: {xg['total_xg']}",
        "",
        f"### 泊松比分概率",
        f"| 比分 | 概率 |",
        f"|------|------|",
    ]

    for s in poisson["top_scores"][:5]:
        lines.append(f"| {s['home']}-{s['away']} | {s['probability']}% |")

    lines += [
        "",
        f"### 泊松结果概率",
        f"- 主胜: {poisson['result_probability']['home']}%",
        f"- 平局: {poisson['result_probability']['draw']}%",
        f"- 客胜: {poisson['result_probability']['away']}%",
        "",
        f"### 进球区间概率",
        f"- 0-1球: {poisson['goal_range']['0-1']}%",
        f"- 2-3球: {poisson['goal_range']['2-3']}%",
        f"- 4+球: {poisson['goal_range']['4+']}%",
        "",
        f"### 近期状态（近{hs['played']}场）",
        f"| 队伍 | 场 | 胜 | 平 | 负 | 场均进球 | 场均失球 | 状态 |",
        f"|------|----|----|----|----|---------|---------|------|",
        f"| 主队 | {hs['played']} | {hs['wins']} | {hs['draws']} | {hs['losses']} | {hs['goals_for_avg']} | {hs['goals_against_avg']} | {hs['form']} |",
        f"| 客队 | {aws['played']} | {aws['wins']} | {aws['draws']} | {aws['losses']} | {aws['goals_for_avg']} | {aws['goals_against_avg']} | {aws['form']} |",
    ]

    if h2h["matches"] > 0:
        lines += [
            "",
            f"### 历史交锋统计（近{h2h['matches']}场）",
            f"- {result['match'].split(' vs ')[0]} 胜: {h2h['t1_wins']} ({h2h['t1_win_rate']}%)",
            f"- {result['match'].split(' vs ')[1]} 胜: {h2h['t2_wins']}",
            f"- 平局: {h2h['draws']}",
            f"- 场均进球: {h2h['avg_goals']}",
            f"- 大球率(>2.5): {h2h['over25_rate']}%",
            f"- 双方进球率: {h2h['btts_rate']}%",
        ]

    vc = result["value_check"]
    lines += [
        "",
        f"### 价值检测",
        f"- Kelly 期望收益: {vc['edge']}%",
        f"- 1/4 Kelly 建议: {vc['fractional_kelly']}%" if vc["value"] else "- 无正期望值",
    ]

    if result.get("market_vs_model"):
        mvm = result["market_vs_model"]
        lines += [
            f"- 市场vs模型: 主胜({mvm['home']}) / 平局({mvm['draw']}) / 客胜({mvm['away']})",
        ]

    return "\n".join(lines)


# ============ CLI ============

# ============================================================
# V2 增强模型：Elo + 射门xG + 加权状态 + 集成融合
# ============================================================

def compute_elo(home_elo: float, away_elo: float, home_score: int, away_score: int,
                k: float = 32, home_advantage: float = 100) -> tuple:
    """Elo 评分更新"""
    elo_diff = home_elo - away_elo + home_advantage
    expected_home = 1.0 / (1.0 + 10 ** (-elo_diff / 400.0))

    if home_score > away_score:
        result_home = 1.0
    elif home_score < away_score:
        result_home = 0.0
    else:
        result_home = 0.5

    # 进球差加权 K
    goal_diff = abs(home_score - away_score)
    if goal_diff > 0:
        k_adj = k * (1.0 + min(goal_diff, 4) * 0.5)
    else:
        k_adj = k

    new_home = home_elo + k_adj * (result_home - expected_home)
    new_away = away_elo + k_adj * ((1.0 - result_home) - (1.0 - expected_home))

    return round(new_home, 1), round(new_away, 1)


def build_elo_ratings(completed_matches: list, base_elo: float = 1500) -> dict:
    """从已完赛数据构建 Elo 评分表"""
    elo = defaultdict(lambda: base_elo)
    for m in completed_matches:
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        hs = m.get("home_score")
        aws = m.get("away_score")
        if hs is None or aws is None:
            continue
        new_h, new_a = compute_elo(elo[home], elo[away], hs, aws)
        elo[home] = new_h
        elo[away] = new_a
    return dict(elo)


def extract_weighted_stats(matches: list, team_name: str, lookback: int = 15) -> dict:
    """加权近期统计——越近的比赛权重越高"""
    recent = []
    for m in matches:
        if m.get("status") not in ("FINISHED", "FINISHED_ET", "FINISHED_PK"):
            continue
        if m["home_team"] == team_name or m["away_team"] == team_name:
            hs = m.get("home_score")
            aws = m.get("away_score")
            if hs is None or aws is None:
                continue
            recent.append(m)

    recent = recent[-lookback:]
    if not recent:
        return {"goals_for_avg": 1.3, "goals_against_avg": 1.3,
                "played": 0, "form_pts": 0, "shots_for": 0, "shots_against": 0,
                "xg_for": 0, "xg_against": 0}

    n = len(recent)
    total_weight = 0
    w_gf = w_ga = w_shots_f = w_shots_a = w_shots_on_f = w_shots_on_a = 0
    form_pts = 0

    for i, m in enumerate(recent):
        weight = 0.5 + 0.5 * (i + 1) / n  # 0.5 → 1.0 线性

        is_home = m["home_team"] == team_name
        gf = m["home_score"] if is_home else m["away_score"]
        ga = m["away_score"] if is_home else m["home_score"]

        w_gf += gf * weight
        w_ga += ga * weight
        total_weight += weight

        # 射门数据（如有）
        sf = m.get("home_shots") if is_home else m.get("away_shots")
        sa = m.get("away_shots") if is_home else m.get("home_shots")
        if sf is not None:
            w_shots_f += sf * weight
        if sa is not None:
            w_shots_a += sa * weight

        sof = m.get("home_shots_on_target") if is_home else m.get("away_shots_on_target")
        soa = m.get("away_shots_on_target") if is_home else m.get("home_shots_on_target")
        if sof is not None:
            w_shots_on_f += sof * weight
        if soa is not None:
            w_shots_on_a += soa * weight

        if gf > ga:
            form_pts += 3 * weight
        elif gf == ga:
            form_pts += 1 * weight

    return {
        "played": n,
        "goals_for_avg": round(w_gf / total_weight, 2),
        "goals_against_avg": round(w_ga / total_weight, 2),
        "shots_for_avg": round(w_shots_f / total_weight, 1) if w_shots_f > 0 else None,
        "shots_against_avg": round(w_shots_a / total_weight, 1) if w_shots_a > 0 else None,
        "shots_on_target_for": round(w_shots_on_f / total_weight, 1) if w_shots_on_f > 0 else None,
        "shots_on_target_against": round(w_shots_on_a / total_weight, 1) if w_shots_on_a > 0 else None,
        "weighted_form": round(form_pts / total_weight, 1),
    }


def expected_goals_v2(home_stats: dict, away_stats: dict,
                      home_elo: float = 1500, away_elo: float = 1500) -> dict:
    """V2 预期进球——结合射门数据 + Elo"""
    league_avg = 1.35

    # 基础攻击/防守指数（优先用射门数据，退化为进球数据）
    h_attack = home_stats.get("shots_on_target_for") or home_stats.get("goals_for_avg", 1.3)
    h_defense = home_stats.get("shots_on_target_against") or home_stats.get("goals_against_avg", 1.3)
    a_attack = away_stats.get("shots_on_target_for") or away_stats.get("goals_for_avg", 1.2)
    a_defense = away_stats.get("shots_on_target_against") or away_stats.get("goals_against_avg", 1.2)

    # Elo 调整因子
    elo_diff = home_elo - away_elo + 100  # +100 = 主场优势
    elo_factor = 1.0 + (elo_diff / 400.0) * 0.15  # Elo 差 400 = 15% 调整

    home_xg = (h_attack / league_avg) * (a_defense / league_avg) * league_avg
    home_xg *= elo_factor
    away_xg = (a_attack / league_avg) * (h_defense / league_avg) * league_avg

    # 确保不低于最低值
    home_xg = max(home_xg, 0.4)
    away_xg = max(away_xg, 0.3)

    return {
        "home_xg": round(home_xg, 2),
        "away_xg": round(away_xg, 2),
        "total_xg": round(home_xg + away_xg, 2),
        "elo_diff": round(elo_diff, 0),
    }


def ensemble_probability(market_prob: dict, model_prob: dict, market_weight: float = 0.65) -> dict:
    """集成融合：市场与模型加权平均"""
    mw = market_weight
    pw = 1.0 - market_weight
    return {
        "home": round(market_prob["home"] * mw + model_prob["home"] * pw, 1),
        "draw": round(market_prob["draw"] * mw + model_prob["draw"] * pw, 1),
        "away": round(market_prob["away"] * mw + model_prob["away"] * pw, 1),
    }


def draw_adjustment(probs: dict, home_xg: float, away_xg: float, h2h_stats: dict) -> dict:
    """平局概率专项调整——市场低估平局，模型补回"""
    # 平局更可能发生在: xG 接近、双方防守强、H2H 平局率高
    xg_diff = abs(home_xg - away_xg)
    draw_boost = 0

    # 预期进球差小 → 平局概率高
    if xg_diff < 0.2:
        draw_boost += 3
    elif xg_diff < 0.5:
        draw_boost += 1

    # 总预期进球低 → 平局概率高（0-0, 1-1）
    total_xg = home_xg + away_xg
    if total_xg < 2.0:
        draw_boost += 2
    elif total_xg < 2.5:
        draw_boost += 1

    # H2H 平局率高 → 加分
    if h2h_stats.get("matches", 0) >= 3:
        draw_rate = h2h_stats.get("draws", 0) / h2h_stats["matches"]
        if draw_rate > 0.33:
            draw_boost += 2
        elif draw_rate > 0.2:
            draw_boost += 1

    adjusted = dict(probs)
    adjusted["draw"] = min(adjusted["draw"] + draw_boost, 45)
    # 减少的部分从主客概率中按比例扣
    excess = sum(adjusted.values()) - 100
    if excess > 0:
        ratio_h = adjusted["home"] / (adjusted["home"] + adjusted["away"]) if (adjusted["home"] + adjusted["away"]) > 0 else 0.5
        adjusted["home"] = round(adjusted["home"] - excess * ratio_h, 1)
        adjusted["away"] = round(adjusted["away"] - excess * (1 - ratio_h), 1)

    return adjusted


def analyze_match_v2(
    competition: str,
    home_team: str,
    away_team: str,
    home_odds: float,
    draw_odds: float,
    away_odds: float,
    match_data: dict = None,
    completed_for_elo: list = None,
    elo_ratings: dict = None,
) -> dict:
    """V2 综合预测——增强特征 + Elo + 集成融合"""
    result = {
        "match": f"{home_team} vs {away_team}",
        "version": "v2",
    }

    # 1. 市场
    imp = implied_probability(home_odds, draw_odds, away_odds)
    result["market"] = {"odds": {"home": home_odds, "draw": draw_odds, "away": away_odds},
                        "implied_probability": imp}

    # 2. 球队统计
    home_basic = away_basic = {"goals_for_avg": 1.3, "goals_against_avg": 1.3,
                                "played": 0, "form_pts": 0}
    home_weighted = away_weighted = {"goals_for_avg": 1.3, "goals_against_avg": 1.3,
                                      "played": 0, "form_pts": 0}
    h2h_stats = {"matches": 0}

    if match_data:
        matches = match_data.get("matches", [])
        home_basic = extract_team_stats(match_data, home_team)
        away_basic = extract_team_stats(match_data, away_team)
        home_weighted = extract_weighted_stats(matches, home_team)
        away_weighted = extract_weighted_stats(matches, away_team)
        h2h_stats = extract_h2h_stats(matches, home_team, away_team)

    result["home_stats"] = home_weighted
    result["away_stats"] = away_weighted

    # 3. Elo
    home_elo = (elo_ratings or {}).get(home_team, 1500)
    away_elo = (elo_ratings or {}).get(away_team, 1500)
    result["elo"] = {"home": home_elo, "away": away_elo, "diff": round(home_elo - away_elo, 0)}

    # 4. V2 预期进球（射门+Elo）
    xg = expected_goals_v2(home_weighted, away_weighted, home_elo, away_elo)
    result["expected_goals"] = xg

    # 5. 泊松
    poisson = poisson_probability(xg["home_xg"], xg["away_xg"])
    result["poisson_raw"] = poisson

    # 6. 集成融合（市场 65% + 模型 35%）
    ensemble = ensemble_probability(imp, poisson["result_probability"], market_weight=0.65)
    result["ensemble_raw"] = dict(ensemble)

    # 7. 平局调整
    adjusted = draw_adjustment(ensemble, xg["home_xg"], xg["away_xg"], h2h_stats)
    result["ensemble_adjusted"] = adjusted
    result["final_probability"] = adjusted

    # 8. 最佳选择
    best = max(adjusted, key=adjusted.get)
    result["recommendation"] = best
    result["confidence"] = adjusted[best]

    # 9. 价值检测
    best_odds = {"home": home_odds, "draw": draw_odds, "away": away_odds}[best]
    result["value_check"] = kelly_stake(adjusted[best] / 100, best_odds)

    # 10. H2H
    result["h2h"] = h2h_stats

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="数学预测引擎")
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--home_odds", type=float, required=True)
    parser.add_argument("--draw_odds", type=float, required=True)
    parser.add_argument("--away_odds", type=float, required=True)
    parser.add_argument("-c", "--competition", default="worldcup")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    # 尝试加载实际比赛数据
    data = None
    try:
        from scripts.match_data import get_data
        data = get_data(args.competition)
    except Exception:
        pass

    result = analyze_match(
        args.competition, args.home, args.away,
        args.home_odds, args.draw_odds, args.away_odds,
        data,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_analysis(result))
