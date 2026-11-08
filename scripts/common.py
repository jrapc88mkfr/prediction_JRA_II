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


def signed(v):
    """能力指数以外の補正値の短縮表示。正数には+を付け、0はそのまま「0」、
    Noneは「-」にする（設計書Ver.03 8.1.10の「正数には+を付ける」に準拠）。"""
    if v is None:
        return "-"
    n = _to_num(v)
    if n is None:
        return "-"
    if n == int(n):
        n = int(n)
    return f"+{n}" if n > 0 else f"{n}"


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

        # 指数は「総合指数」(summary側キー名は補正後指数のまま)を正とする
        # （印(◎○▲…)はこの値の順位で付与されているため）
        s_rec = summary_map.get(name, {})
        idx = _to_num(s_rec.get("補正後指数"))
        if idx is None:
            idx = _to_num(h.get("総合指数"))

        # ---- 総合指数の内訳（設計書Ver.03: 能力指数+トレンド+しくじり+斤量+激走）----
        # トレンド(上昇下降度)は summary ではなく pyxel 側にしか無いのでそちらから取る。
        # 激走は summary["激走指数"] が実体としてはレース内最大値10点で正規化済みの値
        # （JRA_read_next.py 内の命名ゆれ。設計書でいう「激走補正」に相当する）。
        ability_val = _to_num(s_rec.get("能力指数"))
        trend_val   = _to_num(h.get("上昇下降度"))
        mishap_val  = _to_num(s_rec.get("しくじり補正"))
        weight_val  = _to_num(s_rec.get("斤量補正"))
        gekisou_val = _to_num(s_rec.get("激走指数"))
        breakdown = dict(
            ability=ability_val,
            ability_disp=(str(round(ability_val)) if ability_val is not None else "-"),
            trend=trend_val, trend_disp=signed(trend_val),
            mishap=mishap_val, mishap_disp=signed(mishap_val),
            weight=weight_val, weight_disp=signed(weight_val),
            gekisou=gekisou_val, gekisou_disp=signed(gekisou_val),
            total=idx,
            total_disp=(str(round(idx)) if idx is not None else "-"),
        )

        # 総合指数の色は「馬印(◎○▲△☆)」の色に合わせて目立たせる。
        # 印なしの馬は従来通りスコア基準の色（score_class）にフォールバック。
        mark = h.get("印") or ""
        mark_cls = MARK_CLASS.get(mark, "c-muted")
        idx_class = mark_cls if mark else score_class(idx)

        bar_px = 2
        if idx is not None:
            bar_px = max(2, min(24, round(idx * 0.22)))
        bar_pct = 0
        if idx is not None:
            bar_pct = max(2, min(100, round((idx - 50) / (120 - 50) * 100)))

        horses.append(dict(
            no=no, name=name,
            odds_val=odds_val, odds_disp=odds_disp, odds_class=odds_class(odds_val),
            record=f"（{record}）" if record else "",
            sex=h.get("性齢"), weight=h.get("斤量"),
            jockey=h.get("騎手"), style=style, style_class=STYLE_CLASS.get(style, "c-gray"),
            index=idx, index_class=idx_class, index_bar_px=bar_px, index_bar_pct=bar_pct,
            index_disp=(str(round(idx)) if idx is not None else "-"),
            prev_comment=(s_rec.get("前走コメント") or ""),
            prev1=dash(h.get("前走")), prev1_class=rating_class(h.get("前走")),
            prev2=dash(h.get("前々")), prev2_class=rating_class(h.get("前々")),
            prev3=dash(h.get("3走")),  prev3_class=rating_class(h.get("3走")),
            last3f=dash(h.get("前3F")), last3f_class=last3f_class(h.get("前3F")),
            train1f=dash(h.get("調1F")), train1f_class=train1f_class(h.get("調1F")),
            mark=mark, mark_class=mark_cls,
            lane_color=LANE_COLORS[(no - 1) % 8] if no else "#333",
            summary=s_rec,
            rawdata=raw_map.get(name),
            breakdown=breakdown,
        ))
    return horses


