#!/usr/bin/env python3
"""
MatchPredict CLI - 体彩数据 + DeepSeek AI 预测
用法:
  python predict.py fetch [--days 3]        爬取体彩比赛
  python predict.py ai <编号>                对缓存的比赛进行 AI 预测
  python predict.py ai --home X --away Y    手动输入比赛进行预测
             [--league L] [--home_odds H] [--draw_odds D] [--away_odds A]
  python predict.py result <ID> <主队进球> <客队进球>   录入比赛结果
  python predict.py stats                   查看预测统计
  python predict.py history [--limit 20]    查看最近预测记录
  python predict.py pending                 查看待录入结果的预测
"""
import argparse
import os
import sys
import io

# 强制 UTF-8 输出（Windows 兼容）
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

from scripts.deepseek_predictor import DeepSeekPredictor
from scripts.lottery_api import ChinaSportsLotterySpider
from scripts.odds500_scraper import get_worldcup_matches as get_500_matches
from scripts.match_data import get_upcoming, get_standings, auto_sync
from scripts.match_research import research_match, format_for_prompt
from scripts.storage import (
    save_prediction, update_result, get_predictions, get_stats,
    get_pending_predictions, cache_lottery_matches, load_cached_matches,
)

# ========== 配置 ==========

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

spider = ChinaSportsLotterySpider()
predictor = DeepSeekPredictor(api_key=API_KEY, model=MODEL)


# ========== 表格渲染 ==========

def _fmt(v, width: int = 0) -> str:
    """安全格式化，处理 None 和截断"""
    s = str(v) if v is not None else ""
    if width and len(s) > width:
        s = s[:width - 1] + "…"
    return s


def _print_table(headers: list[str], rows: list[list], aligns: list[str] = None):
    """打印对齐的终端表格"""
    if not rows:
        print("  (无数据)")
        return

    if aligns is None:
        aligns = ["<"] * len(headers)

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(_fmt(cell)))

    # 分隔线
    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    print(sep)

    # 表头
    header_cells = [f" {headers[i].ljust(col_widths[i])} " for i in range(len(headers))]
    print("|" + "|".join(header_cells) + "|")
    print(sep)

    # 数据行
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            text = _fmt(cell, col_widths[i])
            if aligns[i] == ">":
                cells.append(f" {text.rjust(col_widths[i])} ")
            else:
                cells.append(f" {text.ljust(col_widths[i])} ")
        print("|" + "|".join(cells) + "|")

    print(sep)


# ========== 命令实现 ==========

def cmd_wc(args):
    """从 500.com 获取世界杯比赛 + 赔率"""
    print(f"\n  正在从 odds.500.com 获取世界杯比赛...\n")
    matches = get_500_matches()

    if not matches:
        print("  未获取到世界杯比赛数据")
        return

    # 转换为统一缓存格式
    formatted = []
    for m in matches:
        formatted.append({
            "match_id": m["fid"],
            "home_team": m["home_team"],
            "away_team": m["away_team"],
            "league_name": f"世界杯 ({m.get('match_num', '')})",
            "match_time": m.get("match_time", ""),
            "odds": {
                "hhad": {
                    "h": str(m.get("home_odds", "")),
                    "d": str(m.get("draw_odds", "")),
                    "a": str(m.get("away_odds", "")),
                }
            }
        })

    cache_lottery_matches(formatted)

    headers = ["#", "编号", "主队", "客队", "时间", "主胜", "平局", "客胜"]
    rows = []
    for i, m in enumerate(matches, 1):
        rows.append([
            str(i),
            m.get("match_num", ""),
            m["home_team"],
            m["away_team"],
            m.get("match_time", "")[:16],
            str(m.get("home_odds", "")),
            str(m.get("draw_odds", "")),
            str(m.get("away_odds", "")),
        ])

    _print_table(headers, rows, ["<", "<", "<", "<", "<", ">", ">", ">"])
    print(f"  共 {len(matches)} 场世界杯比赛 | 赔率来源: odds.500.com")
    print(f"  下一步: python predict.py ai <编号>")


