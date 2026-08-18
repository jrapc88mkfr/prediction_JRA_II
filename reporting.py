import re

# =====================================
# ① 予想ペース
# =====================================

def predict_pace(df, pace_module):
    """
    脚質分布から展開予想
    """

    styles = df.apply(pace_module.get_running_style, axis=1)
    counts = styles.value_counts().to_dict()

    lead = counts.get("逃げ", 0)
    front = counts.get("先行", 0)
    late = counts.get("差し", 0) + counts.get("追込", 0)

    if lead >= 3:
        return "Hペース"
    elif lead == 2:
        return "Mペース"
    elif lead <= 1 and late >= 8:
        return "Sペース"
    else:
        return "Mペース"
    
# =====================================
# 展開ボーナス
# =====================================
def pace_fit_score(style, pace):

    if "Sペース" in pace:
        if style in ["逃げ", "先行"]:
            return 3
        elif style == "差し":
            return 0
        else:
            return -1

    elif "Hペース" in pace:
        if style in ["差し", "追込"]:
            return 3
        elif style == "逃げ":
            return -2
        else:
            return 0

    else:
        return 0

# =====================================
# ② 激走指数
# =====================================
def calc_gekisou_index(row):

    try:
        # =========================
        # 基本データ
        # =========================
        ratings = [
            float(row.get("前走指数", 0) or 0),
            float(row.get("前々走指数", 0) or 0),
            float(row.get("3走前指数", 0) or 0)
        ]

        rating = max(ratings)

        last = str(row.get("前走", ""))

        # 前走人気
        pop = re.search(r"(\d+)番人気", last)
        pop = int(pop.group(1)) if pop else 10

        # 前走着順
        rank = re.search(r"(\d+)着", last)
        rank = int(rank.group(1)) if rank else 10

        # 上がり3F
        last3f = re.search(r"3F\s+(\d+\.\d+)", last)
        last3f = float(last3f.group(1)) if last3f else 36.0

        # =========================
        # ① 人気×着順ギャップ
        # =========================
        bad_run = pop - rank  # 人気より負けたほどプラス

        # =========================
        # ② 能力ベース
        # =========================
        ability = rating / 10  # スケール調整

        # =========================
        # ③ 切れ味ボーナス（重要）
        # =========================
        if last3f <= 33.0:
            kick = 20
        elif last3f <= 33.5:
            kick = 15
        elif last3f <= 34.0:
            kick = 10
        elif last3f <= 34.5:
            kick = 2
        else:
            kick = 0

        # =========================
        # ④ 展開適性（ここが追加）
        # =========================

        style = str(row.get("脚質", ""))   # 先に作っておく必要あり
        pace = str(row.get("展開予想", "")) # summary側で付与

        fit = pace_fit_score(style, pace)

        # =========================
        # ⑤ 総合
        # =========================
        score = (
            bad_run * 1.5 +
            ability * 2.0 +
            kick * 2.0 +
            fit * 5.0   # ←展開はかなり重要なので重め
        )

        return round(score, 2)

    except:
        return 0

# =====================================
# ③ 競馬新聞コメント
# =====================================

def make_comment(row):

    rating = float(row.get("能力指数", 0))
    workout = str(row.get("追切評価", ""))
    pace = str(row.get("脚質", ""))

    comment = ""

    # 能力評価
    if rating >= 80:
        comment += "能力上位。"
    elif rating >= 70:
        comment += "安定勢力。"
    else:
        comment += "評価は中位。"

    # 追い切り
    if "A" in workout:
        comment += "追い切り抜群。"
    elif "B" in workout:
        comment += "仕上がり良好。"
    else:
        comment += "やや割引。"

    # 脚質コメント
    if "逃げ" in pace:
        comment += "単騎逃げなら粘り込み注意。"
    elif "先行" in pace:
        comment += "好位抜け出し警戒。"
    elif "差し" in pace:
        comment += "展開ハマれば一発。"
    elif "追込" in pace:
        comment += "展開待ちだが末脚は確実。"

    return comment


# =====================================
# ④ 一括生成（便利関数）
# =====================================

def build_report(df, pace_module):

    df["脚質"] = df.apply(pace_module.get_running_style, axis=1)

    df["激走指数"] = df.apply(calc_gekisou_index, axis=1)

    df["新聞コメント"] = df.apply(make_comment, axis=1)

    pace = predict_pace(df, pace_module)

    return df, pace