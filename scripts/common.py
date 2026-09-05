"""3ハロンVII - 予想データ(pyxel/summary/rawdata)をテンプレート用に整形する共通ロジック。
generate_html.py から呼び出す。Pyxel版(keiba_pyxel_ANT_json.py)の色分けロジックを移植。
"""
from __future__ import annotations
import re

MARK_CLASS = {"◎": "c-yellow", "○": "c-orange", "▲": "c-red", "☆": "c-gray", "△": "c-green"}
STYLE_CLASS = {"逃": "c-red", "先": "c-orange", "差": "c-blue", "追": "c-pink"}
LANE_COLORS = ['#FFF1E8', '#FF004D', '#FFA300', '#29ADFF', '#FFEC27', '#00E436', '#FF77A8', '#83769C']


def odds_class(v):
    if v is None: return "c-muted"
    if v <= 5:  return "c-red"
    if v <= 15: return "c-orange"
    return "c-white"


def score_class(v):
    if v is None: return "c-muted"
    if v >= 90: return "c-green"
    if v >= 75: return "c-yellow"
    return "c-lav"


def rating_class(v):
    if v is None: return "c-muted"
    if v >= 100: return "c-red"
    if v >= 90:  return "c-yellow"
    return "c-white"


def last3f_class(v):
    if v is None: return "c-muted"
    if v < 33.5: return "c-red"
    if v < 34.0: return "c-yellow"
    return "c-green"


def train1f_class(v):
    if v is None: return "c-muted"
    if v < 11.0:  return "c-red"
    if v <= 11.5: return "c-yellow"
    return "c-green"


def _to_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def dash(v):
    return v if v not in (None, "") else "-"


def build_horses(race: dict) -> list[dict]:
    """race JSON (pyxel/summary/rawdata) -> テンプレートに渡す馬リスト"""
    summary_map = {s["馬名"]: s for s in race.get("summary", [])}
    raw_map = {r["馬名"]: r for r in race.get("rawdata", [])}
    horses = []
    for h in race.get("pyxel", []):
        odds_field = h.get("オッズ戦績") or ""
        m = re.match(r"^([\d.]+)\s*\(([^)]*)\)", odds_field.strip())
        odds_val = float(m.group(1)) if m else None
        record = m.group(2) if m else ""
        odds_disp = f"{odds_val:g}" if odds_val is not None else "---"
        style = h.get("脚質") or ""
        no = h.get("馬番")
        name = h.get("馬名")

        # 指数は「補正後指数」を正とする（印(◎○▲…)はこの値の順位で付与されているため）
        s_rec = summary_map.get(name, {})
        idx = _to_num(s_rec.get("補正後指数"))
        if idx is None:
            idx = _to_num(h.get("総合指数"))

        bar_px = 2
        if idx is not None:
            bar_px = max(2, min(45, round(idx * 0.45)))

        horses.append(dict(
            no=no, name=name,
            odds_val=odds_val, odds_disp=odds_disp, odds_class=odds_class(odds_val),
            record=f"（{record}）" if record else "",
            sex=h.get("性齢"), weight=h.get("斤量"),
            jockey=h.get("騎手"), style=style, style_class=STYLE_CLASS.get(style, "c-gray"),
            index=idx, index_class=score_class(idx), index_bar_px=bar_px,
            prev1=dash(h.get("前走")), prev1_class=rating_class(h.get("前走")),
            prev2=dash(h.get("前々")), prev2_class=rating_class(h.get("前々")),
            prev3=dash(h.get("3走")),  prev3_class=rating_class(h.get("3走")),
            last3f=dash(h.get("前3F")), last3f_class=last3f_class(h.get("前3F")),
            train1f=dash(h.get("調1F")), train1f_class=train1f_class(h.get("調1F")),
            mark=h.get("印") or "", mark_class=MARK_CLASS.get(h.get("印"), "c-muted"),
            lane_color=LANE_COLORS[(no - 1) % 8] if no else "#333",
            summary=s_rec,
            rawdata=raw_map.get(name),
        ))
    return horses


# ---------------------------------------------------------------
# 的中判定・回収率計算
#   馬連BOX  : 補正後指数 上位1〜3位(◎○▲) の3頭box = 3点
#   3連複F   : 1列目=上位1-2位(◎○) / 2列目=上位1-3位(◎○▲) / 3列目=上位1-6位(◎○▲△☆1☆2) = 10点
#   計13点 x 100円 = 1,300円/レース
# ---------------------------------------------------------------
from itertools import combinations
import re as _re

BET_UNIT = 100


def _yen(text):
    """'9-16　1,850円' のような文字列から金額(int)を取り出す"""
    if not text:
        return None
    m = _re.search(r"([\d,]+)\s*円", text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def evaluate_race_bet(horses: list[dict], result: dict | None) -> dict | None:
    """1レース分の馬連BOX+3連複フォーメーションの的中判定・収支を計算する。
    result が未確定/Noneなら None を返す。"""
    if not result or not result.get("confirmed"):
        return None
    top3 = result.get("top3") or []
    if len(top3) < 3:
        return None

    ranked = sorted(
        [h for h in horses if h.get("index") is not None],
        key=lambda h: h["index"], reverse=True,
    )
    if len(ranked) < 6:
        return None  # 頭数が少なすぎてフォーメーションが組めない

    nos = [h["no"] for h in ranked]
    col_umaren = nos[0:3]                      # ◎○▲
    col1, col2, col3 = nos[0:2], nos[0:3], nos[0:6]  # ◎○ / ◎○▲ / ◎○▲△☆1☆2

    umaren_combos = {frozenset(c) for c in combinations(col_umaren, 2)}
    sanrenpuku_combos = set()
    for x in col1:
        for y in col2:
            if y == x:
                continue
            for z in col3:
                if z == x or z == y:
                    continue
                sanrenpuku_combos.add(frozenset((x, y, z)))

    actual_1_2 = frozenset({top3[0]["no"], top3[1]["no"]})
    actual_top3 = frozenset({top3[0]["no"], top3[1]["no"], top3[2]["no"]})

    umaren_hit = actual_1_2 in umaren_combos
    sanrenpuku_hit = actual_top3 in sanrenpuku_combos

    umaren_pay = _yen(result.get("umaren")) if umaren_hit else 0
    sanrenpuku_pay = _yen(result.get("sanrenpuku")) if sanrenpuku_hit else 0
    umaren_pay = umaren_pay or 0
    sanrenpuku_pay = sanrenpuku_pay or 0

    n_points = len(umaren_combos) + len(sanrenpuku_combos)
    investment = n_points * BET_UNIT
    payout = umaren_pay + sanrenpuku_pay

    return dict(
        n_points=n_points,
        investment=investment,
        umaren_hit=umaren_hit, umaren_pay=umaren_pay,
        sanrenpuku_hit=sanrenpuku_hit, sanrenpuku_pay=sanrenpuku_pay,
        payout=payout,
        win=payout > 0,
    )


def summarize_bets(entries: list[dict]) -> dict:
    """evaluate_race_betの結果リストから通算成績を集計する"""
    n = len(entries)
    wins = sum(1 for e in entries if e["win"])
    investment = sum(e["investment"] for e in entries)
    payout = sum(e["payout"] for e in entries)
    return dict(
        n_races=n,
        wins=wins,
        losses=n - wins,
        hit_rate=round(wins / n * 100, 1) if n else 0.0,
        investment=investment,
        payout=payout,
        recovery_rate=round(payout / investment * 100, 1) if investment else 0.0,
    )
