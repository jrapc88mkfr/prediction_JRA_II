# ============================================================
# odds_estimate.py  馬連・3連複「想定オッズ」推定モジュール
#
# kichiuma.net から取れるのは単勝オッズのみで、馬連・3連複の
# 組み合わせオッズは提供されていない（netkeibaは規制が厳しく使えない）。
# そこで単勝オッズから Harville法 で確率を逆算し、
# JRAの実際の払戻率を掛けて「想定オッズ」を概算する。
#
# 注意（重要）:
#   これは単勝人気だけから逆算した理論値であり、実際の市場オッズではない。
#   実際の馬連・3連複オッズは、人気馬同士の組み合わせに買いが集中する、
#   大穴の組み合わせは理論値より高くなりやすい、といった単勝オッズだけ
#   では説明できない偏り（favorite-longshot bias）で乖離することが多い。
#   レポートに出す際は「想定オッズ」であることを明記し、実オッズと
#   同列に扱わないこと。
# ============================================================

import itertools

# ============================================================
# JRA 払戻率（控除率の逆）2014年6月改定以降・変更なし
# ============================================================
PAYOUT_RATE = {
    "umaren"    : 0.775,   # 馬連
    "sanrenpuku": 0.75,    # 3連複
}


def build_formation(ranked_nos: list[str]) -> dict:
    """
    補正後指数の高い順に並んだ馬番リストから、決め打ちの買い目フォーメーションを生成する。

    馬連BOX　　　　　：補正指数1〜3位（◎○▲）の3頭ボックス　　　　　　→ 3点
    3連複フォーメーション：1列目1〜2位（◎○）／2列目1〜3位（◎○▲）／
                        3列目1〜6位（◎○▲△☆1☆2）　　　　　　　　→ 10点

    ranked_nos: 補正後指数が高い順に並んだ馬番のリスト（例: ["2","5","6","8","9","10",...]）
    戻り値: {"umaren": [("2","5"), ...], "sanrenpuku": [("2","5","6"), ...]}
    """
    if len(ranked_nos) < 6:
        raise ValueError("フォーメーションには最低6頭分の順位付けが必要です")

    # 馬連BOX：上位3頭の2頭ずつの組み合わせ → 3C2 = 3点
    # 表示は馬番の若い順（昇順）にする（例: 9-2 ではなく 2-9）
    top3 = ranked_nos[:3]
    umaren = [tuple(sorted(c, key=int)) for c in itertools.combinations(top3, 2)]

    # 3連複フォーメーション：列ごとの候補から重複なしの組み合わせを列挙 → 10点
    col1 = ranked_nos[:2]   # ◎○
    col2 = ranked_nos[:3]   # ◎○▲
    col3 = ranked_nos[:6]   # ◎○▲△☆1☆2

    sanrenpuku = set()
    for a in col1:
        for b in col2:
            for c in col3:
                combo = {a, b, c}
                if len(combo) == 3:
                    # 表示は馬番の若い順（昇順）にする
                    sanrenpuku.add(tuple(sorted(combo, key=int)))

    # 補正後指数の順位が高い馬から順に並べ、見やすくする
    sanrenpuku_sorted = sorted(
        sanrenpuku,
        key=lambda combo: tuple(ranked_nos.index(x) for x in combo),
    )

    return {"umaren": umaren, "sanrenpuku": sanrenpuku_sorted}


def implied_win_probabilities(win_odds_by_no: dict[str, float]) -> dict[str, float]:
    """
    単勝オッズ（{馬番: オッズ}）から各馬の推定勝率を返す。

    生オッズの逆数(1/odds)を単純に足すと1を超える（JRAの控除率分、
    オッズが本来の確率より不利＝低く出るよう調整されているため）。
    合計が1になるよう正規化することで、控除率の歪みを取り除いた
    「市場が織り込んでいる勝率」を得る。
    """
    raw = {no: 1.0 / odds for no, odds in win_odds_by_no.items() if odds and odds > 0}
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {no: v / total for no, v in raw.items()}


def harville_top2_prob(p: dict[str, float], a: str, b: str) -> float:
    """
    Harville近似式。a・bの2頭が1着2着を独占する確率（順不同＝馬連の確率）。

    P(a,b) = P(aが1着)*P(bが2着|aが1着) + P(bが1着)*P(aが2着|bが1着)
           = pa * pb/(1-pa) + pb * pa/(1-pb)
    """
    pa, pb = p.get(a, 0.0), p.get(b, 0.0)
    if pa <= 0 or pb <= 0 or pa >= 1 or pb >= 1:
        return 0.0
    return pa * pb / (1 - pa) + pb * pa / (1 - pb)


def harville_top3_prob(p: dict[str, float], a: str, b: str, c: str) -> float:
    """
    Harville近似式。a・b・cの3頭が1〜3着を占める確率（順不同＝3連複の確率）。
    3頭の並び順6通りすべてを足し合わせる。
    """
    total = 0.0
    for x, y, z in itertools.permutations((a, b, c)):
        px, py, pz = p.get(x, 0.0), p.get(y, 0.0), p.get(z, 0.0)
        denom1 = 1 - px
        denom2 = 1 - px - py
        if px <= 0 or denom1 <= 0 or denom2 <= 0:
            continue
        total += px * (py / denom1) * (pz / denom2)
    return total


def _fmt_odds(v: float) -> float:
    """
    表示用のオッズ丸め処理。
    10倍を超える場合は整数に、10倍以下は小数第1位までにする
    （高配当ほど小数の意味が薄いため）。
    """
    if v is None or v == float("inf"):
        return v
    return round(v) if v > 10 else round(v, 1)


