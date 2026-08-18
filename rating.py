# rating.py

import re

from records import get_record
from records import time_to_seconds


# ==========================================
# レース結果解析
# ==========================================

def parse_race_result(text):

    text = str(text)

    result = {
        "track": None,
        "surface": None,
        "distance": None,
        "time": None,
        "margin": None,
        "rank": None,
        "popularity": None,
        "last3f": None
    }

    tracks = [
        "東京", "中山", "阪神", "京都", "中京",
        "新潟", "札幌", "函館", "福島", "小倉"
    ]

    for track in tracks:
        if track in text:
            result["track"] = track
            break

    # 距離・芝ダ
    m = re.search(r'(\d+)(芝|ダ)', text)

    if m:
        result["distance"] = int(m.group(1))
        result["surface"] = m.group(2)

    # タイム
    m = re.search(r'\d+(?:芝|ダ)\s+(\d+:\d+\.\d+)', text)

    if m:
        result["time"] = m.group(1)

    # 着順
    m = re.search(r'(\d+)着', text)

    if m:
        result["rank"] = int(m.group(1))

    # 人気
    m = re.search(r'(\d+)番人気', text)

    if m:
        result["popularity"] = int(m.group(1))

    # 上がり
    m = re.search(r'3F\s+(\d+\.\d+)', text)

    if m:
        result["last3f"] = float(m.group(1))

    # 着差
    m = re.search(r'\(([\d\.]+)\)\s*$', text)

    if m:
        result["margin"] = float(m.group(1))

    return result


# ==========================================
# タイム指数
# ==========================================

def calc_time_rating(info):

    if not info["time"]:
        return 50

    record = get_record(
        info["track"],
        info["surface"],
        info["distance"]
    )

    if not record:
        return 50

    try:

        race_sec = time_to_seconds(info["time"])
        record_sec = time_to_seconds(record)

        diff = race_sec - record_sec

        score = 100 - diff * 10

        score = round(score)

        score = max(0, min(120, score))

        return score

    except:
        return 50


# ==========================================
# 着順補正
# ==========================================

def rank_bonus(rank):

    if rank is None:
        return 0

    if rank == 1:
        return 10

    elif rank == 2:
        return 7

    elif rank == 3:
        return 5

    elif rank <= 5:
        return 2

    return 0


# ==========================================
# 人気補正
# 人気以上に走ればプラス
# ==========================================

def popularity_bonus(rank, pop):

    if rank is None:
        return 0

    if pop is None:
        return 0

    return pop - rank


# ==========================================
# 着差補正
# ==========================================

def margin_bonus(margin):

    if margin is None:
        return 0

    if margin <= 0.1:
        return 5

    elif margin <= 0.3:
        return 3

    elif margin <= 0.5:
        return 1

    elif margin <= 1.0:
        return -2

    elif margin <= 2.0:
        return -5

    return -10


# ==========================================
# 上がり補正
# ==========================================

def last3f_bonus(last3f):

    if last3f is None:
        return 0

    if last3f <= 33.0:
        return 12

    elif last3f <= 33.5:
        return 8

    elif last3f <= 34.0:
        return 5

    elif last3f <= 34.5:
        return 3

    elif last3f <= 35.0:
        return 1

    elif last3f <= 36.0:
        return 0

    return -3


# ==========================================
# 1レース指数
# ==========================================

def race_rating(text):

    info = parse_race_result(text)

    score = 0

    score += calc_time_rating(info)

    score += rank_bonus(
        info["rank"]
    )

    # score += popularity_bonus(
    #     info["rank"],
    #     info["popularity"]
    # )

    score += margin_bonus(
        info["margin"]
    )

    score += last3f_bonus(
        info["last3f"]
    )

    return round(score)


# ==========================================
# 前走指数
# ==========================================

def last_race_rating(row):

    return race_rating(
        row.get("前走", "")
    )


# ==========================================
# 過去3走平均指数
# ==========================================

def horse_rating(row):

    scores = []

    for col in ["前走", "前々走", "3走前"]:

        text = row.get(col, "")

        if str(text).strip():

            scores.append(
                race_rating(text)
            )

    if not scores:
        return 0

    return round(
        sum(scores) / len(scores)
    )


# ==========================================
# 単レース指数（1走ごと）
# ==========================================

def single_race_rating(text):

    if not str(text).strip():
        return 0

    return race_rating(text)

# ==========================================
# 能力評価
# ==========================================

def rating_rank(score):

    if score >= 110:
        return "S"

    elif score >= 100:
        return "A"

    elif score >= 90:
        return "B"

    elif score >= 80:
        return "C"

    elif score >= 70:
        return "D"

    return "E"