"""
投资组合优化器 — 多注Kelly + 风险价值 + 夏普率 + 有效前沿 + 破产概率

模型:
  1. 多注 Kelly 优化 — 同时投注的最优资金分配
  2. Risk of Ruin — 给定策略的破产概率
  3. VaR/CVaR — 尾部风险度量
  4. Sharpe Ratio — 风险调整收益
  5. 蒙特卡洛回撤路径 — 最坏情景模拟
  6. 连续亏损保护 — 动态降档
"""
import math
import random
from typing import Optional


# ============ 多注 Kelly 优化 ============

def multi_kelly(bets: list[dict], bankroll: float = 100.0,
                max_single: float = 0.25, fraction: float = 0.25) -> dict:
    """
    多注同时投注的 Kelly 最优分配。

    bets: [{"label":"主胜","odds":1.86,"prob":0.464}, ...]
    bankroll: 总资金
    fraction: Kelly 分数 (0.25 = 1/4 Kelly)

    算法：迭代求解——每注独立 Kelly 后按比例缩放至总资金约束。
    """
    if not bets:
        return {"allocations": [], "total_stake": 0, "expected_growth": 0}

    # Step 1: 独立 Kelly
    allocations = []
    total_raw = 0

    for b in bets:
        odds = b["odds"]
        prob = b["prob"]
        b_param = odds - 1.0  # 净赔率
        q = 1.0 - prob

        if b_param <= 0 or prob <= 0:
            f_star = 0
        else:
            f_star = (b_param * prob - q) / b_param  # Full Kelly

        f_frac = max(0, f_star * fraction)  # Fractional Kelly
        allocations.append({
            "label": b["label"],
            "odds": odds,
            "prob": prob,
            "edge": round(prob * odds - 1, 3),  # 期望收益率
            "full_kelly_pct": round(f_star * 100, 1),
            "fractional_kelly_pct": round(f_frac * 100, 1),
        })
        total_raw += f_frac

    # Step 2: 如果总和超限，等比缩放
    if total_raw > max_single * len(bets):
        scale = (max_single * len(bets)) / total_raw
    elif total_raw > 1.0:
        scale = 1.0 / total_raw
    else:
        scale = 1.0

    total_stake = 0
    for a in allocations:
        stake_pct = a["fractional_kelly_pct"] / 100 * scale
        a["stake_pct"] = round(stake_pct * 100, 1)
        a["stake_amount"] = round(stake_pct * bankroll, 1)
        total_stake += stake_pct

    # Step 3: 组合期望增长率 (EG)
    eg = 0
    for a in allocations:
        if a["stake_pct"] > 0:
            f = a["stake_pct"] / 100
            p = a["prob"]
            b = a["odds"] - 1
            eg += p * math.log(1 + f * b) + (1 - p) * math.log(1 - f)

    return {
        "bankroll": bankroll,
        "kelly_fraction": fraction,
        "allocations": allocations,
        "total_stake_pct": round(total_stake * 100, 1),
        "expected_growth": round(eg, 4),
        "expected_growth_pct": round((math.exp(eg) - 1) * 100, 2),
    }


# ============ 风险指标 ============

def risk_metrics(bets: list[dict], n_sim: int = 10000) -> dict:
    """
    蒙特卡洛模拟计算风险指标。

    返回: VaR(95%), CVaR(95%), 最大回撤, 夏普率, 破产概率
    """
    if not bets:
        return {}

    returns = []
    drawdowns = []
    peak = 100.0
    bankroll = 100.0

    for _ in range(n_sim):
        pnl = 0
        for b in bets:
            stake = b.get("stake_amount", 2) / 100  # 转为比例
            if stake <= 0:
                continue
            if random.random() < b["prob"]:
                pnl += stake * (b["odds"] - 1)
            else:
                pnl -= stake
        returns.append(pnl)
        bankroll += pnl
        if bankroll > peak:
            peak = bankroll
        dd = (peak - bankroll) / peak * 100
        drawdowns.append(max(0, dd))

    returns.sort()

    # VaR(95%): 第 5 百分位的损失
    var_95 = -returns[int(n_sim * 0.05)]

    # CVaR(95%): 尾部平均损失
    tail = returns[:int(n_sim * 0.05)]
    cvar_95 = -sum(tail) / len(tail) if tail else 0

    # 夏普率
    mean_ret = sum(returns) / n_sim
    std_ret = (sum((r - mean_ret) ** 2 for r in returns) / n_sim) ** 0.5
    sharpe = mean_ret / std_ret if std_ret > 0 else 0

    # 破产概率
    ruin_prob = sum(1 for r in returns if r <= -50) / n_sim * 100  # 损失 >50% 视为破产

    # 最大回撤
    max_dd = max(drawdowns)

    return {
        "var_95pct": round(var_95, 1),  # "95%概率单轮损失不超过X%"
        "cvar_95pct": round(cvar_95, 1),  # "尾部平均损失X%"
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd, 1),
        "ruin_probability": round(ruin_prob, 1),
        "expected_return": round(mean_ret, 2),
        "volatility": round(std_ret, 2),
    }