# ---------------------------------------------------------------
# 的中判定・回収率計算
#   馬連BOX  : 総合指数 上位1〜3位(◎○▲) の3頭box = 3点
#   3連複F   : 1列目=上位1-2位(◎○) / 2列目=上位1-3位(◎○▲) / 3列目=上位1-6位(◎○▲△☆1☆2) = 10点
#   単勝     : ◎の単勝 = 1点   （2026/10追加）
#   複勝     : ◎の複勝 = 1点   （2026/10追加）
#   計15点 x 100円 = 1,500円/レース
#   ※結果JSONに単勝・複勝の払戻(tansho/fukusho)が無いレースは、取得できるまで
#     従来の13点(1,300円)で判定する（払戻不明のまま「外れ」扱いにして成績を歪めないため）
# ---------------------------------------------------------------
from itertools import combinations
import re as _re

BET_UNIT = 100


def _find_honmei_no(horses):
    """◎の馬番。印が無ければ総合指数1位の馬番"""
    for h in horses:
        if h.get("mark") == "◎":
            return h.get("no")
    ranked = sorted([h for h in horses if h.get("index") is not None],
                    key=lambda h: h["index"], reverse=True)
    return ranked[0]["no"] if ranked else None


def _honmei_payout(items, honmei_no):
    """tansho / fukusho のリスト [{"no":9,"payout":"150円"},...] から◎の払戻(円)を返す。着外なら0"""
    for it in items or []:
        try:
            if int(it.get("no")) == int(honmei_no):
                return _yen(it.get("payout")) or 0
        except (TypeError, ValueError):
            continue
    return 0