def cmd_sync(args):
    """用 football-data.org 自动同步已完赛比分"""
    pending = get_pending_predictions()
    if not pending:
        print("  所有预测都已录入结果")
        return

    print(f"\n  正在检查 {len(pending)} 条待录入预测...\n")
    updated = auto_sync("worldcup", pending)

    if updated:
        print(f"  已自动更新 {len(updated)} 条记录:")
        for pid in updated:
            # 显示更新后的记录
            records = get_predictions(limit=100)
            for r in records:
                if int(r.get("id", 0)) == pid:
                    h = r.get("is_correct") == "Y"
                    status = "[OK] 命中" if h else "[XX] 未命中"
                    score = f"{r.get('actual_home_score', '?')}-{r.get('actual_away_score', '?')}"
                    print(f"    ID={pid}: {r['home_team']} {score} {r['away_team']} | 预测:{r.get('predicted_result','?')} | {status}")
                    break
    else:
        print("  暂无可自动更新的结果（比赛尚未进行或未找到匹配）")

    print(f"\n  数据来源: football-data.org API")


def cmd_standings(args):
    """显示世界杯小组积分榜"""
    groups = get_standings()
    if not groups:
        print("  未获取到积分榜数据")
        return

    for g in groups:
        print(f"\n  === {g['group']} ===")
        headers = ["#", "队伍", "场", "胜", "平", "负", "进球", "失球", "净胜", "分"]
        rows = []
        for t in g["table"]:
            rows.append([
                str(t["position"]),
                t["tla"],
                str(t["played"]),
                str(t["won"]),
                str(t["draw"]),
                str(t["lost"]),
                str(t["goals_for"]),
                str(t["goals_against"]),
                f"{t['goal_diff']:+d}",
                str(t["points"]),
            ])
        _print_table(headers, rows, ["<", "<", ">", ">", ">", ">", ">", ">", ">", ">"])

    print(f"\n  数据来源: football-data.org API")


def cmd_fetch(args):
    """爬取体彩比赛数据"""
    days = getattr(args, 'days', 3)
    print(f"\n  正在从 sporttery.cn 爬取未来 {days} 天比赛...\n")
    matches = spider.get_formatted_matches(days_ahead=days)

    if not matches:
        print("  未获取到比赛数据（网站可能改版，已使用模拟数据）")
        return

    cache_lottery_matches(matches)

    headers = ["#", "主队", "客队", "联赛", "时间", "主胜", "平局", "客胜"]
    rows = []
    for i, m in enumerate(matches, 1):
        odds = m.get("odds", {}).get("hhad", {})
        rows.append([
            str(i),
            m.get("home_team", ""),
            m.get("away_team", ""),
            m.get("league_name", ""),
            m.get("match_time", "")[:16],
            odds.get("h", ""),
            odds.get("d", ""),
            odds.get("a", ""),
        ])

    _print_table(headers, rows, ["<", "<", "<", "<", "<", ">", ">", ">"])
    print(f"  共 {len(matches)} 场比赛 | 已缓存到 data/lottery_cache.csv")
    print(f"  下一步: python predict.py ai <编号>")


