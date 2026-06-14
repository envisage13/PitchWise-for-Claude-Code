"""
赛前战术研究模块
从 RotoWire 等来源搜索球队战术分析、预测首发、伤病信息
"""
import re
import logging
from typing import Optional
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}

# 已知的 RotoWire 世界杯小组预览文章 URL（按组）
ROTOWIRE_GROUP_PREVIEWS = {
    "A": "https://www.rotowire.com/soccer/article/2026-world-cup-group-a-preview-mexico-south-korea-czech-republic-south-africa-tactics-lineups-odds-109044",
    "B": "https://www.rotowire.com/soccer/article/2026-world-cup-group-b-preview-switzerland-canada-qatar-bosnia-tactics-lineups-odds-109043",
    "C": "https://www.rotowire.com/soccer/article/2026-world-cup-group-c-preview-brazil-morocco-scotland-haiti-tactics-lineups-set-pieces-odds-109040",
    "D": "https://www.rotowire.com/soccer/article/2026-world-cup-group-d-preview-usa-turkey-australia-paraguay-tactics-lineups-odds-109041",
    "E": "https://www.rotowire.com/soccer/article/2026-world-cup-group-e-preview-germany-ecuador-ivory-coast-curacao-tactics-lineups-set-pieces-odds-109042",
    "F": "https://www.rotowire.com/soccer/article/2026-world-cup-group-f-preview-netherlands-sweden-japan-tunisia-tactics-lineups-odds-109045",
}


def _fetch(url: str) -> Optional[str]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        return r.text if r.status_code == 200 else None
    except Exception as e:
        logger.warning(f"请求失败 {url[:80]}: {e}")
        return None


def _extract_tactical_paragraphs(soup: BeautifulSoup, team_name: str) -> list[str]:
    """从文章 HTML 中提取与某队相关的战术段落"""
    article = soup.find("article") or soup.find("div", class_=re.compile("article|content|body|post"))
    if not article:
        return []

    relevant = []
    team_keywords = team_name.lower().split()

    for tag in article.find_all(["p", "h2", "h3", "h4", "li"]):
        text = tag.get_text(strip=True)
        if len(text) < 60:
            continue

        text_lower = text.lower()

        # 匹配战术相关内容
        tactical_kw = ["formation", "lineup", "tactic", "attack", "defense", "midfield",
                       "starting", "injury", "absence", "formation", "style", "press",
                       "counter", "possession", "wing", "striker", "goalkeeper",
                       "captain", "coach", "manager", "key player", "star"]

        if any(kw in team_name.lower() for kw in team_keywords):
            if any(kw in text_lower for kw in tactical_kw):
                # 清理文本
                clean = re.sub(r'\s+', ' ', text)[:500]
                relevant.append(clean)

    return relevant[:20]


def _extract_formation(soup: BeautifulSoup) -> Optional[str]:
    """提取阵型信息"""
    text = soup.get_text()
    formations = re.findall(r'(\d[-\d]+\d)\s*(?:formation|shape|system|setup)', text[:10000])
    if formations:
        return formations[0]
    # 直接搜索常见阵型
    for fmt in ["4-3-3", "4-2-3-1", "4-4-2", "3-5-2", "3-4-3", "4-1-4-1", "5-3-2"]:
        if fmt in text[:10000]:
            return fmt
    return None


def _extract_injuries(soup: BeautifulSoup, team_name: str) -> list[str]:
    """提取伤病信息"""
    text = soup.get_text()
    injuries = []

    # 找包含伤病关键字的句子
    injury_kw = ["injured", "injury", "out", "absent", "ruled out", "doubt", "unavailable", "hamstring", "knee", "ankle"]
    sentences = re.split(r'(?<=[.!?])\s+', text[:15000])

    for sent in sentences:
        if len(sent) < 40:
            continue
        sent_lower = sent.lower()
        if team_name.lower() in sent_lower:
            if any(kw in sent_lower for kw in injury_kw):
                clean = re.sub(r'\s+', ' ', sent.strip())[:300]
                if clean not in injuries:
                    injuries.append(clean)

    return injuries[:5]


