"""
统一比赛数据接口 — 世界杯 + 欧洲杯 + 五大联赛

数据源:
  OpenFootball (主): worldcup.json, euro.json, football.json
  football-data.org (辅): 实时状态 + 积分榜

用法:
  python scripts/match_data.py --competition worldcup matches
  python scripts/match_data.py --competition euro standings
  python scripts/match_data.py --competition PL matches
  python scripts/match_data.py --competition worldcup sync
"""
import csv
import io
import json
import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ============ 赛事配置 ============

OF_RAW = "https://raw.githubusercontent.com/openfootball"

FD_CSV_BASE = "https://www.football-data.co.uk/mmz4281/2526"

COMPETITIONS = {
    "worldcup": {
        "name": "World Cup 2026",
        "of_url": f"{OF_RAW}/worldcup.json/master/2026/worldcup.json",
        "of_teams": f"{OF_RAW}/worldcup.json/master/2026/worldcup.teams.json",
        "is_tournament": True,
    },
    "euro": {
        "name": "Euro 2024",
        "of_url": f"{OF_RAW}/euro.json/master/2024/euro.json",
        "of_teams": None,
        "is_tournament": True,
    },
    "PL": {
        "name": "Premier League 2025/26",
        "of_url": None,
        "fd_csv": f"{FD_CSV_BASE}/E0.csv",
        "is_tournament": False,
    },
    "PD": {
        "name": "La Liga 2025/26",
        "of_url": None,
        "fd_csv": f"{FD_CSV_BASE}/SP1.csv",
        "is_tournament": False,
    },
    "SA": {
        "name": "Serie A 2025/26",
        "of_url": None,
        "fd_csv": f"{FD_CSV_BASE}/I1.csv",
        "is_tournament": False,
    },
    "BL1": {
        "name": "Bundesliga 2025/26",
        "of_url": None,
        "fd_csv": f"{FD_CSV_BASE}/D1.csv",
        "is_tournament": False,
    },
    "FL1": {
        "name": "Ligue 1 2025/26",
        "of_url": None,
        "fd_csv": f"{FD_CSV_BASE}/F1.csv",
        "is_tournament": False,
    },
}

# 中文队名 → FIFA TLA
CN_TO_TLA = {
    "德国": "GER", "荷兰": "NED", "日本": "JPN", "巴西": "BRA",
    "阿根廷": "ARG", "英格兰": "ENG", "法国": "FRA", "西班牙": "ESP",
    "意大利": "ITA", "葡萄牙": "POR", "比利时": "BEL", "克罗地亚": "CRO",
    "乌拉圭": "URY", "哥伦比亚": "COL", "墨西哥": "MEX", "美国": "USA",
    "摩洛哥": "MAR", "塞内加尔": "SEN", "突尼斯": "TUN", "阿尔及利亚": "ALG",
    "加纳": "GHA", "科特迪瓦": "CIV", "南非": "RSA", "埃及": "EGY",
    "韩国": "KOR", "澳大利亚": "AUS", "瑞典": "SWE", "挪威": "NOR",
    "丹麦": "DEN", "波兰": "POL", "捷克": "CZE", "奥地利": "AUT",
    "卡塔尔": "QAT", "沙特阿拉伯": "KSA", "伊朗": "IRN", "伊拉克": "IRQ",
    "加拿大": "CAN", "新西兰": "NZL", "海地": "HAI", "库拉索": "CUW",
    "佛得角": "CPV", "刚果(金)": "COD", "巴拿马": "PAN",
    "约旦": "JOR", "乌兹别克斯坦": "UZB", "巴拉圭": "PAR", "波黑": "BIH",
    "土耳其": "TUR", "苏格兰": "SCO", "瑞士": "SUI", "厄瓜多尔": "ECU",
    "乌克兰": "UKR", "塞尔维亚": "SRB", "喀麦隆": "CMR", "尼日利亚": "NGA",
}

FD_BASE = "https://api.football-data.org/v4"
FD_KEY = os.environ.get("FOOTBALL_DATA_KEY", "")
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CACHE_TTL = 300


# ============ 数据获取 ============

def _fetch(url: str, headers: dict = None) -> Optional[dict]:
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        logger.warning(f"HTTP {r.status_code}: {url[-60:]}")
        return None
    except Exception as e:
        logger.warning(f"Fetch fail: {url[-60:]}: {e}")
        return None


