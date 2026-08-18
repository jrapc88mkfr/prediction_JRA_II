# ============================================================
# adjustment.py  指数補正テーブル
#
# ① しくじり補正: 前走コメントに含まれるキーワードで指数を加算
#    → 「しくじりがなければもっと走れていた」分を補正
#
# ② 斤量補正: レース内の最重量馬との差を指数に加算
#    → 斤量が軽いほど有利なため加算
# ============================================================

# ============================================================
# ① しくじり補正テーブル
# ============================================================
# キー   : 前走コメントに含まれるキーワード（部分一致）
# 値     : 指数加算値
# 考え方 : しくじりが大きいほど「実力より低い指数」になっているため加算
# ============================================================
MISHAP_BONUS_TABLE = {
    # ---- 大きなしくじり（+8〜+10） ----
    "出遅れ"            : 10,   # スタートで大きく出遅れ → 明らかな実力外の敗因
    "大出遅れ"          : 12,   # 特に大きな出遅れ
    "落馬"              : 0,    # 落馬は参考外（マイナスにもしない）
    "競走中止"          : 0,    # 参考外

    # ---- 中程度のしくじり（+5〜+7） ----
    "直線で進路"        : 7,    # 直線で進路が塞がれた
    "進路狭"            : 7,    # 進路が狭くなった
    "前が壁"            : 6,    # 前が壁になった
    "詰まる"            : 6,    # 直線で詰まった
    "不利"              : 6,    # 不利を受けた
    "コースロス"        : 5,    # コースロスが大きかった
    "大外"              : 5,    # 大外を回した
    "外に振"            : 5,    # 4角で外に振られた
    "かかり"            : 4,    # かかって折り合い欠いた

    # ---- 小さなしくじり（+2〜+3） ----
    "馬群"              : 3,    # 馬群に包まれた
    "後方"              : 2,    # 後方からの競馬（展開的なロス）
    "最後方"            : 3,    # 最後方からの競馬
    "道悪"              : 3,    # 道悪が合わなかった

    # ---- 休養明け補正（+3〜+5） ----
    # 「休養明けで力を出し切れなかった」分を補正
    "長期休養明け"      : 5,    # 6ヵ月以上の休養明け
    "年以上の長期休養"  : 8,    # 1年以上の長期休養明け
    "ヵ月休養明け"      : 3,    # 4〜6ヵ月の休養明け
    "ぶりの実戦"        : 4,    # 経過月数から計算した休養明け

    # ---- 距離・条件ミスマッチ（補正なし or 小さい） ----
    "距離が長"          : 0,    # 距離が合わなかった（能力差とは別）
    "距離が短"          : 0,    # 距離が短すぎた
    "初距離"            : 1,    # 初めての距離
}

# ---- 複数キーワードが一致した場合の上限 ----
MISHAP_BONUS_MAX = 15   # 1頭あたりの最大加算値


# ---- キーワードグループ（グループ内は最大値のみ採用して二重計上を防ぐ）----
MISHAP_BONUS_GROUPS = [
    # スタート系
    ["大出遅れ", "出遅れ"],
    # 進路系
    ["直線で進路", "進路狭", "前が壁", "詰まる", "不利"],
    # コースロス系
    ["コースロス", "大外", "外に振", "かかり"],
    # ポジション系
    ["最後方", "後方", "馬群"],
    # 馬場系
    ["道悪"],
    # 休養系
    ["年以上の長期休養", "長期休養明け", "ヵ月休養明け", "ぶりの実戦"],
]

