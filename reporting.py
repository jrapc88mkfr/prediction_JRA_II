import re

# =====================================
# ① 予想ペース
# =====================================

def predict_pace(df):
    """
    脚質分布から展開予想
    """

    counts = df["脚質"].value_counts()

    lead = counts.get("逃", 0)
    front = counts.get("先", 0)
    late = counts.get("差", 0) + counts.get("追", 0)

    if lead >= 3:
        return "Hペース"
    elif lead >=1 and front >= 7 :
        return "Hペース"    
    elif lead == 2:
        return "Mペース"
    elif lead <= 1 and late >= 8 :
        return "Sペース"
    else:
        return "Mペース"
    
# =====================================
# 展開ボーナス(2026/09/21)
# =====================================
def pace_fit_score(style, pace):

    style = str(style).strip()

    if pace == "Sペース":
        if style in ["逃", "先"]:
            return 3
        elif style == "差":
            return 0
        elif style == "追":
            return -1

    elif pace == "Hペース":
        if style in ["差", "追"]:
            return 3
        elif style == "逃":
            return -2
        elif style == "先":
            return 0

    # Mペース
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
            bad_run * 2.0 +
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

    #2026/09/21 変更
    if pace == "逃":
        comment += "単騎逃げなら粘り込み注意。"
    elif pace == "先":
        comment += "好位抜け出し警戒。"
    elif pace == "差":
        comment += "展開ハマれば一発。"
    elif pace == "追":
        comment += "展開待ちだが末脚は確実。"

    return comment


# =====================================
# ④ 一括生成（便利関数）
# =====================================

def build_report(df, pace_module):

    # ① 脚質を決定
    df["脚質"] = df.apply(pace_module.get_running_style,axis=1)

    # ② レース全体の展開を予測
    pace = predict_pace(df, pace_module)

    # ③ 各馬に展開予想をセット
    df["展開予想"] = pace

    # ④ 展開を含めて激走指数を計算
    df["激走指数"] = df.apply(calc_gekisou_index,axis=1)

    # ⑤ 新聞コメント
    df["新聞コメント"] = df.apply(make_comment,axis=1)

    return df, pace