def estimate_combo_odds(p: dict[str, float], combo: tuple[str, ...], bet_type: str) -> float:
    """
    確率辞書pと組み合わせ（馬番のタプル）から想定オッズを1点分計算する。
    bet_type: "umaren"（2頭・馬連） or "sanrenpuku"（3頭・3連複）
    """
    if bet_type == "umaren":
        if len(combo) != 2:
            raise ValueError("umarenは馬番2頭のタプルを指定してください")
        prob = harville_top2_prob(p, combo[0], combo[1])
    elif bet_type == "sanrenpuku":
        if len(combo) != 3:
            raise ValueError("sanrenpukuは馬番3頭のタプルを指定してください")
        prob = harville_top3_prob(p, combo[0], combo[1], combo[2])
    else:
        raise ValueError(f"未対応の券種: {bet_type}")

    if prob <= 0:
        return float("inf")

    fair_odds = 1.0 / prob
    return fair_odds * PAYOUT_RATE[bet_type]


# ============================================================
# 想定期待値（参考値）
#
# 「堅い/荒れる」ラベルから、3連複フォーメーションが的中する確率を
# 大まかに仮定し、想定平均オッズに掛けて「想定期待値」を出す。
#
# 重要：ASSUMED_HIT_RATE の数値は実績データによる検証を行っていない
# 経験則の初期値。実際の的中率とは異なる可能性が高い。
# summarize_bets() の回収率ログが「堅い/荒れる」ラベル別に十分溜まったら、
# 実績の的中率に置き換えて精度を上げること。
# ============================================================
ASSUMED_HIT_RATE = {
    "堅い"    : 0.55,
    "やや堅い" : 0.40,
    "やや荒れる": 0.28,
    "荒れる"   : 0.18,
}


def estimate_hit_rate(race_shape_label: str | None) -> float | None:
    """race_shapeのラベルから、3連複フォーメーションの想定的中率（参考値）を返す。"""
    if not race_shape_label:
        return None
    return ASSUMED_HIT_RATE.get(race_shape_label)


def estimate_formation(
    win_odds_by_no: dict[str, float],
    umaren_combos: list[tuple[str, str]] | None = None,
    sanrenpuku_combos: list[tuple[str, str, str]] | None = None,
    race_shape: dict | None = None,
) -> dict:
    """
    フォーメーション全体（馬連N点＋3連複M点）の想定オッズ一覧と平均を返す。

    win_odds_by_no: {"2": 3.1, "5": 4.8, ...} のような 馬番→単勝オッズ
    umaren_combos / sanrenpuku_combos: [("2","5"), ...] / [("2","5","6"), ...]
    race_shape: JRA_read_next.pyが生成した {"label": "やや堅い", "gap_ratio": 0.25} 等。
                渡された場合、3連複の想定期待値（参考値）も計算する。

    戻り値:
      {
        "umaren": {"2-5": 12, ...},
        "umaren_avg": 34.1,
        "sanrenpuku": {"2-5-6": 59, ...},
        "sanrenpuku_avg": 44.5,
        "assumed_hit_rate": 0.28,      # race_shape渡し時のみ。的中率の参考値（0〜1）
        "expected_value": 12.5,        # race_shape渡し時のみ。assumed_hit_rate × sanrenpuku_avg
      }
    """
    p = implied_win_probabilities(win_odds_by_no)
    result = {}

    if umaren_combos:
        raw = {"-".join(c): estimate_combo_odds(p, c, "umaren") for c in umaren_combos}
        finite = [v for v in raw.values() if v != float("inf")]
        result["umaren"] = {k: _fmt_odds(v) for k, v in raw.items()}
        result["umaren_avg"] = _fmt_odds(sum(finite) / len(finite)) if finite else None

    if sanrenpuku_combos:
        raw = {"-".join(c): estimate_combo_odds(p, c, "sanrenpuku") for c in sanrenpuku_combos}
        finite = [v for v in raw.values() if v != float("inf")]
        result["sanrenpuku"] = {k: _fmt_odds(v) for k, v in raw.items()}
        result["sanrenpuku_avg"] = _fmt_odds(sum(finite) / len(finite)) if finite else None

        if race_shape:
            hit_rate = estimate_hit_rate(race_shape.get("label"))
            if hit_rate is not None and result["sanrenpuku_avg"]:
                result["assumed_hit_rate"] = hit_rate
                result["expected_value"] = _fmt_odds(hit_rate * result["sanrenpuku_avg"])

    return result


if __name__ == "__main__":
    # 動作確認用のダミーデータ（補正後指数順に並んだ馬番。10頭立てを想定）
    ranked_nos = ["2", "5", "6", "8", "9", "10", "1", "3", "4", "7"]
    dummy_win_odds = {
        "2": 6.5, "5": 8.2, "6": 3.1, "8": 5.4,
        "9": 4.8, "10": 12.0, "1": 20.0, "3": 40.0,
        "4": 60.0, "7": 90.0,
    }

    formation = build_formation(ranked_nos)
    print(f"馬連BOX: {len(formation['umaren'])}点  {formation['umaren']}")
    print(f"3連複フォーメーション: {len(formation['sanrenpuku'])}点  {formation['sanrenpuku']}")

    out = estimate_formation(
        dummy_win_odds,
        umaren_combos=formation["umaren"],
        sanrenpuku_combos=formation["sanrenpuku"],
    )
    import json
    print(json.dumps(out, ensure_ascii=False, indent=2))

