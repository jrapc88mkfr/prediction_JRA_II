# rating.py

import re

from records import get_record, time_to_seconds

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
        "last3f": None,
        "baba": None
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

    # タイム・馬場状態
    m = re.search(r'\d+(?:芝|ダ)\s+(\d+:\d+\.\d+)([良稍重不])?', text)

    if m:
        result["time"] = m.group(1)
        result["baba"] = m.group(2)

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
# 馬場差補正
#   records.py のレコードは良馬場基準とみなし、
#   稍重・重・不良のタイムを良馬場換算してから
#   レコードと比較する。
#
#   芝：馬場が悪くなるほど時計が掛かる（遅くなる）
#       → 補正を引いて良馬場換算（＝タイムを良くする）
#   ダート：馬場が悪くなるほど（締まって）時計が速くなりやすい
#       → 補正を足して良馬場換算（＝タイムを悪くする）
#
#   ※実績データによる検証は未実施の経験則の初期値。
#     今後の実績を見て調整すること。
# ==========================================

BABA_CORRECTION_SEC = {
    ("芝", "良"): 0.0,
    ("芝", "稍"): 0.5,
    ("芝", "重"): 1.5,
    ("芝", "不"): 2.5,

    ("ダ", "良"): 0.0,
    ("ダ", "稍"): -0.3,
    ("ダ", "重"): -0.8,
    ("ダ", "不"): -1.2,
}


def baba_correction_seconds(surface, baba):
    """
    良馬場換算のための補正秒数を返す。
    surface/baba が取れない組み合わせは補正なし（0.0）。
    """
    if not surface or not baba:
        return 0.0

    return BABA_CORRECTION_SEC.get((surface, baba), 0.0)


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

        # 馬場状態を良馬場換算に補正
        race_sec -= baba_correction_seconds(
            info.get("surface"),
            info.get("baba")
        )

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


# 2026/09/21 変更
# ==========================================
# A：現在能力指数
# ==========================================

def calc_current_ability(r1, r2, r3):
    """
    前3走から現在能力を算出する。

    前走   35%
    前々走 35%
    3走前  30%

    欠損レースがある場合は、
    有効なレースだけでウェイトを再配分する。
    """

    values = [
        (r1, 0.35),
        (r2, 0.35),
        (r3, 0.30)
    ]

    valid = [
        (float(v), w)
        for v, w in values
        if v is not None and float(v) > 0
    ]

    if not valid:
        return 0

    total_weight = sum(w for _, w in valid)

    score = sum(
        v * w
        for v, w in valid
    ) / total_weight

    return round(score)

# ==========================================
# B：上昇・下降度
# ==========================================

def calc_trend_score(r1, r2, r3):
    """
    前3走の指数から上昇・下降傾向を算出する。

    Bは「能力そのもの」ではなく、
    最近の調子の方向性を軽く反映する。

    前々走 → 前走を重視
    3走前 → 前々走も加味

    Bは最大±3点に制限する。
    """

    trend = 0.0

    # 前々走 → 前走
    if (
        r1 is not None and
        r2 is not None and
        r1 > 0 and
        r2 > 0
    ):
        trend += 0.15 * (float(r1) - float(r2))

    # 3走前 → 前々走
    if (
        r2 is not None and
        r3 is not None and
        r2 > 0 and
        r3 > 0
    ):
        trend += 0.10 * (float(r2) - float(r3))

    # 上昇・下降度は最大±3点
    trend = max(-3, min(3, trend))

    return round(trend, 1)

def horse_rating(row):
    """A：現在能力指数"""

    r1 = race_rating(row.get("前走", ""))
    r2 = race_rating(row.get("前々走", ""))
    r3 = race_rating(row.get("3走前", ""))

    return calc_current_ability(r1, r2, r3)


def horse_trend(row):
    """B：上昇下降度"""

    r1 = race_rating(row.get("前走", ""))
    r2 = race_rating(row.get("前々走", ""))
    r3 = race_rating(row.get("3走前", ""))

    return calc_trend_score(r1, r2, r3)


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