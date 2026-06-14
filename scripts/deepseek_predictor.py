"""
DeepSeek API 足球预测器
注入历史球队数据丰富 prompt
"""
import os
import json
import time
import logging
import requests
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

LEAGUE_FEATURE_FILES = {
    "英超": "features_PL2024.csv",
    "西甲": "features_PD2024.csv",
    "意甲": "features_SA2024.csv",
    "德甲": "features_BL12024.csv",
    "法甲": "features_FL12024.csv",
}

# 中文队名 → 英文队名（用于匹配历史数据）
TEAM_NAME_MAP = {
    "曼彻斯特城": "Manchester City FC", "曼城": "Manchester City FC",
    "利物浦": "Liverpool FC",
    "阿森纳": "Arsenal FC",
    "切尔西": "Chelsea FC",
    "曼联": "Manchester United FC",
    "托特纳姆": "Tottenham Hotspur FC", "热刺": "Tottenham Hotspur FC",
    "纽卡斯尔": "Newcastle United FC",
    "布莱顿": "Brighton & Hove Albion FC",
    "阿斯顿维拉": "Aston Villa FC",
    "水晶宫": "Crystal Palace FC",
    "布伦特福德": "Brentford FC",
    "富勒姆": "Fulham FC",
    "狼队": "Wolverhampton Wanderers FC",
    "伯恩茅斯": "AFC Bournemouth",
    "诺丁汉森林": "Nottingham Forest FC",
    "埃弗顿": "Everton FC",
    "西汉姆": "West Ham United FC", "西汉姆联": "West Ham United FC",
    "皇家马德里": "Real Madrid CF",
    "巴塞罗那": "FC Barcelona",
    "马德里竞技": "Atlético de Madrid",
    "塞维利亚": "Sevilla FC",
    "瓦伦西亚": "Valencia CF",
    "皇家贝蒂斯": "Real Betis Balompié",
    "皇家社会": "Real Sociedad de Fútbol",
    "毕尔巴鄂竞技": "Athletic Club",
    "比利亚雷亚尔": "Villarreal CF",
    "拜仁慕尼黑": "FC Bayern München",
    "多特蒙德": "Borussia Dortmund",
    "莱比锡红牛": "RB Leipzig",
    "勒沃库森": "Bayer 04 Leverkusen",
    "门兴格拉德巴赫": "Borussia Mönchengladbach", "门兴": "Borussia Mönchengladbach",
    "沃尔夫斯堡": "VfL Wolfsburg",
    "法兰克福": "Eintracht Frankfurt",
    "斯图加特": "VfB Stuttgart",
    "弗赖堡": "SC Freiburg",
    "尤文图斯": "Juventus FC",
    "国际米兰": "FC Internazionale Milano",
    "AC米兰": "AC Milan",
    "那不勒斯": "SSC Napoli",
    "罗马": "AS Roma",
    "拉齐奥": "SS Lazio",
    "亚特兰大": "Atalanta BC",
    "佛罗伦萨": "ACF Fiorentina",
    "都灵": "Torino FC",
    "博洛尼亚": "Bologna FC 1909",
    "巴黎圣日耳曼": "Paris Saint-Germain FC",
    "马赛": "Olympique de Marseille",
    "摩纳哥": "AS Monaco FC",
    "里昂": "Olympique Lyonnais",
    "尼斯": "OGC Nice",
    "雷恩": "Stade Rennais FC",
    "兰斯": "Stade de Reims",
    "斯特拉斯堡": "RC Strasbourg Alsace",
    "朗斯": "RC Lens",
    "里尔": "LOSC Lille",
}


