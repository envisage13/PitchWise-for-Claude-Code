"""
CSV 存储模块 - 预测记录与体彩缓存
"""
import os
import csv
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PREDICTIONS_FILE = os.path.join(DATA_DIR, "predictions.csv")
LOTTERY_CACHE_FILE = os.path.join(DATA_DIR, "lottery_cache.csv")

PREDICTION_COLUMNS = [
    "id", "home_team", "away_team", "league_name",
    "home_odds", "draw_odds", "away_odds",
    "ai_analysis", "predicted_result",
    "actual_home_score", "actual_away_score",
    "is_correct", "created_at",
]

LOTTERY_COLUMNS = [
    "match_id", "home_team", "away_team", "league_name",
    "match_time", "home_odds", "draw_odds", "away_odds",
    "fetched_at",
]


def _ensure_file(filepath: str, columns: list[str]):
    """确保 CSV 文件存在，不存在则创建并写入表头"""
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)


def _read_csv(filepath: str) -> list[dict]:
    """读取 CSV 为 dict 列表"""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append_csv(filepath: str, row: dict, columns: list[str]):
    """追加一行到 CSV"""
    _ensure_file(filepath, columns)
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writerow(row)


# ========== 预测记录 ==========

def save_prediction(home_team: str, away_team: str, league_name: str,
                    home_odds: float, draw_odds: float, away_odds: float,
                    ai_analysis: str) -> int:
    """保存预测记录，返回记录 ID"""
    records = _read_csv(PREDICTIONS_FILE)
    new_id = max((int(r.get("id", 0)) for r in records), default=0) + 1

    # 从 AI 分析中提取预测结果
    predicted_result = _extract_prediction(ai_analysis)

    row = {
        "id": str(new_id),
        "home_team": home_team,
        "away_team": away_team,
        "league_name": league_name,
        "home_odds": str(home_odds),
        "draw_odds": str(draw_odds),
        "away_odds": str(away_odds),
        "ai_analysis": ai_analysis.replace("\n", "\\n"),
        "predicted_result": predicted_result,
        "actual_home_score": "",
        "actual_away_score": "",
        "is_correct": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _append_csv(PREDICTIONS_FILE, row, PREDICTION_COLUMNS)
    logger.info(f"预测记录已保存 ID={new_id}")
    return new_id


def _extract_prediction(ai_analysis: str) -> str:
    """从 AI 分析文本中提取胜平负预测"""
    text = ai_analysis.replace("\\n", "\n")
    for line in text.split("\n"):
        line = line.strip()
        if "推荐" in line and (":" in line or "：" in line):
            if "主胜" in line:
                return "主胜"
            elif "客胜" in line:
                return "客胜"
            elif "平局" in line or "平" in line:
                return "平局"
    return "未知"


def update_result(prediction_id: int, home_score: int, away_score: int):
    """更新预测的实际比分和命中状态"""
    records = _read_csv(PREDICTIONS_FILE)
    updated = False

    for r in records:
        if int(r.get("id", 0)) == prediction_id:
            r["actual_home_score"] = str(home_score)
            r["actual_away_score"] = str(away_score)

            # 判断命中：预测结果与实际结果一致
            predicted = r.get("predicted_result", "")
            if home_score > away_score:
                actual = "主胜"
            elif home_score < away_score:
                actual = "客胜"
            else:
                actual = "平局"
            r["is_correct"] = "Y" if predicted == actual else "N"
            updated = True
            break

    if updated:
        _ensure_file(PREDICTIONS_FILE, PREDICTION_COLUMNS)
        with open(PREDICTIONS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=PREDICTION_COLUMNS)
            writer.writeheader()
            writer.writerows(records)
        logger.info(f"ID={prediction_id} 结果已更新")


def get_predictions(limit: int = 20) -> list[dict]:
    """获取最近 N 条预测"""
    records = _read_csv(PREDICTIONS_FILE)
    return records[-limit:]


def get_stats() -> dict:
    """计算预测统计"""
    records = _read_csv(PREDICTIONS_FILE)
    total = len(records)
    if total == 0:
        return {"total": 0, "with_result": 0, "correct": 0,
                "accuracy": 0, "by_result": {}}

    with_result = [r for r in records if r.get("is_correct", "") in ("Y", "N")]
    correct = sum(1 for r in with_result if r["is_correct"] == "Y")

    by_result = {"主胜": {"total": 0, "hit": 0},
                 "平局": {"total": 0, "hit": 0},
                 "客胜": {"total": 0, "hit": 0}}

    for r in with_result:
        p = r.get("predicted_result", "未知")
        if p in by_result:
            by_result[p]["total"] += 1
            if r["is_correct"] == "Y":
                by_result[p]["hit"] += 1

    return {
        "total": total,
        "with_result": len(with_result),
        "correct": correct,
        "accuracy": round(correct / len(with_result) * 100, 1) if with_result else 0,
        "by_result": by_result,
    }


def get_pending_predictions() -> list[dict]:
    """获取尚未录入结果的预测"""
    records = _read_csv(PREDICTIONS_FILE)
    return [r for r in records if r.get("is_correct", "") == ""]


# ========== 体彩比赛缓存 ==========

def cache_lottery_matches(matches: list[dict]):
    """缓存体彩比赛数据"""
    _ensure_file(LOTTERY_CACHE_FILE, LOTTERY_COLUMNS)
    # 覆盖写入
    with open(LOTTERY_CACHE_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOTTERY_COLUMNS)
        writer.writeheader()
        for i, m in enumerate(matches, 1):
            odds = m.get("odds", {}).get("hhad", {})
            row = {
                "match_id": m.get("match_id", f"m{i}"),
                "home_team": m.get("home_team", ""),
                "away_team": m.get("away_team", ""),
                "league_name": m.get("league_name", ""),
                "match_time": m.get("match_time", ""),
                "home_odds": odds.get("h", ""),
                "draw_odds": odds.get("d", ""),
                "away_odds": odds.get("a", ""),
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            writer.writerow(row)
    logger.info(f"已缓存 {len(matches)} 场体彩比赛")


def load_cached_matches() -> list[dict]:
    """读取缓存的体彩比赛"""
    return _read_csv(LOTTERY_CACHE_FILE)