def _cache_path(competition: str) -> str:
    return os.path.join(CACHE_DIR, f"matchdata_{competition}.json")


def _load_cache(competition: str) -> Optional[dict]:
    path = _cache_path(competition)
    if os.path.exists(path):
        age = datetime.now().timestamp() - os.path.getmtime(path)
        if age < CACHE_TTL:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


def _parse_fd_csv(csv_url: str, season_label: str) -> list:
    """解析 Football-Data.co.uk CSV，提取比分+赔率+统计数据"""
    import csv
    text = _fetch_text(csv_url)
    if not text:
        return []

    reader = csv.DictReader(io.StringIO(text))
    matches = []
    for i, row in enumerate(reader, 1):
        date_str = row.get("Date", "")

        # 转换日期格式 DD/MM/YYYY → YYYY-MM-DD
        date_iso = ""
        if date_str:
            try:
                parts = date_str.split("/")
                if len(parts) == 3:
                    date_iso = f"20{parts[2]}-{parts[1]}-{parts[0]}"
            except (ValueError, IndexError):
                date_iso = date_str

        home = row.get("HomeTeam", "")
        away = row.get("AwayTeam", "")
        fthg = row.get("FTHG", "")
        ftag = row.get("FTAG", "")
        hthg = row.get("HTHG", "")
        htag = row.get("HTAG", "")

        status = "SCHEDULED"
        if fthg and ftag:
            status = "FINISHED"

        matches.append({
            "id": i,
            "date": date_iso,
            "round": f"Matchday {len(matches) // 10 + 1}",
            "home_team": home,
            "away_team": away,
            "home_tla": home[:3].upper(),
            "away_tla": away[:3].upper(),
            "home_score": int(fthg) if fthg else None,
            "away_score": int(ftag) if ftag else None,
            "half_home": int(hthg) if hthg else None,
            "half_away": int(htag) if htag else None,
            "stadium": "",
            "status": status,
            # 赔率（多家博彩公司）
            "odds": {
                "bet365": {
                    "home": float(row["B365H"]) if row.get("B365H") else None,
                    "draw": float(row["B365D"]) if row.get("B365D") else None,
                    "away": float(row["B365A"]) if row.get("B365A") else None,
                },
                "betfair": {
                    "home": float(row["BFEH"]) if row.get("BFEH") else None,
                    "draw": float(row["BFED"]) if row.get("BFED") else None,
                    "away": float(row["BFEA"]) if row.get("BFEA") else None,
                },
                "pinnacle": {
                    "home": float(row["PSH"]) if row.get("PSH") else None,
                    "draw": float(row["PSD"]) if row.get("PSD") else None,
                    "away": float(row["PSA"]) if row.get("PSA") else None,
                },
                "market_avg": {
                    "home": float(row["AvgH"]) if row.get("AvgH") else None,
                    "draw": float(row["AvgD"]) if row.get("AvgD") else None,
                    "away": float(row["AvgA"]) if row.get("AvgA") else None,
                },
                "max": {
                    "home": float(row["MaxH"]) if row.get("MaxH") else None,
                    "draw": float(row["MaxD"]) if row.get("MaxD") else None,
                    "away": float(row["MaxA"]) if row.get("MaxA") else None,
                },
            },
            # 统计数据
            "stats": {
                "home_shots": int(row["HS"]) if row.get("HS") else None,
                "away_shots": int(row["AS"]) if row.get("AS") else None,
                "home_shots_on_target": int(row["HST"]) if row.get("HST") else None,
                "away_shots_on_target": int(row["AST"]) if row.get("AST") else None,
                "home_fouls": int(row["HF"]) if row.get("HF") else None,
                "away_fouls": int(row["AF"]) if row.get("AF") else None,
                "home_corners": int(row["HC"]) if row.get("HC") else None,
                "away_corners": int(row["AC"]) if row.get("AC") else None,
                "home_yellow": int(row["HY"]) if row.get("HY") else None,
                "away_yellow": int(row["AY"]) if row.get("AY") else None,
                "home_red": int(row["HR"]) if row.get("HR") else None,
                "away_red": int(row["AR"]) if row.get("AR") else None,
            },
            "home_goals": [],
            "away_goals": [],
            "source": "football-data.co.uk",
        })

    return matches


def _fetch_text(url: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=15)
        r.encoding = "utf-8"
        return r.text if r.status_code == 200 else None
    except Exception as e:
        logger.warning(f"Fetch fail: {url[:60]}: {e}")
        return None


