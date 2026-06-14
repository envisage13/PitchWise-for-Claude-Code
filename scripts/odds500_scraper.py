"""
500.com 赔率爬虫 - 获取竞彩足球比赛和赔率
"""
import re
import logging
from datetime import datetime
from typing import Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://odds.500.com/",
}


def _fetch(url: str) -> Optional[str]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = "gb2312"  # 500.com 使用 GB2312 编码
        return r.text if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"请求失败 {url}: {e}")
        return None


def get_worldcup_matches() -> list[dict]:
    """获取竞彩世界杯比赛列表（含赔率）"""
    html = _fetch("https://odds.500.com/")
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    matches = []

    for tr in soup.select("tr[data-fid]"):
        try:
            fid = tr.get("data-fid", "")
            cid = tr.get("data-cid", "")
            dtime = tr.get("date-dtime", "")

            # 只取世界杯 (cid=3)
            if cid != "3":
                continue

            # 提取队名：td.text_right.no_border > a.team_link 是主队
            #          td.text_left > a.team_link 是客队
            home_a = tr.select_one('.text_right a') or tr.select_one('.text_right')
            away_a = tr.select_one('.text_left a') or tr.select_one('.text_left')

            if not home_a or not away_a:
                continue

            home_team = home_a.get_text(strip=True)
            away_team = away_a.get_text(strip=True)

            # 提取 title 属性作为更准确的队名（title="德国" 可能比显示的文本更长）
            home_title = home_a.get("title", "")
            away_title = away_a.get("title", "")
            if home_title and len(home_title) > len(home_team):
                home_team = home_title
            if away_title and len(away_title) > len(away_team):
                away_team = away_title

            # 跳过非队名行
            if not home_team or len(home_team) > 20 or "析" in home_team:
                continue
            if "VS" in home_team or "vs" in home_team.lower():
                continue

            # 提取比赛编号（如 周日009）
            tds = tr.find_all("td")
            match_num = ""
            for td in tds:
                text = td.get_text(strip=True)
                if "周" in text and any(d in text for d in "一二三四五六日"):
                    match_num = text
                    break

            # 获取赔率
            odds = _get_match_odds(fid)

            matches.append({
                "fid": fid,
                "match_num": match_num,
                "home_team": home_team,
                "away_team": away_team,
                "league": "世界杯",
                "match_time": dtime,
                "home_odds": odds.get("home", 2.0),
                "draw_odds": odds.get("draw", 3.2),
                "away_odds": odds.get("away", 3.5),
            })

            logger.info(f"解析: {home_team} vs {away_team} | {odds}")

        except Exception as e:
            logger.error(f"解析比赛行失败: {e}")
            continue

    return matches


def _get_match_odds(fid: str) -> dict:
    """获取单场比赛的即时平均赔率"""
    url = f"https://odds.500.com/fenxi/ouzhi-{fid}.shtml"
    html = _fetch(url)
    if not html:
        return {}

    try:
        soup = BeautifulSoup(html, "lxml")
        all_trs = soup.find_all("tr")
        odds_candidates = []

        for tr in all_trs:
            tds = tr.find_all("td")
            nums = []
            for td in tds:
                text = td.get_text(strip=True)
                m = re.match(r'^\d+\.\d{2}$', text)
                if m:
                    nums.append(float(text))

            if len(nums) == 3:
                h, d, a = nums
                # 合理的 1X2 赔率范围:
                # 主胜/客胜至少有一个在 1.0-5.0（正常竞争范围）
                # 平局在 2.0-20.0
                # 不让极端赔率污染（如 90+ 的客胜只在悬殊比赛中出现）
                has_normal = (1.01 <= h <= 6.0) or (1.01 <= a <= 6.0)
                draw_ok = 2.0 <= d <= 25.0
                if has_normal and draw_ok:
                    odds_candidates.append((h, d, a))

        if odds_candidates:
            # 取最后一组合适的赔率（通常是即时平均）
            h, d, a = odds_candidates[-1]
            return {"home": round(h, 2), "draw": round(d, 2), "away": round(a, 2)}

        # 放宽限制再试
        for tr in all_trs:
            tds = tr.find_all("td")
            nums = []
            for td in tds:
                text = td.get_text(strip=True)
                m = re.match(r'^\d+\.\d{2}$', text)
                if m:
                    nums.append(float(text))
            if len(nums) == 3 and all(1.01 <= n <= 200 for n in nums):
                h, d, a = nums
                # 至少有一个合理的主/客赔率
                if h <= 8.0 or a <= 8.0:
                    if 2.0 <= d <= 30.0:
                        return {"home": round(h, 2), "draw": round(d, 2), "away": round(a, 2)}

    except Exception as e:
        logger.error(f"解析赔率失败 fid={fid}: {e}")

    return {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    matches = get_worldcup_matches()
    print(f"\n获取到 {len(matches)} 场世界杯比赛:\n")
    for i, m in enumerate(matches, 1):
        print(f"  {i}. [{m['match_num']}] {m['home_team']} vs {m['away_team']}")
        print(f"     时间: {m['match_time']} | 赔率: {m['home_odds']}/{m['draw_odds']}/{m['away_odds']}")
        print()