def calc_mishap_bonus(comment: str) -> int:
    """
    前走コメントからしくじり補正値を計算する。
    同一グループ内は最大値のみ採用（二重計上を防ぐ）。
    異なるグループは合算。上限あり。

    例:
        "直線で進路狭くなる" → 進路系グループの最大=7
        "出遅れ後に直線で進路狭" → スタート10 + 進路7 = 17 → 上限15
        "長期休養明け" → 5
        "" → 0
    """
    if not comment:
        return 0

    total = 0
    for group in MISHAP_BONUS_GROUPS:
        # グループ内でマッチしたキーワードの最大値のみ採用
        group_max = 0
        for keyword in group:
            if keyword in comment:
                bonus = MISHAP_BONUS_TABLE.get(keyword, 0)
                group_max = max(group_max, bonus)
        total += group_max

    # グループ未所属キーワード（距離・初距離等）
    ungrouped = set(MISHAP_BONUS_TABLE.keys())
    for group in MISHAP_BONUS_GROUPS:
        ungrouped -= set(group)
    for keyword in ungrouped:
        if keyword in comment:
            total += MISHAP_BONUS_TABLE.get(keyword, 0)

    return min(total, MISHAP_BONUS_MAX)


# ============================================================
# ② 斤量補正テーブル
# ============================================================
# レース内で最も重い斤量との差に対して指数を加算する。
# 参考: 競馬の慣例では斤量1kg差 ≒ タイム約0.2秒差
#       タイム指数への換算は コース・距離によるが概算で 1kg ≈ 2点
# ============================================================
KG_BONUS_PER_KG = 2.0   # 1kg差あたりの加算値


def calc_weight_bonus(weight_str: str, max_weight: float) -> float:
    """
    斤量補正値を計算する。
    weight_str : この馬の斤量文字列 ("57.0" または "57.0kg")
    max_weight : レース内の最重量斤量 (float)
    戻り値     : 加算値 (float)

    例: 最重量58.0kg、この馬57.0kg → 差1.0kg → +2.0点
        最重量58.0kg、この馬58.0kg → 差0.0kg → +0.0点
    """
    try:
        w = float(str(weight_str).replace("kg", "").strip())
        diff = max_weight - w
        return round(diff * KG_BONUS_PER_KG, 1) if diff > 0 else 0.0
    except (ValueError, TypeError):
        return 0.0


def get_max_weight(rows: list) -> float:
    """
    全馬の斤量リストから最大値を返す。
    """
    weights = []
    for r in rows:
        try:
            w = float(str(r.get("斤量", "")).replace("kg", "").strip())
            weights.append(w)
        except (ValueError, TypeError):
            continue
    return max(weights) if weights else 0.0


# ============================================================
# ③ 補正後総合指数の計算
# ============================================================
def calc_adjusted_index(base_index: int,
                        mishap_comment: str,
                        weight_str: str,
                        max_weight: float) -> int:
    """
    しくじり補正 + 斤量補正を加えた補正後総合指数を返す。

    base_index    : 元の総合指数（過去3走平均）
    mishap_comment: 前走コメント文字列
    weight_str    : この馬の斤量 ("57.0" or "57.0kg")
    max_weight    : レース内最大斤量

    例:
        base=85, しくじり"出遅れ"(+10), 斤量差1kg(+2) → 97
    """
    mishap  = calc_mishap_bonus(mishap_comment)
    weight  = calc_weight_bonus(weight_str, max_weight)
    adjusted = base_index + mishap + weight
    return round(adjusted)


# ============================================================
# ④ 印付けルーチン
# ============================================================
MARKS = ["◎", "○", "▲", "△", "☆", "☆"]

def assign_marks(rows: list) -> list:
    """
    補正後総合指数（adjusted_index）で降順ソートして印を付ける。
    同点の場合は元の総合指数を優先、それも同点なら激走指数を優先。

    rows: build_json内の行リスト（adjusted_indexが設定済みであること）
    戻り値: 印が設定されたrows（同じリストを変更して返す）
    """
    # 全馬の印をリセット
    for r in rows:
        r["印"] = ""

    # 補正後指数 → 元指数 → 激走指数 の優先順でソート
    ranked = sorted(
        rows,
        key=lambda r: (
            r.get("adjusted_index", r.get("総合指数", 0)),
            r.get("総合指数", 0),
            r.get("激走指数", 0),
        ),
        reverse=True,
    )

    for i, r in enumerate(ranked[:len(MARKS)]):
        r["印"] = MARKS[i]

    return rows