def _save_cache(competition: str, data: dict):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(competition), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============ 数据融合 ============

def get_data(competition: str, force_refresh: bool = False) -> dict:
    """获取融合后的赛事数据"""
    if not force_refresh:
        cached = _load_cache(competition)
        if cached:
            return cached

    cfg = COMPETITIONS.get(competition)
    if not cfg:
        return {"error": f"未知赛事: {competition}", "matches": [], "standings": []}

    matches = []
    teams_list = []

    # 1. OpenFootball 数据
    if cfg["of_url"]:
        of_data = _fetch(cfg["of_url"]) or {}
        if cfg["of_teams"]:
            teams_list = _fetch(cfg["of_teams"]) or []

        for i, m in enumerate(of_data.get("matches", []), 1):
            score = m.get("score", {})
            ft = score.get("ft")
            ht = score.get("ht")

            # 队名提取（euro.json 格式不同）
            if isinstance(m.get("team1"), dict):
                home_name = m["team1"].get("name", "")
                away_name = m["team2"].get("name", "")
                home_code = m["team1"].get("code", "")
                away_code = m["team2"].get("code", "")
            else:
                home_name = m.get("team1", "")
                away_name = m.get("team2", "")
                home_code = home_name[:3].upper()
                away_code = away_name[:3].upper()

            status = "SCHEDULED"
            if ft:
                status = "FINISHED"
            if score.get("et"):
                status = "FINISHED_ET"

            matches.append({
                "id": i,
                "date": m.get("date", ""),
                "time": m.get("time", ""),
                "round": m.get("round", ""),
                "group": m.get("group", ""),
                "home_team": home_name,
                "away_team": away_name,
                "home_tla": home_code,
                "away_tla": away_code,
                "home_score": ft[0] if ft else None,
                "away_score": ft[1] if ft else None,
                "half_home": ht[0] if ht else None,
                "half_away": ht[1] if ht else None,
                "stadium": m.get("ground", m.get("stadium", "")),
                "status": status,
                "home_goals": _extract_goals(m, "goals1"),
                "away_goals": _extract_goals(m, "goals2"),
            })

    # 2. Football-Data.co.uk (联赛主数据源，零Key，含赔率+统计)
    if cfg.get("fd_csv") and not matches:
        logger.info(f"从 Football-Data.co.uk 加载: {cfg['fd_csv'][-20:]}")
        matches = _parse_fd_csv(cfg["fd_csv"], cfg["name"])
        if matches:
            logger.info(f"Football-Data.co.uk: {len(matches)} 场比赛 (含赔率+数据)")

    # 3. football-data.org (实时补充)
    fd_matches_raw = []
    if FD_KEY and cfg.get("fd_id"):
        headers = {"X-Auth-Token": FD_KEY}
        fd_data = _fetch(f"{FD_BASE}/competitions/{cfg['fd_id']}/matches", headers)
        if fd_data:
            fd_matches_raw = fd_data.get("matches", [])

    if fd_matches_raw and matches:
        _merge_fd(matches, fd_matches_raw)

    # 如果没有其他源数据，直接用 football-data.org
    if not matches and fd_matches_raw:
        matches = _parse_fd_matches(fd_matches_raw)

    # 3. 计算积分榜
    standings = _compute_standings(matches, cfg["is_tournament"])

    result = {
        "competition": cfg["name"],
        "matches": matches,
        "standings": standings,
        "teams": teams_list,
        "updated": datetime.now().isoformat(),
    }
    _save_cache(competition, result)
    return result


def _extract_goals(m: dict, key: str) -> list:
    goals = m.get(key, [])
    result = []
    for g in (goals or []):
        if isinstance(g, dict):
            result.append({
                "name": g.get("name", ""),
                "minute": g.get("minute", 0),
                "penalty": g.get("penalty", False),
            })
    return result


