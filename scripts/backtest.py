"""
回测系统 V2 — 对比 Market vs V1 泊松 vs V2 增强模型
"""
import csv
import io
import json
from collections import defaultdict
from datetime import datetime
import requests

try:
    from scripts.prediction_engine import (
        implied_probability, expected_goals, poisson_probability,
        extract_team_stats, analyze_match_v2, build_elo_ratings,
    )
except ImportError:
    from prediction_engine import (
        implied_probability, expected_goals, poisson_probability,
        extract_team_stats, analyze_match_v2, build_elo_ratings,
    )

FD_BASE = "https://www.football-data.co.uk/mmz4281/2526"
LEAGUES = {
    "PL": ("E0", "Premier League"), "PD": ("SP1", "La Liga"),
    "SA": ("I1", "Serie A"), "BL1": ("D1", "Bundesliga"), "FL1": ("F1", "Ligue 1"),
}


def load_csv(url):
    r = requests.get(url, timeout=15)
    r.encoding = "utf-8"
    return list(csv.DictReader(io.StringIO(r.text))) if r.status_code == 200 else []


def backtest(league_code):
    csv_code, name = LEAGUES[league_code]
    rows = load_csv(f"{FD_BASE}/{csv_code}.csv")
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("Date", ""))

    completed = []
    v1res, v2res, mktres = [], [], []
    total = len(rows)

    print(f"\n  {name}: {total} 场...", end=" ")

    for i, row in enumerate(rows):
        home, away = row.get("HomeTeam", ""), row.get("AwayTeam", "")
        fthg_s, ftag_s = row.get("FTHG", ""), row.get("FTAG", "")
        if not fthg_s or not ftag_s:
            continue
        fthg, ftag = int(fthg_s), int(ftag_s)

        oh = float(row.get("B365H", 0) or 0)
        od = float(row.get("B365D", 0) or 0)
        oa = float(row.get("B365A", 0) or 0)
        if not (oh and od and oa):
            continue

        odds = {"home": oh, "draw": od, "away": oa}
        actual = "home" if fthg > ftag else ("away" if fthg < ftag else "draw")
        md = {"matches": list(completed)}
        elo = build_elo_ratings(completed)

        # Market pick (highest implied prob = lowest odds)
        mkt_pick = min(odds, key=lambda k: odds[k])

        # V1: basic Poisson
        hs = extract_team_stats(md, home)
        aws = extract_team_stats(md, away)
        imp = implied_probability(oh, od, oa)
        xg = expected_goals(hs, aws)
        p = poisson_probability(xg["home_xg"], xg["away_xg"])
        v1_pick = max(p["result_probability"], key=p["result_probability"].get)
        v1_prob = p["result_probability"]

        # V2: enhanced + ensemble
        v2 = analyze_match_v2("PL", home, away, oh, od, oa, md, completed, elo)
        v2_pick = v2["recommendation"]
        v2_prob = v2["final_probability"]

        def record(pick, prob):
            return {
                "pick": pick, "actual": actual, "correct": pick == actual,
                "odds": odds,
                "brier": sum((prob[o] / 100 - (1.0 if actual == o else 0.0)) ** 2 for o in ["home","draw","away"]),
            }

        mktres.append(record(mkt_pick, imp))
        v1res.append(record(v1_pick, v1_prob))
        v2res.append(record(v2_pick, v2_prob))

        completed.append({"home_team": home, "away_team": away,
                          "home_score": fthg, "away_score": ftag, "status": "FINISHED"})

        if (i + 1) % 100 == 0:
            print(f"{i + 1}...", end=" ", flush=True)

    print("done")
    return _summarize(name, mktres, v1res, v2res)


def _summarize(name, mkt, v1, v2):
    def stats(results, label):
        n = len(results)
        acc = sum(1 for r in results if r["correct"]) / n * 100
        brier = sum(r["brier"] for r in results) / n
        roi = sum((r["odds"][r["pick"]] - 1) if r["correct"] else -1 for r in results) / n * 100
        by = defaultdict(lambda: [0, 0])
        for r in results:
            by[r["actual"]][0] += 1
            if r["correct"]:
                by[r["actual"]][1] += 1
        return {
            "label": label, "accuracy": round(acc, 1), "brier": round(brier, 4),
            "roi": round(roi, 1), "n": n,
            "by": {k: f"{v[1]}/{v[0]} ({round(v[1]/max(1,v[0])*100)}%)" for k, v in sorted(by.items())},
        }

    return {
        "league": name, "matches": len(v1),
        "market": stats(mkt, "Market"),
        "v1": stats(v1, "V1 Poisson"),
        "v2": stats(v2, "V2 Enhanced"),
    }


def print_report(all_m):
    print("\n" + "=" * 72)
    print("  V1 vs V2 回测对比")
    print("=" * 72)
    for m in all_m:
        if not m:
            continue
        print(f"\n  ── {m['league']} ({m['matches']} 场) ──")
        print(f"  {'':>12} {'Market':>10} {'V1 Poisson':>11} {'V2 Enhanced':>11}")
        print(f"  {'准确率':>12} {m['market']['accuracy']:>9.1f}% {m['v1']['accuracy']:>10.1f}% {m['v2']['accuracy']:>10.1f}%")
        print(f"  {'Brier':>12} {m['market']['brier']:>10} {m['v1']['brier']:>10} {m['v2']['brier']:>10}")
        print(f"  {'ROI':>12} {m['market']['roi']:>9.1f}% {m['v1']['roi']:>10.1f}% {m['v2']['roi']:>10.1f}%")
        print(f"  {'主胜':>12} {m['market']['by'].get('home','-'):>10} {m['v1']['by'].get('home','-'):>11} {m['v2']['by'].get('home','-'):>11}")
        print(f"  {'平局':>12} {m['market']['by'].get('draw','-'):>10} {m['v1']['by'].get('draw','-'):>11} {m['v2']['by'].get('draw','-'):>11}")
        print(f"  {'客胜':>12} {m['market']['by'].get('away','-'):>10} {m['v1']['by'].get('away','-'):>11} {m['v2']['by'].get('away','-'):>11}")

    total = sum(m["matches"] for m in all_m if m)
    if len(all_m) > 1:
        w = lambda key: sum(m[key]["accuracy"] * m["matches"] for m in all_m if m) / total
        wb = lambda key: sum(m[key]["brier"] * m["matches"] for m in all_m if m) / total
        print(f"\n  ── 加权汇总 ({total} 场) ──")
        print(f"  准确率: Market {w('market'):.1f}% | V1 {w('v1'):.1f}% | V2 {w('v2'):.1f}%")
        print(f"  Brier:  Market {wb('market'):.4f} | V1 {wb('v1'):.4f} | V2 {wb('v2'):.4f}")
        print(f"  V2 vs V1 提升: +{w('v2') - w('v1'):.1f}% 准确率, Brier {wb('v1') - wb('v2'):+.4f}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("-c", "--competition", default="PL")
    p.add_argument("--all-leagues", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    all_m = []
    codes = list(LEAGUES) if args.all_leagues else [args.competition]
    for c in codes:
        m = backtest(c)
        if m:
            all_m.append(m)

    if args.json:
        print(json.dumps(all_m, ensure_ascii=False, indent=2))
    else:
        print_report(all_m)
