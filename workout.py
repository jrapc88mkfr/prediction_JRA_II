# workout.py

import re

# ==========================
# 時計文字列から終い1F取得
# ==========================

def get_last_furlong(clock_text):

    """
    6F 82.4-66.1-51.1-37.1-11.5（馬なり）
    ↓
    11.5
    """

    if not clock_text:
        return None

    nums = re.findall(r'\d+\.\d+', str(clock_text))

    if not nums:
        return None

    return float(nums[-1])


# ==========================
# 調教コース補正
# ==========================

def course_bonus(place):

    place = str(place)

    if "CW" in place:
        return 10

    elif "ウッド" in place:
        return 10

    elif "坂路" in place:
        return 15

    elif "ポリ" in place:
        return 5

    return 0


# ==========================
# 内容補正
# ==========================

def content_bonus(content):

    content = str(content)

    if "一杯" in content:
        return 20

    elif "強め" in content:
        return 15

    elif "G前気合付" in content:
        return 10

    elif "馬なり" in content:
        return 7

    return 0


# ==========================
# 終い評価
# ==========================

def last1f_score(last1f):

    if last1f is None:
        return 0

    if last1f <= 11.0:
        return 70

    elif last1f <= 11.5:
        return 60

    elif last1f <= 12.0:
        return 50

    elif last1f <= 12.5:
        return 40

    elif last1f <= 13.0:
        return 25

    return 0


# ==========================
# 追切指数
# ==========================

def calc_workout_score(row):

    clock = row.get("時計", "")
    place = row.get("調教場所・馬場", "")
    content = row.get("内容", "")

    score = 0

    last1f = get_last_furlong(clock)

    score += last1f_score(last1f)

    score += course_bonus(place)

    score += content_bonus(content)

    return score


# ==========================
# 評価ランク
# ==========================

def score_to_rank(score):

    if score >= 80:
        return "S"

    elif score >= 65:
        return "A"

    elif score >= 50:
        return "B"

    elif score >= 35:
        return "C"

    return "D"


# ==========================
# 行から評価取得
# ==========================

def get_workout_rank(row):

    score = calc_workout_score(row)

    return score_to_rank(score)