def _merge_fd(of_matches: list, fd_raw: list):
    for fd_m in fd_raw:
        fd_home = (fd_m.get("homeTeam") or {}).get("name", "") or ""
        fd_away = (fd_m.get("awayTeam") or {}).get("name", "") or ""
        fd_status = fd_m.get("status", "")
        fd_score = fd_m.get("score", {}).get("fullTime", {})
        if not fd_home or not fd_away:
            continue

        for m in of_matches:
            if (fd_home.lower() in m["home_team"].lower() or m["home_team"].lower() in fd_home.lower()):
                if (fd_away.lower() in m["away_team"].lower() or m["away_team"].lower() in fd_away.lower()):
                    if fd_score.get("home") is not None:
                        m["home_score"] = fd_score["home"]
                        m["away_score"] = fd_score["away"]
                    half = fd_m.get("score", {}).get("halfTime", {})
                    if half.get("home") is not None:
                        m["half_home"] = half["home"]
                        m["half_away"] = half["away"]
                    m["status"] = fd_status
                    m["home_tla"] = fd_m.get("homeTeam", {}).get("tla", m["home_tla"])
                    m["away_tla"] = fd_m.get("awayTeam", {}).get("tla", m["away_tla"])
                    break


def _parse_fd_matches(fd_raw: list) -> list:
    matches = []
    for i, m in enumerate(fd_raw, 1):
        ft = m.get("score", {}).get("fullTime", {})
        ht = m.get("score", {}).get("halfTime", {})
        matches.append({
            "id": i,
            "date": (m.get("utcDate", "")[:10] if m.get("utcDate") else ""),
            "round": f"Matchday {m.get('matchday', '')}",
            "group": m.get("group", ""),
            "home_team": (m.get("homeTeam") or {}).get("name", ""),
            "away_team": (m.get("awayTeam") or {}).get("name", ""),
            "home_tla": (m.get("homeTeam") or {}).get("tla", ""),
            "away_tla": (m.get("awayTeam") or {}).get("tla", ""),
            "home_score": ft.get("home"),
            "away_score": ft.get("away"),
            "half_home": ht.get("home"),
            "half_away": ht.get("away"),
            "stadium": m.get("venue", ""),
            "status": m.get("status", "SCHEDULED"),
            "home_goals": [],
            "away_goals": [],
        })
    return matches


# ============ 积分榜 ============

def _compute_standings(matches: list, is_tournament: bool) -> list:
    groups = defaultdict(lambda: defaultdict(lambda: {
        "team": "", "tla": "", "played": 0, "won": 0, "draw": 0, "lost": 0,
        "goals_for": 0, "goals_against": 0, "goal_diff": 0, "points": 0,
    }))

    for m in matches:
        if m["home_score"] is None or m["away_score"] is None:
            continue
        if m["status"] not in ("FINISHED", "FINISHED_ET", "FINISHED_PK"):
            continue

        key = m.get("group", "League") if is_tournament else "League"
        home, away = m["home_team"], m["away_team"]
        gs_h, gs_a = m["home_score"], m["away_score"]

        for team, name, gf, ga, side in [
            (home, home, gs_h, gs_a, "home"),
            (away, away, gs_a, gs_h, "away"),
        ]:
            g = groups[key][name]
            g["team"] = name
            g["tla"] = (m.get(f"{side}_tla", name[:3].upper()) if is_tournament else name[:3].upper())
            g["played"] += 1
            g["goals_for"] += gf
            g["goals_against"] += ga

        if gs_h > gs_a:
            groups[key][home]["won"] += 1
            groups[key][home]["points"] += 3
            groups[key][away]["lost"] += 1
        elif gs_h < gs_a:
            groups[key][away]["won"] += 1
            groups[key][away]["points"] += 3
            groups[key][home]["lost"] += 1
        else:
            groups[key][home]["draw"] += 1
            groups[key][home]["points"] += 1
            groups[key][away]["draw"] += 1
            groups[key][away]["points"] += 1

    result = []
    for g_name in sorted(groups.keys()):
        table = list(groups[g_name].values())
        for t in table:
            t["goal_diff"] = t["goals_for"] - t["goals_against"]
        table.sort(key=lambda t: (-t["points"], -t["goal_diff"], -t["goals_for"]))
        result.append({"group": g_name, "table": table})

    return result


# ============ 查询 ============

def get_standings(competition: str) -> list:
    return get_data(competition)["standings"]


def get_upcoming(competition: str, days: int = 7) -> list:
    data = get_data(competition)
    today = datetime.now().date()
    end = today + timedelta(days=days)
    result = []
    for m in data["matches"]:
        try:
            md = datetime.strptime(m["date"], "%Y-%m-%d").date()
            if today <= md <= end:
                result.append(m)
        except ValueError:
            continue
    return result


