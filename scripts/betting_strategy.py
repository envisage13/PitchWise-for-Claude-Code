"""
投注策略引擎 — 基于体彩规则 + Kelly准则 + 预算约束

输出: 100元/50注预算下的最优投注分配方案
"""
import json
from typing import Optional


# ============ 体彩规则常量 ============

PER_NOTE = 2        # 每注 2 元
DEFAULT_BUDGET = 100  # 默认 100 元
MAX_SINGLE_STAKE = 0.25  # 单场最大 25% 资金（Kelly 约束）


# ============ 标准比分赔率参考 ============
# 基于常见竞彩比分赔率范围（实际以 500.com 为准）
SCORE_ODDS_REFERENCE = {
    "1-0": 6.5, "2-0": 7.0, "2-1": 7.5, "3-0": 12.0, "3-1": 13.0, "3-2": 25.0,
    "0-0": 9.0, "1-1": 6.0, "2-2": 14.0, "3-3": 50.0,
    "0-1": 8.0, "0-2": 14.0, "1-2": 11.0, "0-3": 35.0, "1-3": 28.0, "2-3": 40.0,
}


# ============ 核心策略 ============

def allocate_budget(
    spf_probs: dict,          # {"home": 46.4, "draw": 26.6, "away": 27.0}
    spf_odds: dict,           # {"home": 1.86, "draw": 3.25, "away": 3.20}
    top_scores: list,         # [{"home":1,"away":1,"probability":12.2}, ...]
    score_odds: dict = None,  # 可选的实际比分赔率
    goal_range: dict = None,  # {"0-1": 25.1, "2-3": 46.6, "4+": 28.3}
    budget: int = DEFAULT_BUDGET,
    kelly_stake_pct: float = None,  # 1/4 Kelly 建议比例
) -> dict:
    """
    在 100元/50注 约束下，生成最优投注分配方案。

    策略逻辑:
      1. SPF 主投 (60-70%): 概率最高结果，Kelly 定投注量
      2. 比分博冷 (15-25%): 最可能比分 + 防守比分
      3. 对冲保护 (10-15%): 次优结果覆盖
    """
    notes = budget // PER_NOTE

    # 确定推荐结果
    best_outcome = max(spf_probs, key=spf_probs.get)
    outcome_names = {"home": "主胜", "draw": "平局", "away": "客胜"}

    # === 1. SPF 主投 (65%)===
    main_budget = int(budget * 0.65)
    main_odds = spf_odds[best_outcome]
    main_notes = main_budget // PER_NOTE

    # Kelly 约束：单场不超过总资金 25%
    max_main_budget = int(budget * MAX_SINGLE_STAKE)
    if main_budget > max_main_budget:
        main_budget = max_main_budget
        main_notes = main_budget // PER_NOTE

    main_return = main_notes * main_odds * PER_NOTE

    # === 2. 比分博冷 (20%)===
    score_budget = int(budget * 0.20)
    score_bets = []

    if top_scores:
        # 最可能比分
        best = top_scores[0]
        best_score_key = f"{best['home']}-{best['away']}"
        best_score_prob = best["probability"]
        best_score_odds_est = SCORE_ODDS_REFERENCE.get(best_score_key, 7.0)
        if score_odds and best_score_key in score_odds:
            best_score_odds_est = score_odds[best_score_key]

        half_score_budget = score_budget // 2
        half_score_notes = half_score_budget // PER_NOTE

        score_bets.append({
            "score": best_score_key,
            "prob": f"{best_score_prob}%",
            "odds_estimate": best_score_odds_est,
            "notes": half_score_notes,
            "amount": half_score_notes * PER_NOTE,
            "return_if_win": round(half_score_notes * best_score_odds_est * PER_NOTE),
            "reason": "最可能比分",
            "type": "primary",
        })

        # 第二可能比分（防守）
        if len(top_scores) >= 2:
            second = top_scores[1]
            second_key = f"{second['home']}-{second['away']}"
            second_odds_est = SCORE_ODDS_REFERENCE.get(second_key, 7.0)
            if score_odds and second_key in score_odds:
                second_odds_est = score_odds[second_key]

            score_bets.append({
                "score": second_key,
                "prob": f"{second['probability']}%",
                "odds_estimate": second_odds_est,
                "notes": half_score_notes,
                "amount": half_score_notes * PER_NOTE,
                "return_if_win": round(half_score_notes * second_odds_est * PER_NOTE),
                "reason": "次可能比分",
                "type": "hedge",
            })

    # === 3. 对冲保护 (15%)===
    hedge_budget = int(budget * 0.15)
    hedge_bets = []

    # 第二可能结果
    sorted_outcomes = sorted(spf_probs.items(), key=lambda x: -x[1])
    if len(sorted_outcomes) >= 2:
        second_outcome, second_prob = sorted_outcomes[1]
        if second_outcome != best_outcome and second_prob > 20:
            second_odds = spf_odds[second_outcome]
            hedge_notes = hedge_budget // PER_NOTE

            hedge_bets.append({
                "type": "spf_hedge",
                "outcome": outcome_names[second_outcome],
                "odds": second_odds,
                "prob": f"{second_prob}%",
                "notes": hedge_notes,
                "amount": hedge_notes * PER_NOTE,
                "return_if_win": round(hedge_notes * second_odds * PER_NOTE),
                "reason": "第二可能结果对冲",
            })

    # 平局保护（如果平局不是前二结果）
    if best_outcome != "draw" and (len(sorted_outcomes) < 3 or sorted_outcomes[1][0] != "draw"):
        draw_prob = spf_probs.get("draw", 0)
        if draw_prob > 18:
            draw_odds = spf_odds["draw"]
            draw_notes = max(1, hedge_budget // PER_NOTE // 2)
            hedge_bets.append({
                "type": "draw_protection",
                "outcome": "平局",
                "odds": draw_odds,
                "prob": f"{draw_prob}%",
                "notes": draw_notes,
                "amount": draw_notes * PER_NOTE,
                "return_if_win": round(draw_notes * draw_odds * PER_NOTE),
                "reason": "平局保护",
            })

    # === 汇总 ===
    total_spent = (
        main_notes * PER_NOTE
        + sum(b["amount"] for b in score_bets)
        + sum(b["amount"] for b in hedge_bets)
    )

    # 剩余零钱加回主投
    remaining = budget - total_spent
    if remaining >= PER_NOTE:
        extra_notes = remaining // PER_NOTE
        main_notes += extra_notes

    total_spent = (
        main_notes * PER_NOTE
        + sum(b["amount"] for b in score_bets)
        + sum(b["amount"] for b in hedge_bets)
    )
    remaining = budget - total_spent

    # 风险等级
    if spf_probs[best_outcome] > 50:
        risk_level = "低"
    elif spf_probs[best_outcome] > 38:
        risk_level = "中"
    else:
        risk_level = "高"

    return {
        "budget": budget,
        "notes_total": budget // PER_NOTE,
        "risk_level": risk_level,
        "recommendation": outcome_names.get(best_outcome, best_outcome),
        "recommendation_prob": f"{spf_probs[best_outcome]}%",
        "kelly_stake": f"{kelly_stake_pct}%" if kelly_stake_pct else None,
        "main_bet": {
            "type": "胜平负",
            "outcome": outcome_names.get(best_outcome, best_outcome),
            "odds": main_odds,
            "notes": main_notes,
            "amount": main_notes * PER_NOTE,
            "return_if_win": round(main_notes * main_odds * PER_NOTE),
            "allocation_pct": round(main_notes * PER_NOTE / budget * 100),
        },
        "score_bets": score_bets,
        "hedge_bets": hedge_bets,
        "total_spent": total_spent,
        "remaining": remaining,
        "scenarios": _compute_scenarios(best_outcome, spf_odds, spf_probs,
                                        main_notes, score_bets, hedge_bets, budget),
    }


def _compute_scenarios(best_outcome, spf_odds, spf_probs, main_notes, score_bets, hedge_bets, budget):
    """计算各情景下的回报"""
    best_odds = spf_odds[best_outcome]

    # 最佳情景：主投命中
    best_return = main_notes * best_odds * PER_NOTE
    best_profit = best_return - budget

    # 比分命中情景
    score_scenarios = []
    for sb in score_bets[:1]:
        score_scenarios.append({
            "name": f"比分 {sb['score']} 命中",
            "return": sb["return_if_win"],
            "profit": sb["return_if_win"] - budget,
        })

    # 对冲命中情景
    hedge_scenarios = []
    for hb in hedge_bets[:1]:
        hedge_scenarios.append({
            "name": f"{hb.get('outcome', '对冲')} 命中",
            "return": hb["return_if_win"],
            "profit": hb["return_if_win"] - budget,
        })

    # 全错情景
    worst_profit = -budget

    return {
        "best": {"name": "主投命中", "return": round(best_return), "profit": round(best_profit)},
        "score": score_scenarios,
        "hedge": hedge_scenarios,
        "worst": {"name": "全部未中", "return": 0, "profit": worst_profit},
    }


# ============ 串关策略 ============

def parlay_strategy(matches: list, budget: int = DEFAULT_BUDGET) -> dict:
    """
    串关组合推荐。
    matches: [{"home":"","away":"","pick":"home","odds":1.86,"prob":46.4}, ...]

    策略: 2串1 稳胆 + 3串1 博高赔
    """
    notes = budget // PER_NOTE
    parlays = []

    if len(matches) < 2:
        return {"error": "至少需要 2 场比赛"}

    # 排序：概率高优先
    sorted_m = sorted(matches, key=lambda m: -m.get("prob", 0))

    # === 2串1 稳胆 (70%) ===
    safe_2 = sorted_m[:2]
    safe_odds = round(safe_2[0]["odds"] * safe_2[1]["odds"], 2)
    safe_prob = round(safe_2[0]["prob"] * safe_2[1]["prob"] / 100, 1)
    safe_notes = int(notes * 0.7)

    parlays.append({
        "type": "2串1 稳胆",
        "matches": [f"{m['home']}vs{m['away']} {m['pick']}@{m['odds']}" for m in safe_2],
        "combined_odds": safe_odds,
        "combined_prob": f"{safe_prob}%",
        "notes": safe_notes,
        "amount": safe_notes * PER_NOTE,
        "return_if_win": round(safe_notes * safe_odds * PER_NOTE),
        "risk": "低",
    })

    # === 3串1 博高赔 (30%) ===
    if len(sorted_m) >= 3:
        value_3 = [m for m in sorted_m if m.get("prob", 0) < 45 and m["odds"] > 2.0][:3]
        if len(value_3) >= 2:
            value_odds = 1
            value_prob = 100
            for m in value_3:
                value_odds *= m["odds"]
                value_prob *= m["prob"] / 100
            value_odds = round(value_odds, 2)
            value_prob = round(value_prob, 1)
            value_notes = int(notes * 0.3)

            parlays.append({
                "type": "串关 博高赔",
                "matches": [f"{m['home']}vs{m['away']} {m['pick']}@{m['odds']}" for m in value_3],
                "combined_odds": value_odds,
                "combined_prob": f"{value_prob}%",
                "notes": value_notes,
                "amount": value_notes * PER_NOTE,
                "return_if_win": round(value_notes * value_odds * PER_NOTE),
                "risk": "高",
            })

    total_spent = sum(p["amount"] for p in parlays)

    return {
        "budget": budget,
        "parlays": parlays,
        "total_spent": total_spent,
        "max_return": max((p["return_if_win"] for p in parlays), default=0),
        "note": "串关风险高于单关。稳胆为主，博高赔为辅。",
    }


# ============ CLI ============

if __name__ == "__main__":
    # 示例: 荷兰 vs 日本
    result = allocate_budget(
        spf_probs={"home": 46.4, "draw": 26.6, "away": 27.0},
        spf_odds={"home": 1.86, "draw": 3.25, "away": 3.20},
        top_scores=[
            {"home": 1, "away": 1, "probability": 12.2},
            {"home": 1, "away": 0, "probability": 9.8},
            {"home": 2, "away": 1, "probability": 8.8},
        ],
        kelly_stake_pct=3.5,
    )

    print("=== 投注策略方案 ===")
    print(f"推荐: {result['recommendation']} ({result['recommendation_prob']})")
    print(f"风险等级: {result['risk_level']}")
    print(f"Kelly建议: {result['kelly_stake']}")
    print()

    print(f"--- 主投 (胜平负) ---")
    m = result["main_bet"]
    print(f"  {m['outcome']} @{m['odds']} | {m['notes']}注 {m['amount']}元 | "
          f"中奖回报 {m['return_if_win']}元")

    if result["score_bets"]:
        print(f"\n--- 比分博冷 ---")
        for s in result["score_bets"]:
            print(f"  {s['score']} @~{s['odds_estimate']} | {s['notes']}注 {s['amount']}元 | "
                  f"{s['reason']}")

    if result["hedge_bets"]:
        print(f"\n--- 对冲保护 ---")
        for h in result["hedge_bets"]:
            print(f"  {h['outcome']} @{h['odds']} | {h['notes']}注 {h['amount']}元 | "
                  f"{h['reason']}")

    print(f"\n总投入: {result['total_spent']}元 | 剩余: {result['remaining']}元")
    print(f"\n情景分析:")
    for name, s in result["scenarios"].items():
        if isinstance(s, dict):
            print(f"  {s['name']}: 回报 {s['return']}元 (盈亏 {s['profit']:+d}元)")
        elif isinstance(s, list):
            for si in s:
                print(f"  {si['name']}: 回报 {si['return']}元 (盈亏 {si['profit']:+d}元)")
