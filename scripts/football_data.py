"""
football-data.org API 集成
提供比赛数据、实时比分、积分榜
"""
import logging
from datetime import datetime
from typing import Optional
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"
API_KEY = ""  # 运行时注入

HEADERS_TEMPLATE = {"X-Auth-Token": ""}

WC_COMPETITION_ID = 2000  # FIFA World Cup


def init(api_key: str):
    global API_KEY
    API_KEY = api_key
    HEADERS_TEMPLATE["X-Auth-Token"] = api_key


def _get(endpoint: str, params: dict = None) -> Optional[dict]:
    try:
        r = requests.get(
            f"{BASE_URL}/{endpoint}",
            headers=HEADERS_TEMPLATE,
            params=params,
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 403:
            logger.warning(f"无权限访问 {endpoint}（需要更高订阅级别）")
            return None
        else:
            logger.error(f"API {endpoint} 返回 {r.status_code}")
            return None
    except Exception as e:
        logger.error(f"API 请求失败 {endpoint}: {e}")
        return None


def get_worldcup_matches(date_from: str = None, date_to: str = None) -> list[dict]:
    """获取世界杯比赛列表（含实时比分）"""
    params = {}
    if date_from:
        params["dateFrom"] = date_from
    if date_to:
        params["dateTo"] = date_to

    data = _get(f"competitions/{WC_COMPETITION_ID}/matches", params)
    if not data:
        return []

    matches = []
    for m in data.get("matches", []):
        # 转换 UTC 时间为北京时间
        utc_str = m.get("utcDate", "")
        bj_time = ""
        if utc_str:
            try:
                utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                bj_dt = utc_dt.replace(tzinfo=None)  # UTC+0
                # football-data.org 时间已经是 UTC，北京时间 +8
                from datetime import timedelta
                bj_dt = bj_dt + timedelta(hours=8)
                bj_time = bj_dt.strftime("%m-%d %H:%M")
            except Exception:
                bj_time = utc_str[:16]

        matches.append({
            "match_id": str(m.get("id", "")),
            "home_team": m.get("homeTeam", {}).get("name", ""),
            "away_team": m.get("awayTeam", {}).get("name", ""),
            "home_tla": m.get("homeTeam", {}).get("tla", ""),
            "away_tla": m.get("awayTeam", {}).get("tla", ""),
            "home_score": m.get("score", {}).get("fullTime", {}).get("home"),
            "away_score": m.get("score", {}).get("fullTime", {}).get("away"),
            "half_home": m.get("score", {}).get("halfTime", {}).get("home"),
            "half_away": m.get("score", {}).get("halfTime", {}).get("away"),
            "status": m.get("status", ""),
            "stage": m.get("stage", ""),
            "group": (m.get("group") or "").replace("GROUP_", ""),
            "utc_date": utc_str,
            "bj_time": bj_time,
        })

    return matches


def get_standings() -> list[dict]:
    """获取世界杯小组积分榜"""
    data = _get(f"competitions/{WC_COMPETITION_ID}/standings")
    if not data:
        return []

    groups = []
    for g in data.get("standings", []):
        group_name = (g.get("group") or "").replace("GROUP_", "")
        table = []
        for row in g.get("table", []):
            table.append({
                "position": row.get("position"),
                "team": row.get("team", {}).get("name", ""),
                "tla": row.get("team", {}).get("tla", ""),
                "played": row.get("playedGames"),
                "won": row.get("won"),
                "draw": row.get("draw"),
                "lost": row.get("lost"),
                "goals_for": row.get("goalsFor"),
                "goals_against": row.get("goalsAgainst"),
                "goal_diff": row.get("goalDifference"),
                "points": row.get("points"),
            })
        groups.append({"group": group_name, "table": table})

    return groups


# 中文队名 → TLA (three-letter acronym) 用于精确匹配
CN_TO_TLA = {
    "德国": "GER", "荷兰": "NED", "日本": "JPN", "巴西": "BRA",
    "阿根廷": "ARG", "英格兰": "ENG", "法国": "FRA", "西班牙": "ESP",
    "意大利": "ITA", "葡萄牙": "POR", "比利时": "BEL", "克罗地亚": "CRO",
    "乌拉圭": "URY", "哥伦比亚": "COL", "墨西哥": "MEX", "美国": "USA",
    "摩洛哥": "MAR", "塞内加尔": "SEN", "突尼斯": "TUN", "阿尔及利亚": "ALG",
    "喀麦隆": "CMR", "加纳": "GHA", "科特迪瓦": "CIV", "尼日利亚": "NGA",
    "南非": "RSA", "埃及": "EGY", "韩国": "KOR", "澳大利亚": "AUS",
    "瑞典": "SWE", "挪威": "NOR", "丹麦": "DEN", "波兰": "POL",
    "捷克": "CZE", "奥地利": "AUT", "塞尔维亚": "SRB", "乌克兰": "UKR",
    "卡塔尔": "QAT", "沙特阿拉伯": "KSA", "伊朗": "IRN", "伊拉克": "IRQ",
    "加拿大": "CAN", "新西兰": "NZL", "海地": "HAI", "牙买加": "JAM",
    "库拉索": "CUW", "佛得角": "CPV", "刚果(金)": "COD", "巴拿马": "PAN",
    "约旦": "JOR", "乌兹别克斯坦": "UZB", "巴拉圭": "PAR", "波黑": "BIH",
    "土耳其": "TUR", "苏格兰": "SCO", "瑞典": "SWE",
}


def find_match_by_teams(matches: list[dict], home: str, away: str) -> Optional[dict]:
    """根据队名模糊匹配比赛（支持中文和英文名）"""
    # 方法1: 中文名→TLA 精确匹配
    home_tla = CN_TO_TLA.get(home.strip(), "")
    away_tla = CN_TO_TLA.get(away.strip(), "")
    if home_tla and away_tla:
        for m in matches:
            if m["home_tla"] == home_tla and m["away_tla"] == away_tla:
                return m

    # 方法2: 模糊文本匹配
    for m in matches:
        h = m["home_team"].lower()
        a = m["away_team"].lower()
        home_l = home.lower()
        away_l = away.lower()
        if (home_l in h or h in home_l) and (away_l in a or a in away_l):
            return m

    return None


def auto_update_results(predictions: list[dict]) -> list[dict]:
    """用 football-data.org 实时比分自动更新预测结果，返回被更新的预测 ID 列表"""
    if not predictions:
        return []

    # 获取近期所有比赛
    from datetime import date
    today = date.today().isoformat()
    matches = get_worldcup_matches(date_from="2026-06-11", date_to=today)

    updated = []
    for pred in predictions:
        # 跳过已有结果的
        if pred.get("is_correct", "") != "":
            continue

        m = find_match_by_teams(matches, pred.get("home_team", ""), pred.get("away_team", ""))
        if not m:
            continue

        if m["status"] == "FINISHED" and m["home_score"] is not None:
            from scripts.storage import update_result
            update_result(
                int(pred.get("id", 0)),
                int(m["home_score"]),
                int(m["away_score"]),
            )
            updated.append(int(pred.get("id", 0)))
            logger.info(f"自动更新 ID={pred['id']}: {m['home_team']} {m['home_score']}-{m['away_score']} {m['away_team']}")

    return updated


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)

    key = os.environ.get("FOOTBALL_DATA_KEY", "")
    if not key:
        print("请设置 FOOTBALL_DATA_KEY 环境变量")
        exit(1)

    init(key)

    print("=== 今日世界杯比赛 ===")
    matches = get_worldcup_matches("2026-06-14", "2026-06-14")
    for m in matches:
        score = f"{m['home_score']}-{m['away_score']}" if m['home_score'] is not None else "vs"
        print(f"  {m['bj_time']} | {m['home_team']} {score} {m['away_team']} | {m['status']} | {m['group']}")

    print("\n=== 积分榜 ===")
    for g in get_standings():
        print(f"\n  Group {g['group']}:")
        for t in g["table"]:
            print(f"    {t['position']}. {t['tla']}  {t['played']}场 {t['won']}胜{t['draw']}平{t['lost']}负  GD:{t['goal_diff']:+d}  {t['points']}分")