# ============ 连续亏损保护 ============

def drawdown_protection(kelly_fraction: float, consecutive_losses: int) -> dict:
    """
    连续亏损后自动降档。

    默认 1/4 Kelly。连续亏损后:
      1 次 → 不变 (正常波动)
      2 次 → 1/4→1/6
      3 次 → 1/8
      4+ 次 → 1/16 (接近停止)
    """
    if consecutive_losses <= 1:
        new_fraction = kelly_fraction
        level = "正常"
    elif consecutive_losses == 2:
        new_fraction = kelly_fraction * 0.67
        level = "谨慎"
    elif consecutive_losses == 3:
        new_fraction = kelly_fraction * 0.5
        level = "防御"
    else:
        new_fraction = kelly_fraction * 0.25
        level = "极简"

    return {
        "consecutive_losses": consecutive_losses,
        "original_kelly": f"1/{int(1/kelly_fraction) if kelly_fraction > 0 else '∞'}",
        "adjusted_kelly": f"1/{int(1/new_fraction) if new_fraction > 0 else '∞'}",
        "level": level,
        "suggested_stake_pct": round(new_fraction * 100, 1),
    }


# ============ 有效前沿 ============

def efficient_frontier(bets: list[dict], points: int = 20) -> list:
    """
    生成有效前沿：不同 Kelly 分数下的风险-收益组合。

    对 fraction 从 0 到 1.0，计算期望收益和波动率。
    """
    frontier = []
    for frac in [f / 100 for f in range(5, 105, 5)]:
        result = multi_kelly(bets, fraction=frac)
        eg = result["expected_growth"]
        if eg > -1:
            # 用蒙特卡洛估计波动率（快速版）
            returns = []
            for _ in range(500):
                pnl = 0
                for b in bets:
                    a = next((x for x in result["allocations"] if x["label"] == b["label"]), None)
                    if a is None:
                        continue
                    stake = a.get("stake_pct", 0) / 100
                    if stake <= 0:
                        continue
                    if random.random() < b["prob"]:
                        pnl += stake * (b["odds"] - 1)
                    else:
                        pnl -= stake
                returns.append(pnl)

            mean_r = sum(returns) / len(returns)
            std_r = (sum((r - mean_r) ** 2 for r in returns) / len(returns)) ** 0.5

            frontier.append({
                "kelly_fraction": round(frac, 2),
                "expected_return_pct": round(mean_r * 100, 1),
                "volatility_pct": round(std_r * 100, 1),
                "sharpe": round(mean_r / std_r, 2) if std_r > 0 else 0,
                "total_stake_pct": result["total_stake_pct"],
            })

    return frontier


# ============ 资金曲线模拟 ============

def simulate_bankroll(bets: list[dict], bankroll: float = 100,
                      rounds: int = 50, n_paths: int = 100) -> dict:
    """
    模拟 N 条资金曲线路径，展示最佳/中位/最坏情景。
    """
    paths = []

    for _ in range(n_paths):
        br = bankroll
        history = [br]
        for _ in range(rounds):
            pnl = 0
            for b in bets:
                a = next((x for x in b.get("allocations", [])
                          if x.get("label") == b.get("label", "")), None)
                stake = (a.get("stake_amount", 2) if a else 2) / bankroll * br
                stake = max(0, min(stake, br * 0.25))  # 单注上限 25%
                if random.random() < b.get("prob", 0.3):
                    pnl += stake * (b.get("odds", 2.0) - 1)
                else:
                    pnl -= stake
            br += pnl
            br = max(br, 1)  # 不低于 1 元
            history.append(round(br, 1))
        paths.append(history)

    # 每条路径的最终资金
    finals = [p[-1] for p in paths]
    finals.sort()

    idx_best = finals.index(max(finals))
    idx_median = len(finals) // 2
    idx_worst = finals.index(min(finals))

    return {
        "rounds": rounds,
        "paths": n_paths,
        "best_path": {"final": round(finals[-1], 1), "path": paths[idx_best]},
        "median_path": {"final": round(finals[idx_median], 1), "path": paths[idx_median]},
        "worst_path": {"final": round(finals[0], 1), "path": paths[idx_worst]},
        "prob_profit": round(sum(1 for f in finals if f > bankroll) / n_paths * 100, 1),
        "prob_ruin": round(sum(1 for f in finals if f < bankroll * 0.5) / n_paths * 100, 1),
        "median_return": round(finals[idx_median] - bankroll, 1),
    }