def research_match(home_team: str, away_team: str, group: str = "") -> dict:
    """
    搜索比赛相关战术分析

    Returns:
        {
            "home_tactics": [...],     # 主队战术要点
            "away_tactics": [...],     # 客队战术要点
            "home_formation": "4-3-3",  # 主队预测阵型
            "away_formation": "4-2-3-1",
            "home_injuries": [...],     # 主队伤病
            "away_injuries": [...],
            "source_url": "https://...", # 数据来源
        }
    """
    result = {
        "home_tactics": [],
        "away_tactics": [],
        "home_formation": None,
        "away_formation": None,
        "home_injuries": [],
        "away_injuries": [],
        "source_url": "",
        "has_data": False,
    }

    def _parse_article(soup, source_url):
        result["source_url"] = source_url
        result["has_data"] = True
        for team in [home_team, away_team]:
            tactics = _extract_tactical_paragraphs(soup, team)
            formation = _extract_formation(soup)
            injuries = _extract_injuries(soup, team)
            if team == home_team:
                result["home_tactics"] = tactics[:10]
                result["home_formation"] = formation
                result["home_injuries"] = injuries
            else:
                result["away_tactics"] = tactics[:10]
                result["away_formation"] = formation
                result["away_injuries"] = injuries

    # 方法1：尝试 RotoWire 小组预览
    if group and group in ROTOWIRE_GROUP_PREVIEWS:
        url = ROTOWIRE_GROUP_PREVIEWS[group]
        logger.info(f"尝试 RotoWire: {url[:80]}...")
        html = _fetch(url)
        if html:
            soup = BeautifulSoup(html, "lxml")
            _parse_article(soup, url)
            logger.info(f"RotoWire: 提取 {len(result['home_tactics'])} + {len(result['away_tactics'])} 条战术要点")

    return result


def format_for_prompt(research: dict, home_team: str, away_team: str) -> str:
    """将研究结果格式化为 prompt 可用的文本"""
    if not research.get("has_data"):
        return ""

    lines = []
    lines.append("## 赛前战术研究（来源：RotoWire）")

    # 阵型
    formations = []
    if research.get("home_formation"):
        formations.append(f"{home_team} 预测阵型: {research['home_formation']}")
    if research.get("away_formation"):
        formations.append(f"{away_team} 预测阵型: {research['away_formation']}")
    if formations:
        lines.append("### 预测阵型")
        for f in formations:
            lines.append(f"- {f}")

    # 主队战术
    if research.get("home_tactics"):
        lines.append(f"\n### {home_team} 战术要点")
        for t in research["home_tactics"][:6]:
            # 截取关键句
            short = t[:400]
            lines.append(f"- {short}")

    # 客队战术
    if research.get("away_tactics"):
        lines.append(f"\n### {away_team} 战术要点")
        for t in research["away_tactics"][:6]:
            short = t[:400]
            lines.append(f"- {short}")

    # 伤病
    all_injuries = []
    if research.get("home_injuries"):
        all_injuries.extend([f"({home_team}) {i}" for i in research["home_injuries"][:3]])
    if research.get("away_injuries"):
        all_injuries.extend([f"({away_team}) {i}" for i in research["away_injuries"][:3]])
    if all_injuries:
        lines.append("\n### 伤病/缺阵信息")
        for i in all_injuries:
            lines.append(f"- {i[:250]}")

    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 测试：巴西 vs 摩洛哥的数据
    print("=== 测试: Brazil vs Morocco (Group C) ===")
    r = research_match("Brazil", "Morocco", group="C")
    print(f"Has data: {r['has_data']}")
    print(f"Home tactics count: {len(r['home_tactics'])}")
    print(f"Away tactics count: {len(r['away_tactics'])}")

    prompt = format_for_prompt(r, "Brazil", "Morocco")
    print(prompt[:1200])