def find_match(competition: str, team1: str, team2: str) -> Optional[dict]:
    data = get_data(competition)
    t1, t2 = team1.lower(), team2.lower()
    for m in data["matches"]:
        if t1 in m["home_team"].lower() or t1 in m["away_team"].lower():
            if t2 in m["home_team"].lower() or t2 in m["away_team"].lower():
                return m
    return None


# ============ 预测同步 ============

def auto_sync(competition: str, predictions: list) -> list:
    data = get_data(competition, force_refresh=True)
    updated = []
    for pred in predictions:
        if pred.get("is_correct", "") != "":
            continue
        m = find_match(competition, pred.get("home_team", ""), pred.get("away_team", ""))
        if not m:
            continue
        if m["status"].startswith("FINISHED") and m["home_score"] is not None:
            try:
                from scripts.storage import update_result
            except ImportError:
                from storage import update_result
            update_result(int(pred.get("id", 0)), int(m["home_score"]), int(m["away_score"]))
            updated.append(int(pred.get("id", 0)))
    return updated


# ============ 表格输出 ============

def _table(headers: list, rows: list, aligns: list = None):
    if aligns is None:
        aligns = ["<"] * len(headers)
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(sep)
    cells = [f" {headers[i].ljust(widths[i])} " for i in range(len(headers))]
    print("|" + "|".join(cells) + "|")
    print(sep)
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            s = str(cell)
            cells.append(f" {s.rjust(widths[i])} " if aligns[i] == ">" else f" {s.ljust(widths[i])} ")
        print("|" + "|".join(cells) + "|")
    print(sep)


# ============ CLI ============

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser()
    parser.add_argument("--competition", "-c", default="worldcup",
                        choices=list(COMPETITIONS.keys()),
                        help="赛事代码: worldcup, euro, PL, PD, SA, BL1, FL1")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("matches")
    sub.add_parser("standings")
    sub.add_parser("sync")
    p_find = sub.add_parser("find")
    p_find.add_argument("team1")
    p_find.add_argument("team2")

    args = parser.parse_args()
    comp = args.competition

    if args.cmd == "matches":
        upcoming = get_upcoming(comp, 14)
        cfg = COMPETITIONS[comp]
        print(f"\n  {cfg['name']} 赛程 ({len(upcoming)} 场)\n")
        for date in sorted(set(m["date"] for m in upcoming)):
            day_matches = [m for m in upcoming if m["date"] == date]
            print(f"  === {date} ===")
            headers = ["#", "主队", "客队", "比分", "状态"]
            rows = []
            for m in day_matches:
                score = f"{m['home_score']}-{m['away_score']}" if m['home_score'] is not None else "vs"
                status_map = {"FINISHED": "完赛", "FINISHED_ET": "完赛(加时)", "TIMED": "待开始",
                              "SCHEDULED": "待开始", "IN_PLAY": "进行中"}
                rows.append([str(m["id"]), m["home_team"], m["away_team"],
                             score, status_map.get(m["status"], m["status"])])
            _table(headers, rows, ["<", "<", "<", ">", "<"])
            print()

    elif args.cmd == "standings":
        standings = get_standings(comp)
        print(f"\n  {COMPETITIONS[comp]['name']} 积分榜\n")
        for g in standings:
            print(f"  === {g['group']} ===")
            headers = ["队伍", "场", "胜", "平", "负", "进", "失", "净", "分"]
            rows = []
            for t in g["table"]:
                rows.append([t["tla"], str(t["played"]), str(t["won"]), str(t["draw"]),
                             str(t["lost"]), str(t["goals_for"]), str(t["goals_against"]),
                             f"{t['goal_diff']:+d}", str(t["points"])])
            _table(headers, rows, ["<", ">", ">", ">", ">", ">", ">", ">", ">"])
            print()

    elif args.cmd == "sync":
        try:
            from scripts.storage import get_pending_predictions, get_predictions
        except ImportError:
            from storage import get_pending_predictions, get_predictions
        pending = get_pending_predictions()
        if not pending:
            print("  所有预测都已录入结果")
        else:
            updated = auto_sync(comp, pending)
            print(f"  已同步 {len(updated)} 条" if updated else "  暂无可同步结果")

    elif args.cmd == "find":
        m = find_match(comp, args.team1, args.team2)
        if m:
            print(json.dumps(m, ensure_ascii=False, indent=2))
        else:
            print(f"  未找到 {args.team1} vs {args.team2}")

    else:
        parser.print_help()