def _yen(text):
    """'9-16　1,850円' のような文字列から金額(int)を取り出す"""
    if not text:
        return None
    m = _re.search(r"([\d,]+)\s*円", text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def evaluate_race_bet(horses: list[dict], result: dict | None, race: dict | None = None) -> dict | None:
    """1レース分の馬連BOX+3連複フォーメーションの的中判定・収支を計算する。
    result が未確定/Noneなら None を返す。

    race（JSON全体）が渡され、かつ race["betting_formation"] があれば、
    JRA_read_next.py が予想生成時に確定させた買い目をそのまま使う
    （的中判定と、想定オッズ表示（betting_estimate）を同じ買い目基準で揃えるため）。
    betting_formation が無い過去のレースJSON（本機能追加前に生成されたもの）は、
    従来通り horses の index からその場で再計算するフォールバックを維持する。
    """
    if not result or not result.get("confirmed"):
        return None
    top3 = result.get("top3") or []
    if len(top3) < 3:
        return None

    formation = (race or {}).get("betting_formation")
    if formation and formation.get("umaren") and formation.get("sanrenpuku"):
        # 馬番は betting_formation 内では文字列("2"等)、result.top3 内ではint(2等)なので
        # 突き合わせのため int に揃える
        umaren_combos = {frozenset(int(x) for x in c) for c in formation["umaren"]}
        sanrenpuku_combos = {frozenset(int(x) for x in c) for c in formation["sanrenpuku"]}
    else:
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

    # ---- ◎の単勝・複勝（2026/10追加）----
    honmei_no = _find_honmei_no(horses)
    has_honmei = bool(honmei_no is not None
                      and result.get("tansho") and result.get("fukusho"))
    tansho_pay = fukusho_pay = 0
    if has_honmei:
        tansho_pay = _honmei_payout(result.get("tansho"), honmei_no)
        fukusho_pay = _honmei_payout(result.get("fukusho"), honmei_no)

    n_points = len(umaren_combos) + len(sanrenpuku_combos) + (2 if has_honmei else 0)
    investment = n_points * BET_UNIT
    payout = umaren_pay + sanrenpuku_pay + tansho_pay + fukusho_pay

    return dict(
        n_points=n_points,
        investment=investment,
        honmei_no=honmei_no, has_honmei=has_honmei,
        tansho_points=1 if has_honmei else 0, fukusho_points=1 if has_honmei else 0,
        umaren_points=len(umaren_combos), sanrenpuku_points=len(sanrenpuku_combos),
        tansho_hit=tansho_pay > 0, tansho_pay=tansho_pay,
        fukusho_hit=fukusho_pay > 0, fukusho_pay=fukusho_pay,
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

    # 券種別の成績（どの券種が効いているか切り分けるため）
    def _by(kind, subset):
        k = len(subset)
        hits = sum(1 for e in subset if e.get(kind + "_hit"))
        inv = sum(e.get(kind + "_points", 0) for e in subset) * BET_UNIT
        pay = sum(e.get(kind + "_pay", 0) for e in subset)
        return dict(
            n=k, hits=hits, investment=inv, payout=pay,
            hit_rate=round(hits / k * 100, 1) if k else 0.0,
            recovery_rate=round(pay / inv * 100, 1) if inv else 0.0,
        )
    honmei_entries = [e for e in entries if e.get("has_honmei")]
    by_type = dict(
        tansho=_by("tansho", honmei_entries),
        fukusho=_by("fukusho", honmei_entries),
        umaren=_by("umaren", entries),
        sanrenpuku=_by("sanrenpuku", entries),
    )
    return dict(
        n_legacy=n - len(honmei_entries),   # 単勝・複勝の払戻が未取得で13点判定のままのレース数
        by_type=by_type,
        n_races=n,
        wins=wins,
        losses=n - wins,
        hit_rate=round(wins / n * 100, 1) if n else 0.0,
        investment=investment,
        payout=payout,
        recovery_rate=round(payout / investment * 100, 1) if investment else 0.0,
    )


# ---------------------------------------------------------------
# 展開予想（自動生成）
#   印(◎○▲△☆)・脚質(逃/先/差/追)・馬番・補正指数・想定ペース(race["pace"])・
#   開催場所(race["course"])・前3F(上がり)・調教1Fから、ルールベースで文章を組み立てる。
#   外部AIは使わず、既存データのみで完結する。
#   脚質が「不明」ばかりの場合でも、前3F(上がり)を"隠れた脚質"の代用指標として使い、
#   コース傾向・指数ギャップ・調教状態などを組み合わせて厚みを持たせる。
# ---------------------------------------------------------------
_MARK_ORDER = ["◎", "○", "▲", "△", "☆"]

# 一般に言われる開催場所ごとのコース傾向（大まかな一般論。距離までは加味していない）
VENUE_TENDENCY = {
    "東京": "直線が長く、末脚に優れた差し・追い込み馬が台頭しやすい",
    "中山": "直線が短くコーナーもきついため、先行馬が粘り込みやすい",
    "阪神": "内枠・先行馬がやや有利とされるが、馬場状態次第で外差しも決まりやすい",
    "京都": "コーナーが緩やかで直線も長く、実力通りの決着になりやすい",
    "中京": "直線が長く、差し・追い込み勢にもチャンスがあるコース",
    "新潟": "直線が非常に長く、外を回した差し・追い込みが決まりやすい",
    "小倉": "小回りコースで先行有利、内枠をロスなく立ち回れるかがカギ",
    "函館": "小回りで直線も短く、先行・好位差しが中心になりやすい",
    "福島": "小回りで機動力のある先行・好位馬が有利になりやすい",
    "札幌": "洋芝で時計がかかりやすく、パワーとスタミナが問われる",
}


def _marked_horses(horses):
    """印がついている馬を ◎○▲△☆ の順で返す"""
    by_mark = {h["mark"]: h for h in horses if h.get("mark")}
    return [by_mark[m] for m in _MARK_ORDER if m in by_mark]


def _join_names(hs, with_mark=True):
    if with_mark:
        return "・".join(f"{h['mark']}{h['name']}" for h in hs)
    return "・".join(h["name"] for h in hs)


def generate_pace_forecast(horses: list[dict], race: dict) -> str:
    """展開予想 (2026-11-08 改修)

    旧版は「ペース+コース定型文+逃げ馬+印つき差し馬+指数僅差+結び」の固定骨格で
    全レース同じ文章になっていた。改修版は実データからシナリオ分岐させる:
      ① 先手争い: 逃げ頭数 (0/1/2/3+) と枠番・脚質前方率で分岐
      ② ペースの帰結: 想定ペースごとに、展開が向く脚質の指数上位馬を名指し
      ③ コース・馬場: course_info (使用コース/馬場状態/芝の状態) を事実として接続
      ④ 上がり: 前走上がり最速馬を実測値つきで、ペースとの相性で言い分ける
      ⑤ 展開利の穴: 想定シナリオに脚質が合う無印馬を1頭だけ拾う
      ⑥ 力関係: 指数ギャップを3分岐の短文に (旧版の「本線としたい」の結びは廃止)
    データが薄いレースでは従来型の最小文にフォールバックする。
    """
    course = race.get("course", "") or ""
    is_jump = "ジャンプ" in (race.get("race_name") or "")
    cp = race.get("candidate_prediction") or {}
    ckey = "" if is_jump else (cp.get("コースキー") or "")
    surface, dist = "", str(race.get("distance") or "")
    _p = ckey.split("_")
    if len(_p) == 3:
        surface = _p[1]
        if not dist:
            dist = _p[2]
    head = f"{course}{surface}{dist}m。" if (course or surface or dist) else ""
    if not dist and not surface:
        head = f"{course}。" if course else ""

    pace_label = race.get("pace", "") or ""
    marked = _marked_horses(horses)

    hd = {e.get("馬名"): e for e in (race.get("horse_data") or []) if isinstance(e, dict)}

    def _waku(h):
        v = (hd.get(h["name"]) or {}).get("枠番")
        return v if isinstance(v, int) else None

    def _front_rate(h):
        v = (hd.get(h["name"]) or {}).get("脚質前方率")
        return v if isinstance(v, (int, float)) else None

    def _by_index(hs):
        return sorted(hs, key=lambda h: (h.get("index") is None, -(h.get("index") or 0)))

    style_known = [h for h in horses if h.get("style") in ("逃", "先", "差", "追")]
    nige = [h for h in style_known if h["style"] == "逃"]
    senko = [h for h in style_known if h["style"] == "先"]
    sashi = [h for h in style_known if h["style"] == "差"]
    oikomi = [h for h in style_known if h["style"] == "追"]
    closers = sashi + oikomi
    sentences = []

    # ---- ① 先手争い ----
    if len(style_known) >= 4:
        if len(nige) >= 5:
            sentences.append(f"逃げ・先行タイプが{len(nige) + len(senko)}頭と前に集中しており、先手争いが激しくなれば前半からペースが上がる。")
        elif len(nige) >= 3:
            names = _join_names(sorted(nige, key=lambda h: (_waku(h) is None, _waku(h) or 0)), with_mark=False)
            sentences.append(f"逃げ馬は{names}の{len(nige)}頭と多く、先手争いが激しくなれば前半からペースが上がる。")
        elif len(nige) == 2:
            a, b = sorted(nige, key=lambda h: (_waku(h) is None, _waku(h) or 0))
            wa, wb = _waku(a), _waku(b)
            if wa is not None and wb is not None and wa != wb:
                sentences.append(f"逃げは{wa}枠の{a['name']}と{wb}枠の{b['name']}の2頭。内の{a['name']}が主張し、{b['name']}が外から競りかける形になりそうだ。")
            else:
                sentences.append(f"逃げは{a['name']}と{b['name']}の2頭で、先手争いの行方がペースを左右する。")
        elif len(nige) == 1:
            a = nige[0]
            if len(senko) >= 6:
                sentences.append(f"逃げは{a['name']}の1頭だけだが、先行馬が{len(senko)}頭と多く、早めに競りかけられれば楽な逃げにはならない。")
            elif len(senko) <= 3:
                sentences.append(f"逃げは{a['name']}の1頭だけで、先行勢も{len(senko)}頭と手薄。{a['name']}がすんなり先手を取り、マイペースに持ち込む公算が大きい。")
            else:
                sentences.append(f"逃げは{a['name']}の1頭。先行馬は{len(senko)}頭で、{a['name']}の出方ひとつでペースが決まる。")
        else:
            cand = sorted(senko, key=lambda h: (_front_rate(h) is None, -(_front_rate(h) or 0)))
            if cand:
                a = cand[0]
                fr = _front_rate(a)
                if fr is not None:
                    sentences.append(f"逃げ馬は不在。先行勢では過去の前方率が最も高い{a['name']}（{fr * 100:.0f}%）がハナに立つ形で、入りは緩やかになりそうだ。")
                else:
                    sentences.append(f"逃げ馬は不在で、先行馬の{a['name']}あたりがハナに立つ形。入りは緩やかになりそうだ。")

    # ---- ② ペースの帰結 ----
    if pace_label:
        if pace_label.startswith("H"):
            tops = _by_index(closers)[:2]
            if tops:
                sentences.append(f"想定は{pace_label}。前半が速くなれば終いの脚比べとなり、差し・追いの指数上位{_join_names(tops)}に展開が向きそうだ。")
            else:
                sentences.append(f"想定は{pace_label}。前半が速くなれば、後方勢にも出番が回ってくる。")
        elif pace_label.startswith("S"):
            tops = _by_index(nige + senko)[:2]
            if tops:
                sentences.append(f"想定は{pace_label}で、前が止まりにくい流れ。逃げ・先行の指数上位{_join_names(tops)}がそのまま粘り込む場面を警戒したい。")
            else:
                sentences.append(f"想定は{pace_label}で、前が止まりにくい流れになりそうだ。")
        else:
            sentences.append(f"想定は{pace_label}。極端な流れにはなりにくく、好位を確保した馬同士の力勝負になりそうだ。")

    # ---- ③ コース・馬場情報 ----
    ci = race.get("course_info") or {}
    if ci:
        is_dirt = (surface == "ダ")
        state = ci.get("ダート馬場状態") if is_dirt else ci.get("芝馬場状態")
        bits = []
        if ci.get("使用コース"):
            bits.append(f"{ci['使用コース']}コース" + (f"（{ci['使用コース備考']}）" if ci.get("使用コース備考") else ""))
        if state:
            bits.append(f"{'ダート' if is_dirt else '芝'}は{state}")
        if bits:
            sentences.append("馬場は" + "、".join(bits) + "。")
        if not is_dirt and ci.get("芝の状態"):
            sentences.append(f"芝の状態は「{ci['芝の状態']}」")

    # ---- ④ 前走の上がり ----
    timed = sorted((h for h in horses if h.get("style") != "逃" and isinstance(h.get("last3f"), (int, float))), key=lambda h: h["last3f"])
    if timed:
        a = timed[0]
        group = [a]
        if len(timed) > 1 and timed[1]["last3f"] - a["last3f"] <= 0.2:
            group.append(timed[1])
        names = _join_names(group, with_mark=False)
        val = f"{a['last3f']:.1f}秒"
        if pace_label.startswith("S"):
            sentences.append(f"前走の上がり最速は{names}の{val}だが、スローでは位置取り次第で届かない場面もある。")
        elif pace_label.startswith("H"):
            sentences.append(f"前走の上がりは{names}の{val}が最速。流れが速くなれば、この末脚が生きてくる。")
        else:
            sentences.append(f"前走の上がり最速は{names}の{val}。上がり勝負になれば台頭の余地がある。")

    # ---- ⑤ 展開利の穴 ----
    if pace_label.startswith("H"):
        fit = ("差", "追")
    elif pace_label.startswith("S"):
        fit = ("逃", "先")
    elif pace_label:
        fit = ("先", "差")
    else:
        fit = ("差", "追") if len(nige) >= 2 else ("先", "差")
    ranked = _by_index([h for h in horses if h.get("index") is not None])
    rank_of = {h["name"]: i + 1 for i, h in enumerate(ranked)}
    half = max(1, len(ranked) // 2)
    cands = [h for h in ranked
             if h["style"] in fit and not h.get("mark")
             and (h.get("odds_val") is None or h["odds_val"] >= 8)
             and rank_of[h["name"]] <= half]
    if cands:
        a = cands[0]
        sentences.append(f"展開面で浮上しそうな穴は、無印の{a['name']}（{a['style']}・指数{rank_of[a['name']]}位）あたり。")

    # ---- ⑥ 力関係 ----
    if len(marked) >= 2:
        top, second = marked[0], marked[1]
        if top.get("index") is not None and second.get("index") is not None:
            gap = top["index"] - second["index"]
            if gap >= 8:
                sentences.append(f"指数では◎{top['name']}が{gap:.0f}pt抜けており、地力は一枚上。")
            elif gap < 3:
                cnt = sum(1 for h in horses if h.get("index") is not None and top["index"] - h["index"] <= 5)
                sentences.append(f"指数は上位{cnt}頭が5pt以内にひしめく混戦模様。")
            else:
                sentences.append(f"指数上位は◎{top['name']}と{second['mark']}{second['name']}がやや抜ける形。")

    # 障害レース・データが薄い場合は従来型の最小文にフォールバック
    if is_jump:
        sentences = []
    if not sentences:
        venue_note = VENUE_TENDENCY.get(course, "")
        if pace_label and venue_note:
            sentences.append(f"{pace_label}が想定される中、当コースは{venue_note}。")
        elif pace_label:
            sentences.append(f"{pace_label}が想定されるレース。")
        elif venue_note:
            sentences.append(f"当コースは{venue_note}。")

    body = "".join(sentences) if sentences else "データが揃い次第、詳細な展開予想を表示します。"
    return (head + body).strip()