# ============ 综合报告 ============

def full_portfolio_analysis(bets: list[dict], bankroll: float = 100,
                            history_losses: int = 0) -> dict:
    """一站式投资组合分析"""
    # 多注 Kelly
    kelly = multi_kelly(bets, bankroll)

    # 风险指标
    risk = risk_metrics(bets)

    # 回撤保护
    protection = drawdown_protection(0.25, history_losses)

    # 有效前沿
    frontier = efficient_frontier(bets)

    # 资金曲线
    sim = simulate_bankroll(bets, bankroll)

    return {
        "kelly_allocation": kelly,
        "risk_metrics": risk,
        "drawdown_protection": protection,
        "efficient_frontier": frontier[:10],  # 前 10 个点
        "bankroll_simulation": sim,
    }


# ============ CLI ============

if __name__ == "__main__":
    # 示例: 荷兰 vs 日本 + 德国 vs 库拉索 两场同时投注
    bets = [
        {"label": "荷兰主胜", "odds": 1.86, "prob": 0.464},
        {"label": "德国主胜", "odds": 1.01, "prob": 0.85},
        {"label": "日本客胜", "odds": 3.20, "prob": 0.27},
    ]

    print("=" * 60)
    print("  投资组合优化报告")
    print("=" * 60)

    analysis = full_portfolio_analysis(bets)

    # Kelly
    k = analysis["kelly_allocation"]
    print(f"\n── 多注 Kelly 分配 (1/{int(1/k['kelly_fraction'])} Kelly, 资金 {k['bankroll']}元) ──")
    print(f"  期望增长率: {k['expected_growth_pct']}%/轮 | 总投注比例: {k['total_stake_pct']}%")
    for a in k["allocations"]:
        flag = "✓" if a["edge"] > 0 else "✗"
        print(f"  {flag} {a['label']:<12} @{a['odds']:<5} P={a['prob']:.1%}  "
              f"Kelly建议 {a['stake_pct']}% ({a['stake_amount']}元)")

    # 风险
    r = analysis["risk_metrics"]
    print(f"\n── 风险指标 (10k 蒙特卡洛) ──")
    print(f"  VaR(95%):      {r['var_95pct']}%  (95%概率单轮损失不超过此值)")
    print(f"  CVaR(95%):     {r['cvar_95pct']}%  (尾部条件损失)")
    print(f"  夏普率:         {r['sharpe_ratio']}  (>0.5=良好, >1.0=优秀)")
    print(f"  最大回撤:       {r['max_drawdown_pct']}%")
    print(f"  破产概率:       {r['ruin_probability']}%  (损失>50%的概率)")
    print(f"  期望收益:       {r['expected_return']}%/轮")
    print(f"  波动率:         {r['volatility']}%")

    # 回撤保护
    d = analysis["drawdown_protection"]
    print(f"\n── 连续亏损保护 ──")
    print(f"  当前连亏: {d['consecutive_losses']}次 → 档位: {d['level']}")
    print(f"  Kelly: {d['original_kelly']} → {d['adjusted_kelly']} ({d['suggested_stake_pct']}%/注)")

    # 资金曲线
    s = analysis["bankroll_simulation"]
    print(f"\n── 资金曲线模拟 ({s['paths']}路径 × {s['rounds']}轮) ──")
    print(f"  最佳:  {s['best_path']['final']}元 | 中位: {s['median_path']['final']}元 | 最差: {s['worst_path']['final']}元")
    print(f"  盈利概率: {s['prob_profit']}% | 破产概率: {s['prob_ruin']}%")

    # 有效前沿
    print(f"\n── 有效前沿 (风险-收益) ──")
    print(f"  {'Kelly':<8} {'收益%':<8} {'波动%':<8} {'夏普':<8} {'投注%':<8}")
    for pt in analysis["efficient_frontier"][:8]:
        print(f"  {pt['kelly_fraction']:<8} {pt['expected_return_pct']:<8} "
              f"{pt['volatility_pct']:<8} {pt['sharpe']:<8} {pt['total_stake_pct']:<8}")