def cmd_ai(args):
    """AI 预测"""
    match_id = getattr(args, 'match_id', None)
    home = getattr(args, 'home', None)

    # 从缓存中选比赛
    if match_id is not None and home is None:
        cached = load_cached_matches()
        idx = match_id - 1
        if idx < 0 or idx >= len(cached):
            print(f"  编号超出范围 (1-{len(cached)})，请先运行 python predict.py fetch")
            return
        m = cached[idx]
        home_team = m["home_team"]
        away_team = m["away_team"]
        league_name = m["league_name"]
        home_odds = float(m["home_odds"]) if m["home_odds"] else 2.0
        draw_odds = float(m["draw_odds"]) if m["draw_odds"] else 3.2
        away_odds = float(m["away_odds"]) if m["away_odds"] else 3.5
    elif home:
        home_team = home
        away_team = args.away or ""
        league_name = getattr(args, 'league', '未知联赛')
        home_odds = float(getattr(args, 'home_odds', 2.0) or 2.0)
        draw_odds = float(getattr(args, 'draw_odds', 3.2) or 3.2)
        away_odds = float(getattr(args, 'away_odds', 3.5) or 3.5)

        if not away_team:
            print("  请提供客队名称: --away <队名>")
            return
    else:
        print("  用法: python predict.py ai <编号>  或  python predict.py ai --home X --away Y")
        return

    print(f"\n  [VS] {home_team} vs {away_team}")
    print(f"  [L] {league_name}")
    print(f"  [$] 赔率: 主胜 {home_odds} / 平局 {draw_odds} / 客胜 {away_odds}")

    # 杯赛 → 自动获取战术研究数据
    research_text = ""
    is_cup = any(kw in league_name for kw in ["世界杯", "World Cup", "欧洲杯", "Euro"])
    if is_cup:
        print(f"  [R] 正在搜索赛前战术分析...")
        try:
            # 确定赛事代码
            comp = "worldcup" if ("世界杯" in league_name or "World Cup" in league_name) else "euro"

            # 从 match_data 查找队伍所在组
            from scripts.match_data import get_data, CN_TO_TLA
            all_data = get_data(comp)
            home_tla = CN_TO_TLA.get(home_team.strip(), home_team)
            away_tla = CN_TO_TLA.get(away_team.strip(), away_team)

            group = ""
            for m in all_data["matches"]:
                htla = m.get("home_tla") or ""
                atla = m.get("away_tla") or ""
                if home_tla in (htla, m.get("home_team", "")) or away_tla in (atla, m.get("away_team", "")):
                    group = (m.get("group") or "").replace("Group ", "").replace("GROUP_", "")
                    break

            if group:
                r = research_match(home_team, away_team, group=group)
                research_text = format_for_prompt(r, home_team, away_team)
                if research_text:
                    print(f"  [R] 已获取 Group {group} 战术分析 (RotoWire)")
                else:
                    print(f"  [R] Group {group} 战术数据不可用，使用 AI 内置知识")
            else:
                print(f"  [R] 未找到队伍分组信息，使用 AI 内置知识")
        except Exception as e:
            import traceback
            print(f"  [R] 战术研究失败: {e}")

    print(f"\n  [AI] 正在调用 DeepSeek({MODEL}) 分析...\n")

    result = predictor.predict(home_team, away_team, league_name,
                               home_odds, draw_odds, away_odds,
                               research_text=research_text)

    if not result:
        print("  [X] AI 预测失败，请检查网络和 API Key")
        return

    print("  " + "─" * 56)
    for line in result.replace("\\n", "\n").split("\n"):
        print(f"  {line}")
    print("  " + "─" * 56)

    # 保存记录
    pred_id = save_prediction(home_team, away_team, league_name,
                              home_odds, draw_odds, away_odds, result)
    print(f"\n  [SAVED] 预测已保存 ID={pred_id} | 比赛结束后运行: python predict.py result {pred_id} <主队进球> <客队进球>")


def cmd_result(args):
    """录入实际比分"""
    pred_id = args.prediction_id
    home_score = args.home_score
    away_score = args.away_score

    update_result(pred_id, home_score, away_score)

    # 显示更新后的记录
    records = get_predictions(limit=100)
    for r in records:
        if int(r.get("id", 0)) == pred_id:
            status = "[OK] 命中" if r.get("is_correct") == "Y" else "[XX] 未命中"
            print(f"  {r['home_team']} {home_score}-{away_score} {r['away_team']}  |  "
                  f"预测: {r.get('predicted_result', '?')} | {status}")
            return

    print(f"  记录 ID={pred_id} 已更新")


def cmd_stats(args):
    """显示预测统计"""
    s = get_stats()
    print(f"\n  [STATS] 预测统计")
    print(f"  {'─' * 30}")
    print(f"  总预测数:     {s['total']}")
    print(f"  已出结果:     {s['with_result']}")
    print(f"  命中:         {s['correct']}")
    print(f"  准确率:       {s['accuracy']}%")
    print()

    if s['with_result'] > 0:
        headers = ["预测类型", "次数", "命中", "准确率"]
        rows = []
        for result_type in ["主胜", "平局", "客胜"]:
            d = s["by_result"][result_type]
            if d["total"] > 0:
                rate = round(d["hit"] / d["total"] * 100, 1)
                rows.append([result_type, str(d["total"]), str(d["hit"]), f"{rate}%"])
        _print_table(headers, rows, ["<", ">", ">", ">"])