class DeepSeekPredictor:
    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self.api_key = api_key
        self.model = model
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        self._features_cache = {}

    # ========== 历史数据加载 ==========

    def _load_features(self, league_name: str) -> pd.DataFrame | None:
        """延迟加载联赛球队特征"""
        if league_name in self._features_cache:
            return self._features_cache[league_name]

        filename = LEAGUE_FEATURE_FILES.get(league_name)
        if not filename:
            return None

        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath):
            logger.warning(f"特征文件不存在: {filepath}")
            return None

        try:
            df = pd.read_csv(filepath, index_col=0)
            self._features_cache[league_name] = df
            logger.info(f"加载 {league_name} 特征数据: {len(df)} 支球队")
            return df
        except Exception as e:
            logger.error(f"加载特征文件失败 {filepath}: {e}")
            return None

    def _resolve_team_name(self, name: str) -> str:
        """中文队名转英文，用于匹配 CSV"""
        return TEAM_NAME_MAP.get(name, name)

    def _get_team_stats(self, team_name: str, league_name: str) -> dict | None:
        """获取一支球队的历史统计数据"""
        df = self._load_features(league_name)
        if df is None:
            return None

        english_name = self._resolve_team_name(team_name)
        if english_name in df.index:
            row = df.loc[english_name]
            return {
                "主场场次": int(row.get("home_matches_played", 0)),
                "主场场均进球": round(float(row.get("home_goals_scored_avg", 0)), 2),
                "主场场均失球": round(float(row.get("home_goals_conceded_avg", 0)), 2),
                "主场胜率": f"{float(row.get('home_win_rate', 0)) * 100:.0f}%",
                "主场平率": f"{float(row.get('home_draw_rate', 0)) * 100:.0f}%",
                "主场负率": f"{float(row.get('home_loss_rate', 0)) * 100:.0f}%",
                "客场场次": int(row.get("away_matches_played", 0)),
                "客场场均进球": round(float(row.get("away_goals_scored_avg", 0)), 2),
                "客场场均失球": round(float(row.get("away_goals_conceded_avg", 0)), 2),
                "客场胜率": f"{float(row.get('away_win_rate', 0)) * 100:.0f}%",
                "客场平率": f"{float(row.get('away_draw_rate', 0)) * 100:.0f}%",
                "客场负率": f"{float(row.get('away_loss_rate', 0)) * 100:.0f}%",
                "综合胜率": f"{float(row.get('overall_win_rate', 0)) * 100:.0f}%",
                "近期状态": f"{float(row.get('recent_form', 0)):.2f}",
            }

        # 反向搜索：部分匹配
        for idx in df.index:
            if english_name.lower() in idx.lower() or idx.lower() in english_name.lower():
                row = df.loc[idx]
                return {
                    "主场胜率": f"{float(row.get('home_win_rate', 0)) * 100:.0f}%",
                    "客场胜率": f"{float(row.get('away_win_rate', 0)) * 100:.0f}%",
                    "综合胜率": f"{float(row.get('overall_win_rate', 0)) * 100:.0f}%",
                    "近期状态": f"{float(row.get('recent_form', 0)):.2f}",
                }

        return None

    # ========== Prompt 构建 ==========

    @staticmethod
    def _is_tournament(league_name: str) -> bool:
        """判断是否为杯赛/锦标赛"""
        keywords = ["世界杯", "欧洲杯", "美洲杯", "亚洲杯", "欧冠", "欧联",
                    "World Cup", "EURO", "Copa", "Champions League", "杯"]
        return any(kw in league_name for kw in keywords)

    def _build_prompt(self, home_team: str, away_team: str, league_name: str,
                      home_odds: float, draw_odds: float, away_odds: float) -> str:
        """构建富含历史数据的分析 prompt"""
        is_cup = self._is_tournament(league_name)
        home_stats = self._get_team_stats(home_team, league_name)
        away_stats = self._get_team_stats(away_team, league_name)

        if is_cup:
            lines = [
                "你是一位专业的国际足球赛事分析师，精通世界杯、洲际杯赛等锦标赛分析。"
                "请基于球队实力、历史交锋、大赛经验和赔率，对这场国家队比赛进行深度预测。",
                "",
                f"## 比赛信息",
                f"- 赛事: {league_name}",
                f"- 主队: {home_team} (主队即左侧队伍)",
                f"- 客队: {away_team} (客队即右侧队伍)",
                f"- 赔率: 主胜 {home_odds} / 平局 {draw_odds} / 客胜 {away_odds}",
                "",
                "## 分析要点（请综合以下维度）",
                "- FIFA 世界排名与近期大赛成绩",
                "- 球队阵容身价、核心球员与伤病情况",
                "- 历史交锋记录（包括友谊赛和正式比赛）",
                "- 小组出线形势 / 淘汰赛策略（如有）",
                "- 中立场地因素（锦标赛通常在中立场地进行）",
                "- 赔率隐含概率与实际胜率的偏差",
            ]
        else:
            lines = [
                "你是一位专业的足球比赛分析师。请基于以下数据，对这场比赛进行深度分析预测。",
                "",
                f"## 比赛信息",
                f"- 主队: {home_team}",
                f"- 客队: {away_team}",
                f"- 联赛: {league_name}",
                f"- 赔率: 主胜 {home_odds} / 平局 {draw_odds} / 客胜 {away_odds}",
            ]

        if home_stats:
            lines.append("")
            lines.append(f"## {home_team} 历史数据（近10场）")
            for k, v in home_stats.items():
                lines.append(f"- {k}: {v}")

        if away_stats:
            lines.append("")
            lines.append(f"## {away_team} 历史数据（近10场）")
            for k, v in away_stats.items():
                lines.append(f"- {k}: {v}")

        if not is_cup and not home_stats and not away_stats:
            lines.append("")
            lines.append("（暂无两队历史数据，请基于球队知名度和赔率进行分析）")

        lines.append("")
        lines.append("## 请按以下格式输出预测:")
        lines.append("")
        lines.append("### 一、胜平负预测")
        lines.append("- 推荐: [主胜/平局/客胜]")
        lines.append("- 置信度: [1-10]")
        lines.append("- 理由: （简要说明）")
        lines.append("")
        lines.append("### 二、比分预测")
        lines.append("- 最可能比分: X-X")
        lines.append("- 其他可能: X-X, X-X")
        lines.append("")
        lines.append("### 三、进球数预测")
        lines.append("- 总进球区间: [0-1球/2-3球/4球以上]")
        lines.append("")

        if is_cup:
            lines.append("### 四、大赛特别分析")
            lines.append("- 小组出线影响/晋级形势:")
            lines.append("- 加时赛/点球可能性:")
            lines.append("- 战术关键点:")
            lines.append("")
            lines.append("### 五、风险提示")
            lines.append("- （一句话风险说明）")
        else:
            lines.append("### 四、风险提示")
            lines.append("- （一句话风险说明）")

        return "\n".join(lines)

    # ========== API 调用 ==========

    def _call_api(self, prompt: str) -> str | None:
        """调用 DeepSeek Chat API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一位专业的足球比赛分析师，擅长基于数据和赔率进行比赛预测。请使用中文回答。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 2000,
        }

        for attempt in range(3):
            try:
                logger.info(f"DeepSeek API 请求 (第 {attempt + 1} 次)")
                resp = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
                logger.info(f"响应状态: {resp.status_code}")

                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    logger.info("DeepSeek 分析完成")
                    return content.strip()

                elif resp.status_code == 429:
                    wait = 2 ** attempt + 1
                    logger.warning(f"速率限制，等待 {wait}s")
                    time.sleep(wait)
                    continue

                else:
                    logger.error(f"API 错误 {resp.status_code}: {resp.text[:200]}")
                    if attempt == 2:
                        return None

            except requests.exceptions.Timeout:
                logger.warning(f"请求超时 (第 {attempt + 1} 次)")
            except Exception as e:
                logger.error(f"API 调用异常: {e}")
                if attempt == 2:
                    return None

        return None

    # ========== 预测入口 ==========

    def predict(self, home_team: str, away_team: str, league_name: str = "未知联赛",
                home_odds: float = 2.0, draw_odds: float = 3.2, away_odds: float = 3.5,
                research_text: str = "") -> str | None:
        """
        单场预测，返回 AI 分析文本
        research_text: 可选的赛前战术研究文本（来自 RotoWire 等）
        """
        home_odds = float(home_odds) if home_odds else 2.0
        draw_odds = float(draw_odds) if draw_odds else 3.2
        away_odds = float(away_odds) if away_odds else 3.5

        prompt = self._build_prompt(home_team, away_team, league_name,
                                    home_odds, draw_odds, away_odds)

        # 注入战术研究数据
        if research_text:
            prompt = research_text + "\n\n" + prompt

        return self._call_api(prompt)


if __name__ == "__main__":
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("请设置 DEEPSEEK_API_KEY 环境变量")
        exit(1)

    p = DeepSeekPredictor(api_key)

    # 测试：有历史数据的比赛
    result = p.predict("曼彻斯特城", "利物浦", "英超", 1.80, 3.50, 4.20)
    if result:
        print("=" * 60)
        print(result)
    else:
        print("预测失败")