def cmd_history(args):
    """查看最近预测"""
    limit = getattr(args, 'limit', 20)
    records = get_predictions(limit=limit)

    if not records:
        print("  暂无预测记录")
        return

    headers = ["ID", "时间", "主队", "客队", "预测", "比分", "命中"]
    rows = []
    for r in reversed(records):
        score = ""
        if r.get("actual_home_score") and r.get("actual_away_score"):
            score = f"{r['actual_home_score']}-{r['actual_away_score']}"
        hit = ""
        if r.get("is_correct") == "Y":
            hit = "OK"
        elif r.get("is_correct") == "N":
            hit = "XX"
        rows.append([
            r.get("id", ""),
            r.get("created_at", "")[:16],
            r.get("home_team", ""),
            r.get("away_team", ""),
            r.get("predicted_result", ""),
            score,
            hit,
        ])

    _print_table(headers, rows, ["<", "<", "<", "<", "<", "<", "<"])
    print(f"  共 {len(records)} 条记录")


def cmd_pending(args):
    """查看待录入结果的预测"""
    pending = get_pending_predictions()
    if not pending:
        print("  所有预测都已录入结果")
        return

    headers = ["ID", "时间", "主队", "客队", "预测", "赔率"]
    rows = []
    for r in pending:
        odds_str = f"{r.get('home_odds', '')}/{r.get('draw_odds', '')}/{r.get('away_odds', '')}"
        rows.append([
            r.get("id", ""),
            r.get("created_at", "")[:16],
            r.get("home_team", ""),
            r.get("away_team", ""),
            r.get("predicted_result", ""),
            odds_str,
        ])

    _print_table(headers, rows, ["<", "<", "<", "<", "<", "<"])
    print(f"  共 {len(pending)} 条待录入")
    print(f"  录入: python predict.py result <ID> <主队进球> <客队进球>")


# ========== CLI 入口 ==========

def main():
    parser = argparse.ArgumentParser(
        description="MatchPredict - 体彩数据 + DeepSeek AI 预测",
        usage="python predict.py <command> [options]"
    )
    sub = parser.add_subparsers(dest="command")

    # fetch
    p_fetch = sub.add_parser("fetch", help="爬取体彩比赛数据")
    p_fetch.add_argument("--days", type=int, default=3, help="未来天数 (1-7)")

    # wc - 500.com 世界杯
    sub.add_parser("wc", help="从 500.com 获取世界杯比赛+赔率")

    # sync
    sub.add_parser("sync", help="自动同步已完赛比分 (football-data.org)")

    # standings
    sub.add_parser("standings", help="显示世界杯小组积分榜 (football-data.org)")

    # ai
    p_ai = sub.add_parser("ai", help="AI 预测")
    p_ai.add_argument("match_id", nargs="?", type=int, default=None, help="缓存比赛编号")
    p_ai.add_argument("--home", type=str, default=None, help="主队名称")
    p_ai.add_argument("--away", type=str, default=None, help="客队名称")
    p_ai.add_argument("--league", type=str, default="未知联赛", help="联赛名称")
    p_ai.add_argument("--home_odds", type=float, default=None, help="主胜赔率")
    p_ai.add_argument("--draw_odds", type=float, default=None, help="平局赔率")
    p_ai.add_argument("--away_odds", type=float, default=None, help="客胜赔率")

    # result
    p_res = sub.add_parser("result", help="录入比赛结果")
    p_res.add_argument("prediction_id", type=int, help="预测记录 ID")
    p_res.add_argument("home_score", type=int, help="主队进球")
    p_res.add_argument("away_score", type=int, help="客队进球")

    # stats
    sub.add_parser("stats", help="查看预测统计")

    # history
    p_hist = sub.add_parser("history", help="查看最近预测")
    p_hist.add_argument("--limit", type=int, default=20, help="显示条数")

    # pending
    sub.add_parser("pending", help="待录入结果的预测")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    commands = {
        "fetch": cmd_fetch,
        "wc": cmd_wc,
        "sync": cmd_sync,
        "standings": cmd_standings,
        "ai": cmd_ai,
        "result": cmd_result,
        "stats": cmd_stats,
        "history": cmd_history,
        "pending": cmd_pending,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
