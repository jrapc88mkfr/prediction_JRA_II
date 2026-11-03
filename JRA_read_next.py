# ============================================================
# JRA_read_next_v4.py  競馬予想データ自動生成 的中率改善バージョン (実績検証つき)
#
# 【v4での変更点】（v3から。同梱の修正版モジュール3点とセットで使うこと）
#   6. reporting.py 修正版に合わせ、前走テキストを激走指数の計算に渡す
#      （人気×着順ギャップと切れ味ボーナスが復活する。ただし修正版の
#      激走指数は実績18Rでは単体で当てておらず、v3のランキングには
#      従来通り使っていない。効くかどうかは今後のデータで再検証）
#   7. adjustment.py 修正版で休養ペナルティが実際に効くようになる
#      （印まわりの補正後指数が変わる。ランキングへの影響はない）
#   8. odds_estimate.py 修正版でフォーメーションが1位軸 (13点は同じ) に
#      なる。実績18R・v3ランキングでの比較: 3連複 従来3的中/回収率0.216
#      → 1位軸 4的中/0.355
#
# 【v3での変更点】（v2から。元の JRA_read_next.py / v2 は変更していません）
#   5. 過去18レースの実績検証に基づき、勝率の元になるモデルを
#      「総合指数」から「クラス調整スコア」に差し替え、
#      温度=12 / 市場ブレンド=0.5 に設定。フォーメーションも
#      最終確率の順で組むようにした。詳細は同梱の検証レポート参照。
#
# 【v2での変更点】
#   1. 補正後指数を「勝率（確率）」に変換する層を追加 (softmax)
#      指数の順位だけでなく、1位の強さ・2位との差を数値化する。
#   2. 単勝オッズから求めた市場の勝率とブレンドする (市場は強い予測子。
#      ただし生成時点のオッズは早い段階のものなので、重みは控えめが既定。
#      最終的には backtest.py で重みを実績データから決めること)
#   3. 信頼度による「見送り」判定を追加。信頼度の低いレースを買わない
#      ことが、買ったレースでの的中率を上げる最も確実な方法の一つ。
#      しきい値は初期値であり backtest.py での検証・調整が前提。
#   4. 出馬表の dosuu_box（距離・芝ダ・コース別成績）を取得していなかった
#      問題を修正し、rawdata に「適性データ」として保存する
#      （まずは蓄積用。指数への反映はバックテストで効果を確認してから）
#
# 【旧バージョンからの変更点】
#   - kichiuma.net から出馬表を自動取得（JRA URL不要）
#   - race_id を レース名辞書から自動生成
#   - Claude API で前走しくじりコメントを自動生成
#   - GitHub Actions での完全自動実行対応
#
# 【使い方】
#   ローカル: python JRA_read_next.py
#   GitHub Actions: 毎週土曜 20:00 JST に自動実行
#
# 【必要な環境変数 (GitHub Secrets)】
#   ANTHROPIC_API_KEY  ... Claude API キー
#   GH_TOKEN           ... GitHub Personal Access Token (push用)
# ============================================================

import os
import re
import json
import math
import pandas as pd
import requests
import anthropic
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# .env ファイルから環境変数を読み込む（ローカル実行用）
# pip install python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # GitHub Actions では不要（Secrets から自動注入）

# 各モジュールをimport（同じフォルダに置く）
from pace      import get_running_style
from rating    import single_race_rating, calc_trend_score , calc_current_ability
from workout   import calc_workout_score, get_workout_rank
from reporting   import predict_pace, calc_gekisou_index, make_comment
from adjustment  import calc_mishap_bonus, calc_weight_bonus, \
                        get_max_weight, calc_adjusted_index, assign_marks
from odds_estimate import build_formation

def _calc_total_record(kisyu_text: str) -> str:
    total = [0, 0, 0, 0]
    for line in kisyu_text.split("\n"):
        import re as _re
        m = _re.match(r"(\d+)-(\d+)-(\d+)-(\d+)", line.strip())
        if m:
            for i in range(4):
                total[i] += int(m.group(i + 1))
    return f"{total[0]}.{total[1]}.{total[2]}.{total[3]}" if sum(total) > 0 else ""


# ============================================================
# rating.py の parse_race_result を kichiuma 形式に対応した版で上書き
# kichiuma 形式:
#   "新潟26.07.26 4 関屋記念GIII 芝 1600m 1:33.4不 34.4 1.0 458(+4) 58.0田口貫太14人 ..."
#    競馬場  日付  着順 レース名  面 距離   タイム馬場 上3F 着差 馬体重  騎手・人気
# ============================================================
def _parse_kichiuma_result(text):
    text = str(text)
    result = {
        "track": None, "surface": None, "distance": None,
        "time": None, "margin": None, "rank": None,
        "popularity": None, "last3f": None, "baba": None,
    }
    # 競馬場
    for t in ["東京","中山","阪神","京都","中京","新潟","札幌","函館","福島","小倉"]:
        if t in text:
            result["track"] = t
            break
    # 距離・面
    m = re.search(r"(芝|ダ)\s*(\d+)m", text)
    if m:
        result["surface"]  = m.group(1)
        result["distance"] = int(m.group(2))
    # タイム・馬場状態
    m = re.search(r"(\d+:\d+\.\d+)([良稍重不])", text)
    if m:
        result["time"] = m.group(1)
        result["baba"] = m.group(2)
    # 着順: 日付(YY.MM.DD)の直後
    m = re.search(r"\d{2}\.\d{2}\.\d{2}\s+(\d+)\s+", text)
    if m:
        result["rank"] = int(m.group(1))
    # 上がり3F: タイム+馬場の直後
    m = re.search(r"\d+:\d+\.\d+[良稍重不]\s+([\d.]+)\s+", text)
    if m:
        result["last3f"] = float(m.group(1))
    # 着差: 上がり3Fの次
    m = re.search(r"\d+:\d+\.\d+[良稍重不]\s+[\d.]+\s+([\d.]+)\s+", text)
    if m:
        result["margin"] = float(m.group(1))
    # 人気
    m = re.search(r"(\d+)人", text)
    if m:
        result["popularity"] = int(m.group(1))
    result["grade"] = _extract_grade(text)
    return result


# ============================================================
# グレード確定抽出（LLMに読み取らせず、コード側で確定させる）
#
# 「GIII」の文字列に部分文字列として「GI」が含まれるため、
# LLM（特にHaiku等の軽量モデル）が「GI」だけを拾って
# GIII級の重賞をGIと誤読するケースがあった。
# 必ず長い表記から順にマッチさせることで誤読を根本から防ぐ。
# ============================================================
_GRADE_PATTERNS = [
    "Jpn1", "Jpn2", "Jpn3",   # 地方交流重賞（念のため長い順に先頭）
    "GIII", "GII", "GI",       # 中央重賞（3文字→2文字→1文字の順が必須）
    "OP", "L",                 # オープン特別・リステッド
]

def _extract_grade(text: str) -> str:
    """
    kichiuma形式の生データ文字列からレースグレードを確定抽出する。
    "GIII"を"GI"と誤読しないよう、必ず長い表記から先に判定する。
    見つからなければ空文字（＝一般競走・条件戦とみなす）。
    """
    text = str(text)
    for g in _GRADE_PATTERNS:
        if g in text:
            return g
    return ""

# rating モジュールの parse_race_result を置き換え
import rating as _rating_mod
_rating_mod.parse_race_result = _parse_kichiuma_result
# single_race_rating / horse_rating は内部で parse_race_result を呼ぶので自動反映

# ============================================================
# ★★★ ローカル実行時はここだけ入力する ★★★
# GitHub Actions では run_schedule.py が自動的に上書きする
TARGET_RACE = os.environ.get("TARGET_RACE", "中京記念")
# ★★★★★★★★★★★★★★★★★★★★★★

# ============================================================
# 開催場ID
# ============================================================
VENUE_ID = {
    "札幌": "71", "函館": "72", "福島": "73", "新潟": "74",
    "東京": "75", "中山": "76", "中京": "77", "京都": "78", "阪神": "79",
    "小倉": "80",
}

# ============================================================
# レーススケジュール辞書
# キー: レース名
# 値:   (開催場, レース番号, 開催日 YYYY/M/D)

# ============================================================
# 日付ユーティリティ
# ============================================================
def next_sunday(d: datetime) -> datetime:
    """月〜土なら次の日曜、日曜ならそのまま"""
    wd = d.weekday()  # 月=0 ... 日=6
    return d if wd == 6 else d + timedelta(days=6 - wd)

# RACE_DATE は main() 内で schedule.json の date から設定する
RACE_DATE = next_sunday(datetime.today())


def build_race_params(race_name: str, date_str: str,
                       venue: str, race_no: str) -> tuple:
    """
    schedule.json から受け取った情報で race_id を生成する。
    RACE_SCHEDULE は不要。

    race_id 形式: YYYYMMDDRRCC
      YYYY=年 MM=月 DD=日 RR=レース番号 CC=開催場ID
    """
    vid = VENUE_ID.get(venue)
    if not vid:
        raise ValueError(
            f"開催場 '{venue}' のIDが VENUE_ID に未登録です。"
            f" VENUE_ID に追加してください。"
        )

    d          = datetime.strptime(date_str, "%Y/%m/%d")
    # race_id 用は必ず2桁ゼロ埋め（例: "8" → "08"）。
    # これをしないと race_id の桁がズレてサイト側でエラーになる。
    race_no_padded = f"{int(race_no):02d}"
    race_id = f"{d.year}{d.month:02d}{d.day:02d}{race_no_padded}{vid}"
    no      = str(int(race_no))   # URLの no= パラメータはゼロ埋めなし "07" → "7"
    return race_id, date_str, no, vid

# ============================================================
# race_id 自動生成
# ============================================================
def get_entry_table(race_id: str, date: str, no: str, id_: str) -> list[dict]:
    """
    kichiuma.net から出馬表を取得し馬リストを返す。

    HTML構造:
      td[00] class=W1        : 馬番
      td[01] class=horse_box : 馬名・騎手・斤量・性齢・調教師・栗東/美浦
      td[02] class=kisyu_box : 馬主・生産者・[中XX週]
      td[03] class=dosuu_box : 距離・芝ダ・コース別成績
      td[04] class=[]        : 休養情報
      td[05] class=CY/CY3   : 前走
      td[06] class=CY/CY3   : 前々走
      td[07] class=CY/CY3   : 3走前
      td[08] class=CY/CY3   : 4走前
    """
    url = (f"https://kichiuma.net/php/search.php"
           f"?race_id={race_id}&date={date}&no={no}&id={id_}&p=rf")
    print(f"[kichiuma] {url}")

    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=15)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")

    race_form = soup.find("div", id="race_form")
    if not race_form:
        raise RuntimeError("race_formが見つかりません。race_idを確認してください。")

    horses = []
    table  = race_form.find("table")
    rows   = table.find_all("tr")

    for row in rows:
        num_td = row.find("td", class_=re.compile(r"W\d+"))
        if not num_td:
            continue

        all_tds = row.find_all("td")
        num = num_td.get_text(strip=True)

        # --- horse_box: 馬名・騎手・斤量・性齢 ---
        horse_td = next((td for td in all_tds if "horse_box" in (td.get("class") or [])), None)
        if not horse_td:
            continue

        text = horse_td.get_text(separator=" ").replace("\u3000", " ")

        name_tag = horse_td.find("span", class_="RHName")
        name     = name_tag.get_text(strip=True) if name_tag else ""
        if not name:
            # spanがない場合はテキストから馬名を推定（4文字以上カタカナ漢字）
            m = re.search(r"([ぁ-んァ-ン一-龥]{3,})", text)
            name = m.group(1) if m else ""

        # 性齢: 牡5 牝4 セ6 など
        m_sex = re.search(r"([牡牝セ])(\d)", text)
        sex_age = m_sex.group(0) if m_sex else ""

        # 斤量
        m_wt = re.search(r"(\d{2}\.\d)kg", text)
        weight = m_wt.group(1) if m_wt else ""

        # 騎手（斤量の直前）
        m_jk = re.search(r"([^\s]+)\s+\d{2}\.\dkg", text)
        jockey = m_jk.group(1) if m_jk else ""

        # 単勝オッズ: 斤量(XX.X)kgの後の最初の数値
        m_odds = re.search(r"\d{2}\.\dkg\s+([\d.]+)", text)
        odds_val = m_odds.group(1) if m_odds else ""

        # kisyu_box から通算成績を計算
        kisyu_td = next(
            (td for td in all_tds if "kisyu_box" in (td.get("class") or [])),
            None
        )
        kisyu_text = kisyu_td.get_text(separator="\n", strip=True) if kisyu_td else ""
        record     = _calc_total_record(kisyu_text)

        # オッズ戦績: "7.2 (2.0.0.1)" 形式
        odds_record = f"{odds_val} ({record})" if odds_val and record else odds_val

        # v2: dosuu_box（距離・芝ダ・コース別成績）も取得する。
        # 旧版ではコメント上「td[03]」とされながら実際には読まれておらず、
        # コース/距離適性という強い特徴量が捨てられていた。
        # まずは生テキストをそのまま保存し、蓄積→検証→指数反映の順で使う。
        dosuu_td = next(
            (td for td in all_tds if "dosuu_box" in (td.get("class") or [])),
            None
        )
        aptitude_text = dosuu_td.get_text(separator=" ", strip=True) if dosuu_td else ""

        # --- 前走データ: class=CY/CY1/CY2 の td を取得 ---
        # CY=通常, CY1=1着, CY2=2着 のバリエーションあり
        # 休養tdはclassなしなので自動的にスキップされる
        prev_tds = row.find_all("td", class_=re.compile(r'^CY'))

        def td_text(td):
            if td is None:
                return ""
            return td.get_text(separator=" ", strip=True)

        prev1 = td_text(prev_tds[0]) if len(prev_tds) > 0 else ""
        prev2 = td_text(prev_tds[1]) if len(prev_tds) > 1 else ""
        prev3 = td_text(prev_tds[2]) if len(prev_tds) > 2 else ""

        # 前走上がり3F
        # テキスト例: "新潟26.07.26 4 関屋記念GIII 芝 1600m 1:33.4不 34.4 1.0 458(+4) ..."
        # 上がり3Fは馬場状態の直後: "1:33.4不 34.4 1.0" → 34.4
        m_3f = re.search(r"\d+:\d+\.\d+[不良稍重]\s+([\d.]+)\s+[\d.]+\s+\d+", prev1)
        prev_3f = float(m_3f.group(1)) if m_3f else None

        # td[04]: 休養情報（class=[]、CYでない空クラスtd）
        kyuyo_td = next(
            (td for td in all_tds
             if not td.get("class") and td.get_text(strip=True) and
             any(kw in td.get_text() for kw in ["休養","休み","放牧"])),
            None
        )
        kyuyo_text = kyuyo_td.get_text(separator=" ", strip=True) if kyuyo_td else ""

        horses.append({
            "no"         : num,
            "name"       : name,
            "sex_age"    : sex_age,
            "weight"     : weight,
            "jockey"     : jockey,
            "odds_record": odds_record,
            "prev1"      : prev1,
            "prev2"      : prev2,
            "prev3"      : prev3,
            "prev_3f"    : prev_3f,
            "prev_raw"   : prev1,
            "kyuyo"      : kyuyo_text,
            "aptitude"   : aptitude_text,
        })
        print(f"  [{num}] {name}  前走={repr(prev1[:40])}")

    print(f"[kichiuma] {len(horses)}頭 取得完了")
    return horses



# ============================================================
# 日付ユーティリティ
# ============================================================
# ------------------------------------------------------------
# 調教テキストのパース（純粋関数・テスト可能）
# 「最終追い切り」を優先し、無ければ「N週前追い切り」を補助的に使う
# ------------------------------------------------------------
USE_WORK_FALLBACK = True   # 最終追い切りが無い馬に１週前等を使うか

_WORK_LABEL_RE = re.compile(r"(最終追い切り|[1-9１-９一二三四五六七八九]+週前追い切り)")
_WORK_CLOCK_RE = re.compile(r"(\d+F)\s+((?:\d+\.\d+-?)+)\s*（([^）]*)）")
_WORK_PLACE_RE = re.compile(r"([^\s\n]+?・[^\s\n（]+?・[良稍重不]+)[（(]([^）)]*)[）)]")


def _parse_work_text(text: str) -> list[dict]:
    """
    1頭分の調教テキストから追い切りブロックを抽出する。
    戻り値: [{"区分", "場所", "時計", "内容"}, ...]（出現順）
    追い切り無し・データなしのブロックは clock が空になる。
    """
    text = text.replace("\u3000", " ")
    blocks = []
    matches = list(_WORK_LABEL_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg = text[m.start():end]
        label = m.group(1)

        if "追い切り無し" in seg:
            blocks.append({"区分": label, "場所": "", "時計": "", "内容": ""})
            continue

        place = ""
        pm = _WORK_PLACE_RE.search(seg)
        if pm:
            place = pm.group(1)

        clock, content = "", ""
        cm = _WORK_CLOCK_RE.search(seg)
        if cm:
            dist, times, content = cm.group(1), cm.group(2), cm.group(3)
            clock = f"{dist} {times}（{content}）"

        blocks.append({"区分": label, "場所": place, "時計": clock, "内容": content})
    return blocks


def _pick_work_block(blocks: list[dict]) -> dict | None:
    """最終追い切りを優先。無ければ（フラグ有効時）直近の週前追い切りを使う。"""
    for b in blocks:
        if b["区分"] == "最終追い切り" and b["時計"]:
            return b
    if USE_WORK_FALLBACK:
        for b in blocks:
            if b["時計"]:
                return b
    return None


def get_work_data(race_name: str, year: int, work_slug: str = "") -> dict:
    """
    keibanomiryoku.com から調教データを取得する。
    最終追い切りを優先し、無い場合のみ１週前等にフォールバックする。
    戻り値: {馬名: {"調教場所・馬場", "時計", "内容", "調1F", "追切区分"}}
    """
    if not work_slug:
        print(f"[WORK] '{race_name}' の work_slug が未設定です。スキップします。")
        return {}

    url = f"https://www.keibanomiryoku.com/article/{work_slug}-{year}-work-out.html"
    print(f"[WORK] {url}")

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        html = requests.get(url, headers=headers, timeout=15).text
    except Exception as e:
        print(f"[WORK ERROR] {e}")
        return {}

    soup = BeautifulSoup(html, "html.parser")
    work_data = {}

    for h3 in soup.find_all("h3"):
        horse_name = h3.get_text(strip=True)
        if not horse_name:
            continue

        # h3 直後〜次の h3 までのテキストを結合
        parts = []
        node = h3.next_sibling
        while node:
            if getattr(node, "name", None) == "h3":
                break
            t = node.get_text("\n", strip=True) if hasattr(node, "get_text") else str(node).strip()
            if t:
                parts.append(t)
            node = getattr(node, "next_sibling", None)
        text = "\n".join(parts)

        blocks = _parse_work_text(text)
        picked = _pick_work_block(blocks)

        if picked:
            place, clock, content, label = picked["場所"], picked["時計"], picked["内容"], picked["区分"]
        else:
            place, clock, content, label = "", "", "", ""

        work_data[horse_name] = {
            "調教場所・馬場": place,
            "時計"          : clock,
            "内容"          : content,
            "調1F"          : _extract_last1f(clock),
            "追切区分"      : label,   # 例: "最終追い切り" / "１週前追い切り"
        }

    print(f"[WORK] {len(work_data)}頭分の調教データ取得")
    return work_data


def get_result_comments(race_name: str, year: int, work_slug: str = "") -> dict:
    """
    keibanomiryoku.com のレース結果ページから騎手コメントを取得する。
    work_slug: schedule.json の work_slug フィールド。
    戻り値: {馬名: コメント文字列}
    """
    if not work_slug:
        print(f"[RESULT] '{race_name}' の work_slug が未設定。スキップ。")
        return {}

    slug = work_slug
    url = f"https://www.keibanomiryoku.com/article/{slug}-{year}-results.html"
    print(f"[RESULT] {url}")

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"[RESULT] status={r.status_code} スキップ")
            return {}
        r.encoding = r.apparent_encoding
    except Exception as e:
        print(f"[RESULT ERROR] {e}")
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(separator="\n")
    comments = {}

    # パターン: "N着 馬名（騎手名）\n「コメント」" 形式
    # 例: "1着 エルトンバローズ（松若騎手）\n「道中は...」"
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # "N着 馬名" を探す
        m = re.match(r"(\d+)\s*着\s+([^\s\uff08\(]{2,12})", line)
        if m:
            horse = m.group(2).strip()
            # 続く数行からコメント（「」内）を探す
            for j in range(i, min(i + 5, len(lines))):
                cline = lines[j].strip()
                cm = re.search(r"[\u300c\u201c]([^\u300d\u201d]{10,200})[\u300d\u201d]", cline)
                if cm:
                    comments[horse] = cm.group(1).strip()
                    break
        i += 1

    # 取得件数が少ない場合: 全文から馬名+コメントを一括抽出
    if len(comments) < 3:
        pattern = re.compile(
            r"(\d+)\s*着\s+([^\s\uff08\(\n]{2,12})[^\n]*\n(?:[^\n]*\n){0,3}"
            r".*?[\u300c\u201c]([^\u300d\u201d\n]{10,200})[\u300d\u201d]",
            re.DOTALL
        )
        for m in pattern.finditer(text):
            horse   = m.group(2).strip()
            comment = m.group(3).strip()
            if horse and comment and horse not in comments:
                comments[horse] = comment

    print(f"[RESULT] {len(comments)}頭分のコメント取得")
    for name, c in list(comments.items())[:3]:
        print(f"  {name}: {c[:50]}...")
    return comments


def _extract_last1f(text: str):
    """
    時計文字列からラスト1Fを抽出する。
    例: "82.4-66.1-51.1-37.1-11.5（馬なり）" → 11.5
    """
    text = str(text)
    # 末尾の数値（全角括弧の前にあるもの）
    m = re.search(r"([\d.]+)\s*（[^）]*）?$", text)
    if m:
        return float(m.group(1))
    # 保険: 末尾数値
    m = re.search(r"([\d.]+)\s*$", text)
    if m:
        return float(m.group(1))
    return None



# ============================================================
# Claude API 前走しくじりコメント生成
# ============================================================
def detect_long_absence(kyuyo_text: str, prev1_text: str) -> str:
    """
    休養テキストまたは前走日付から長期休養明けを判定する。
    kyuyo_text: kichiumaのtd[04]テキスト（"2年10ヵ月休養"等）
    prev1_text: 前走テキスト（日付から経過月数を計算）
    """
    from datetime import datetime

    # td[04]に休養テキストがある場合（優先）
    if kyuyo_text:
        m = re.search(r"(\d+)年(?:(\d+)ヵ?月?)?休養", kyuyo_text)
        if m:
            years  = int(m.group(1))
            months = int(m.group(2)) if m.group(2) else 0
            total  = years * 12 + months
            if total >= 12:
                return f"{years}年以上の長期休養明け"
            elif total >= 6:
                return f"{years}年{months}ヵ月休養明け"

        m = re.search(r"(\d+)ヵ月休養", kyuyo_text)
        if m:
            months = int(m.group(1))
            if months >= 6:
                return f"{months}ヵ月の長期休養明け"
            elif months >= 4:
                return f"{months}ヵ月休養明け"

    # 前走日付から経過期間を計算
    if prev1_text:
        m = re.search(r"(\d{2})\.(\d{2})\.(\d{2})", prev1_text)
        if m:
            try:
                prev_date = datetime(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
                today     = datetime.today()
                elapsed   = (today.year - prev_date.year) * 12 + (today.month - prev_date.month)
                if elapsed >= 24:
                    y, mo = divmod(elapsed, 12)
                    return f"約{y}年{mo}ヵ月ぶりの実戦"
                elif elapsed >= 6:
                    return f"約{elapsed}ヵ月ぶりの実戦"
            except ValueError:
                pass

    return ""


def rule_based_mishap(prev_text: str) -> str:
    """
    kichiuma テキストからルールベースで前走コメントを生成。
    APIなしで動作するフォールバック。
    """
    if not prev_text.strip():
        return ""
    comments = []

    m_rank = re.search(r"\d{2}\.\d{2}\.\d{2}\s+(\d+)\s+", prev_text)
    rank   = int(m_rank.group(1)) if m_rank else None

    m_head = re.search(r"(\d+)ト\s*(\d+)ワク", prev_text)
    total  = int(m_head.group(1)) if m_head else None

    m_pos  = re.search(r"\d+ワク\s+([\d\-]+)", prev_text)
    if m_pos:
        positions = [int(p) for p in re.findall(r"\d+", m_pos.group(1))]
        first_pos = positions[0] if positions else None
    else:
        first_pos = None

    m_3f   = re.search(r"\d+:\d+\.\d+[良稍重不]\s+([\d.]+)\s+", prev_text)
    last3f = float(m_3f.group(1)) if m_3f else None

    m_mg   = re.search(r"\d+:\d+\.\d+[良稍重不]\s+[\d.]+\s+([\d.]+)\s+", prev_text)
    margin = float(m_mg.group(1)) if m_mg else None

    m_ba   = re.search(r"\d+:\d+\.\d+([良稍重不])", prev_text)
    baba   = m_ba.group(1) if m_ba else None

    # 後方ポジション
    if first_pos and total and total >= 10:
        ratio = first_pos / total
        if ratio >= 0.75:
            if rank and rank <= 3:
                comments.append("後方から差し切り")
            elif last3f and last3f <= 33.8:
                comments.append("後方から末脚も届かず")
            else:
                comments.append("後方で見せ場少なく")
        elif ratio >= 0.55 and rank and rank > 5 and margin and margin >= 0.5:
            comments.append("中団から伸び切れず")

    # 逃げ失速
    if first_pos == 1 and rank and rank > 4:
        comments.append("逃げて失速")

    # 先行崩れ
    if first_pos and first_pos <= 3 and rank and rank > 6 and total and total >= 12:
        comments.append("先行も崩れた")

    # 大敗
    if rank and rank >= 8:
        comments.append("大敗" if total and total >= 16 else "惨敗")

    # 道悪大敗→良馬場替わり
    if baba in ["不", "重"] and rank and rank >= 6:
        comments.append("道悪大敗→良馬場替わり注意")

    # 道悪巧者
    if baba in ["不", "重"] and rank and rank <= 3:
        comments.append("道悪巧者")

    # 末脚あるが着外
    if last3f and last3f <= 33.5 and rank and rank > 5:
        comments.append("末脚あるが展開向かず")

    # 僅差好走
    if margin is not None and margin <= 0.1 and rank and rank >= 2:
        comments.append("僅差の好内容")

    return " ".join(comments[:2])


def _describe_prev_race(h: dict) -> str:
    """
    _parse_kichiuma_result で構造化した前走データを、
    プロンプトに渡しやすい短い説明文にする。
    """
    prev = h.get("prev_raw", "")
    if not prev:
        return ""
    info = _parse_kichiuma_result(prev)
    parts = []
    if info.get("track"):
        parts.append(info["track"])
    if info.get("grade"):
        parts.append(info["grade"])
    if info.get("surface") and info.get("distance"):
        parts.append(f"{info['surface']}{info['distance']}m")
    if info.get("rank"):
        parts.append(f"{info['rank']}着")
    if info.get("popularity"):
        parts.append(f"{info['popularity']}人気")
    if info.get("margin") is not None:
        parts.append(f"着差{info['margin']}")
    if info.get("last3f") is not None:
        parts.append(f"上がり{info['last3f']}")
    return " ".join(parts)


def generate_mishap_comments(horses: list[dict], result_comments: dict = None, rawdata: dict = None) -> dict[str, str]:
    """
    前走コメントを生成する。
    ANTHROPIC_API_KEY が設定されていれば Claude API を使用。
    未設定またはエラー時はルールベースにフォールバック。

    仕様変更点:
      - 「しくじりがあるときだけ書く」ではなく、前走データがある馬には
        原則として必ず一言コメントを返す（好走内容・展開・上がり脚質なども対象）。
      - _parse_kichiuma_result で構造化した数値情報もプロンプトに含め、
        Claudeが根拠を持ってコメントできるようにする。
      - 頭数に応じて max_tokens を可変にし、JSON応答が途中で切れないようにする。
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    targets = [h for h in horses if h.get("prev_raw")]

    # ---- Claude API ----
    if api_key and targets:
        horse_list_parts = []
        for h in targets:
            name = h['name']
            prev = h.get('prev_raw', '')
            summary = _describe_prev_race(h)
            grade = _extract_grade(prev)

            entry = f"・{name}({h['no']}番)"
            if summary:
                entry += f" [{summary}]"
            # グレードはコード側で確定済みの値を明示的に渡す。
            # モデルには生データからグレードを読み取らせず、この値をそのまま使わせる。
            entry += f"\n  グレード（確定値・これ以外の表記に変更しないこと）: {grade if grade else '重賞・特別ではない一般競走'}"
            entry += f"\n  生データ: {prev}"

            # 前走レース後の騎手コメントがあれば追加
            rc = (result_comments or {}).get(name, '')
            if rc:
                entry += f"\n  【前走後コメント】{rc}"

            # 休養情報をプロンプトに含める
            absence = (rawdata or {}).get(name, {}).get("休養情報", "")
            if absence:
                entry += f"\n  【休養情報】{absence}"

            horse_list_parts.append(entry)

        horse_list = "\n".join(horse_list_parts)

        prompt = (
            "以下は競馬の各馬の前走データです。\n"
            "各馬について、次走に向けて参考になる一言コメントを20文字以内で書いてください。\n\n"
            "コメントの観点（該当するものを優先。特にしくじり系は配当妙味に直結するため最優先で拾うこと）:\n"
            "・しくじり（スタート/道中）: 出遅れ、ゲートで躓いた、入れ込みすぎて折り合い欠く、"
            "行きたがって掛かった、砂を被って嫌がった、他馬にぶつけられた、挟まれて手前を替えられず\n"
            "・しくじり（コース取り/進路）: 直線で進路が狭くなる、進路なく待たされた、"
            "大外を回した、終始外々を回らされ距離ロス、前が壁になり不完全燃焼\n"
            "・しくじり（展開/騎乗）: 仕掛けが遅れた、早仕掛けで失速、ハイペースの犠牲、"
            "スローに対応できず、鞍上の判断ミスが響いた、位置取りが悪く終始後手\n"
            "・しくじり（適性/コンディション）: 馬場が合わなかった（道悪/高速馬場）、"
            "距離が長かった/短かった、初コース・初回りで戸惑った、返し馬で気配ひと息、"
            "馬体重の増減が大きく仕上がり不安\n"
            "・好走内容: 上がり最速、直線一気、余裕残し、内容以上の着順、格上相手に善戦\n"
            "・展開/脚質: 逃げて粘った、後方から追い込み届かず、道悪巧者\n"
            "・休養明けや初距離・初コースなど特記事項\n\n"
            "重要な制約:\n"
            "・グレード表記は各馬データの「グレード（確定値）」を一字一句そのまま使うこと。"
            "生データの文字列から自分でグレードを読み取ったり、GIとGIIIのような表記を混同したりしないこと。\n"
            "・着順・人気・上がりタイムなどの数値は生データにある値のみを使い、推測や誇張をしないこと。\n"
            "・前走データが乏しく判断材料がない場合のみ空文字にしてください。"
            "それ以外はできる限り全頭に何かしらのコメントをつけてください。\n\n"
            "必ずJSON形式のみで返してください（前後に説明文をつけない）。例:\n"
            '{"馬名A": "出遅れ響いた終い伸び", "馬名B": "上がり最速の内容", "馬名C": "直線進路なく不完全燃焼"}\n\n'
            f"馬のリスト:\n{horse_list}"
        )

        # 頭数に応じてトークン上限を可変に（1頭あたり目安120トークン、最低1500）
        max_tokens = max(1500, len(targets) * 120)

        try:
            # client = anthropic.Anthropic(api_key=api_key)
            # msg = client.messages.create(
            #     model="claude-sonnet-4-6",
            #     max_tokens=max_tokens,
            #     messages=[{"role": "user", "content": prompt}],
            # )

            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )            

            raw = msg.content[0].text.strip()

            comments = None
            # 1. そのままJSONとして読めるか
            try:
                comments = json.loads(raw)
            except json.JSONDecodeError:
                pass

            # 2. ダメなら { } で囲まれた最大範囲を抽出
            if comments is None:
                json_m = re.search(r"\{.*\}", raw, re.DOTALL)
                if json_m:
                    try:
                        comments = json.loads(json_m.group(0))
                    except json.JSONDecodeError:
                        comments = None

            if comments is not None:
                print(f"[COMMENT] Claude API: {len(comments)}頭分 生成完了")
                # API側が一部の馬を返し忘れた場合はルールベースで補完
                missing = [h for h in targets if h["name"] not in comments or not comments.get(h["name"])]
                for h in missing:
                    fallback = rule_based_mishap(h.get("prev_raw", "")) or _describe_prev_race(h)
                    if fallback:
                        comments[h["name"]] = fallback
                if missing:
                    print(f"[COMMENT] {len(missing)}頭をルールベース/前走概要で補完")
                return comments
            else:
                print(f"[COMMENT] Claude API応答をJSONとして解釈できませんでした: {raw[:200]}")
        except Exception as e:
            print(f"[COMMENT] Claude APIエラー: {e}")
            print("[COMMENT] ルールベースにフォールバック")

    # ---- ルールベース（フォールバック） ----
    print("[COMMENT] ルールベースでコメント生成")
    result = {}
    for h in horses:
        c = rule_based_mishap(h.get("prev_raw", ""))
        if not c:
            c = _describe_prev_race(h)
        result[h["name"]] = c
    return result


# ============================================================
# v2: 勝率の確率化・市場ブレンド・信頼度判定（純粋関数群）
#
# 方針:
#   - 指数そのものの作り方（rating.py 等）は変えない。ここは
#     「指数 → 確率 → 買う/見送りの判断」に変換する層だけを足す。
#   - パラメータは環境変数で上書き可能にし、backtest.py の
#     グリッドサーチ結果をそのまま反映できるようにする。
#   - しきい値・重みはすべて「実績未検証の初期値」。
#     過去データで検証せずに本番の重みを上げないこと。
# ============================================================
PROB_TEMPERATURE = float(os.environ.get("PROB_TEMPERATURE", "12.0"))  # v3: 実績18Rで検証した値 (クラススコア用)
MARKET_BLEND     = float(os.environ.get("MARKET_BLEND", "0.50"))      # v3: 実績18Rで検証した値 市場の勝率の混合率 0..1
CONF_STRONG_PROB = float(os.environ.get("CONF_STRONG_PROB", "0.32"))  # 「勝負」判定: 1位の確率
CONF_STRONG_GAP  = float(os.environ.get("CONF_STRONG_GAP", "0.08"))   # 「勝負」判定: 1位と2位の確率差
CONF_NORMAL_PROB = float(os.environ.get("CONF_NORMAL_PROB", "0.22"))  # 「通常」判定: 1位の確率


def parse_win_odds(odds_record: str):
    """'7.2 (2.0.0.1)' のような オッズ戦績 文字列から単勝オッズ(float)を取り出す。無ければ None"""
    m = re.match(r"\s*([\d.]+)", str(odds_record or ""))
    if not m:
        return None
    try:
        v = float(m.group(1))
        return v if v > 1.0 else None
    except ValueError:
        return None


def model_win_probs(rows: list[dict], temperature: float = None) -> dict:
    """
    補正後指数 adjusted_index を softmax で勝率に変換する。
    戻り値: {馬番: 確率}（合計は1.0）。指数が同点なら均等に近づく。
    """
    t = PROB_TEMPERATURE if temperature is None else temperature
    t = max(0.5, float(t))
    scores = {r["馬番"]: float(r.get("adjusted_index", 0) or 0) for r in rows}
    if not scores:
        return {}
    mx = max(scores.values())
    exps = {k: math.exp((v - mx) / t) for k, v in scores.items()}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()}


def market_win_probs(rows: list[dict]) -> dict:
    """
    単勝オッズの逆数から市場の勝率を作り、控除率分を正規化して合計1にする。
    オッズが取れない馬が1頭でもいれば市場ブレンドは行わず {} を返す
    （中途半端なブレンドは順位を歪めるため）。
    """
    raw = {}
    for r in rows:
        odds = parse_win_odds(r.get("オッズ戦績", ""))
        if odds is None:
            return {}
        raw[r["馬番"]] = 1.0 / odds
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()} if total > 0 else {}


def blend_probs(model: dict, market: dict, blend: float = None) -> dict:
    """モデル確率と市場確率の加重平均。市場が無ければモデル確率をそのまま返す。"""
    if not market:
        return dict(model)
    b = MARKET_BLEND if blend is None else blend
    b = max(0.0, min(1.0, float(b)))
    out = {k: (1 - b) * p + b * market.get(k, 0.0) for k, p in model.items()}
    total = sum(out.values())
    return {k: v / total for k, v in out.items()} if total > 0 else dict(model)


# ============================================================
# v3: クラス調整スコア
#
# 実績18レース (2026/7/5〜10/24) の診断で判明したこと:
#   - 従来の総合指数は「勝ち馬の指数順位の中央値が8位」と、
#     ほぼランダムに近い並びだった (1位指名の単勝的中 3/18)。
#   - 原因のひとつは、タイム指数がコースレコードとの差だけで、
#     レースの格 (クラス) を見ていないこと。格上挑戦の凡走と
#     格下での好走が同じ物差しで測られていた。
#   - そこで「着順のパーセンタイル + 格付け点」を直近重視で
#     加重したクラス調整スコアを作り、前走人気で微調整する。
#     検証結果 (全18R): このスコア単体で 複勝(1位指名が3着内) 10/18、
#     市場ブレンド後は 単勝 6/18・複勝 12/18。未来側8Rでも
#     複勝 5/8 と、従来指数 (3/8)・人気のみ (4/8) を上回った。
#     ただし n=18 は小さく、単勝の未来側は人気・従来と同数 (2/8)。
#     「複勝・フォーメーションの改善」として採用し、単勝の
#     優位性は今後のデータ蓄積で再検証すること。
# ============================================================
GRADE_POINTS = {"GI": 12, "Jpn1": 12, "GII": 9, "Jpn2": 9,
                "GIII": 6, "Jpn3": 6, "OP": 3, "L": 3}
CLASS_WEIGHTS = (0.5, 0.3, 0.2)   # 前走 / 前々走 / 3走前


def class_ability_score(raw: dict):
    """
    rawdata の前3走テキストからクラス調整スコアを返す。前走データが無い馬は None。
    スコア = Σ[ (1-(着順-1)/(頭数-1))*100 + 格付け点 ] を CLASS_WEIGHTS で加重
             - (前走人気-1) * 1.5
    """
    weighted = 0.0
    w_total = 0.0
    first_pop = None
    for i, key in enumerate(("前走", "前々走", "3走前")):
        text = str((raw or {}).get(key, "") or "")
        if not text.strip():
            continue
        info = _parse_kichiuma_result(text)
        rank = info.get("rank")
        if not rank:
            continue
        m_field = re.search(r"(\d+)ト", text)
        field = int(m_field.group(1)) if m_field else 16
        pct = (1 - (rank - 1) / max(1, field - 1)) * 100
        weighted += (pct + GRADE_POINTS.get(info.get("grade", ""), 0)) * CLASS_WEIGHTS[i]
        w_total += CLASS_WEIGHTS[i]
        if i == 0:
            first_pop = info.get("popularity")
    if w_total == 0:
        return None
    score = weighted / w_total
    if first_pop:
        score -= (first_pop - 1) * 1.5
    return round(score, 1)


def model_probs_from_scores(scores: dict, temperature: float = None) -> dict:
    """{馬番: スコア} を softmax で勝率に変換する (合計1.0)"""
    if not scores:
        return {}
    t = max(0.5, PROB_TEMPERATURE if temperature is None else float(temperature))
    mx = max(scores.values())
    exps = {k: math.exp((v - mx) / t) for k, v in scores.items()}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()}


def race_recommendation(probs: dict) -> dict:
    """
    確率の集中度から買い方を3段階で返す。
    的中率を上げる要点は「全部のレースを同じだけ買わない」こと。
    見送り推奨のレースを実際に見送った場合の的中率は backtest.py で測る。
    しきい値は初期値（未検証）。backtest.py の結果で調整すること。
    """
    if not probs:
        return {"label": "判定不能", "top1_prob": None, "gap": None}
    ordered = sorted(probs.values(), reverse=True)
    top1 = ordered[0]
    gap = round(top1 - ordered[1], 4) if len(ordered) >= 2 else top1
    if top1 >= CONF_STRONG_PROB and gap >= CONF_STRONG_GAP:
        label = "勝負（信頼度・高）"
    elif top1 >= CONF_NORMAL_PROB:
        label = "通常"
    else:
        label = "見送り推奨（信頼度・低）"
    return {"label": label, "top1_prob": round(top1, 4), "gap": gap}


# ============================================================
# JSON組み立て
# ============================================================
# ============================================================
# v4r 追加：記録専用の特徴量（予想ロジックには一切使わない）
# 将来の候補検証（馬場適性・脚質・騎手など）のために、発走前の時点で
# 得られる情報を構造化して保存する。v4 からの変更はこの記録追加のみで、
# 順位・確率・買い目・推奨の計算には手を入れていない。
# ============================================================
def calc_wakuban(baban: int, tousuu: int) -> int:
    """馬番と頭数から枠番を求める（JRAの枠番割り付けルール）。
    9頭以上では8枠に配分し、余りは後ろの枠から1頭ずつ増やす。"""
    if tousuu <= 8:
        return baban
    base, r = divmod(tousuu, 8)
    sizes = [base + (1 if i >= 8 - r else 0) for i in range(8)]
    acc = 0
    for i, s in enumerate(sizes):
        acc += s
        if baban <= acc:
            return i + 1
    return 8


def parse_past_race_features(texts: list) -> dict:
    """過去走テキスト（kichiuma形式）から候補検証用の特徴量を抽出する純粋関数。
    馬場別成績（良/稍重/重/不良ごとの出走数・3着内数）、脚質前方率
    （最初の通過順位÷頭数の平均。小さいほど前で競馬をする）、
    前走の馬体重・増減・騎手を返す。"""
    going_stats = {"良": [0, 0], "稍重": [0, 0], "重": [0, 0], "不良": [0, 0]}
    front_rates = []
    n_parsed = 0
    for text in texts:
        if not text:
            continue
        m_fin = re.search(r"\d{2}\.\d{2}\.\d{2}\s+(\d{1,2})\s", text)
        m_go = re.search(r"\d+:\d+\.\d(良|稍重|重|不良)", text)
        m_hd = re.search(r"(\d+)ト\s*\d+ワク\s+(\d+)", text)
        if m_fin and m_go:
            fin = int(m_fin.group(1))
            st = going_stats[m_go.group(1)]
            st[0] += 1
            if fin <= 3:
                st[1] += 1
            n_parsed += 1
        if m_hd:
            field = int(m_hd.group(1))
            pos1 = int(m_hd.group(2))
            if field > 0:
                front_rates.append(pos1 / field)
    last_weight = None
    last_weight_diff = None
    last_jockey = None
    if texts and texts[0]:
        m_wt = re.search(r"(\d{3})\(([+-]?\d+)\)", texts[0])
        if m_wt:
            last_weight = int(m_wt.group(1))
            last_weight_diff = int(m_wt.group(2))
        m_jk = re.search(r"\d{2}\.\d([^\d\s]+?)\d+人", texts[0])
        if m_jk:
            last_jockey = m_jk.group(1)
    return {
        "馬場別成績": {k: {"出走": v[0], "3着内": v[1]} for k, v in going_stats.items()},
        "脚質前方率": (round(sum(front_rates) / len(front_rates), 3) if front_rates else None),
        "前走馬体重": last_weight,
        "前走馬体重増減": last_weight_diff,
        "前走騎手": last_jockey,
        "特徴量対象走数": n_parsed,
    }


def build_json(race_name: str, horses: list[dict],
               work: dict, comments: dict,
               rawdata: dict,
               venue: str = "", date_str: str = "") -> dict:
    """
    kichiuma / keibanomiryoku / 各モジュールのデータを統合して
    pyxelビューア用JSONを生成する

    rawdata : {馬名: {前走, 前々走, 3走前, ...}} kichiuma から取得した生データ
    venue   : 開催場名（schedule.json から渡す）
    date_str: 開催日 "YYYY/M/D"（schedule.json から渡す）
    """

    # ---- Step1: 全馬の基本行を作る ----
    rows = []
    for h in horses:
        name = h["name"]
        w    = work.get(name, {})
        raw  = rawdata.get(name, {})
        no   = int(h["no"]) if h["no"].isdigit() else 0

        # 脚質判定（rawdata の前走テキストから）
        style = get_running_style(raw)

        # レース指数（前走・前々走・3走前）
        r1 = single_race_rating(raw.get("前走", ""))
        r2 = single_race_rating(raw.get("前々走", ""))
        r3 = single_race_rating(raw.get("3走前", ""))

        # ==========================================
        # A：現在能力
        # ==========================================
        ability_rating = calc_current_ability(
            r1, r2, r3
        )

        # ==========================================
        # B：上昇・下降度
        # ==========================================
        trend_score = calc_trend_score(
            r1, r2, r3
        )

        # ==========================================
        # A＋B：今回の基礎指数
        # ==========================================
        base_rating = round(
            ability_rating + trend_score
        )

        # 上がり3F: kichiuma取得済みの値を優先、なければ前走テキストから抽出
        prev_3f = h.get("prev_3f")
        if prev_3f is None:
            m3f = re.search(r"\s(3[0-9]\.\d)\s+[\d.]+\s+\d{3}", str(raw.get("前走","")))
            prev_3f = float(m3f.group(1)) if m3f else None

        # 調教評価
        w_rank = get_workout_rank(w) if w else "D"
        w_score = calc_workout_score(w) if w else 0
        last1f = w.get("調1F")

        rows.append({
            "馬番"      : no,
            "馬名"      : name,
            "オッズ戦績": h.get("odds_record", ""),
            "性齢"      : h["sex_age"],
            "斤量"      : h["weight"] + "kg" if h["weight"] else "",
            "騎手"      : h["jockey"],
            "脚質"      : style,

            # A+Bを基礎指数として使用
            "レース指数"  : base_rating,

            # 3走の個別指数
            "前走"      : r1 if r1 > 0 else None,
            "前々"      : r2 if r2 > 0 else None,
            "3走"       : r3 if r3 > 0 else None,

            "前3F"      : prev_3f,
            "調1F"      : last1f,
            "印"        : "",

            # 詳細指数
            "前走指数"  : r1,
            "前々走指数": r2,
            "3走前指数" : r3,

            # A
            "3走指数"  : ability_rating,

            # B
            "上昇下降度": trend_score,

            "追切評価"  : w_rank,
            "追切スコア": w_score,
            "前走コメント": comments.get(name, ""),
        })


    # ---- Step2: 展開予想（全馬の脚質が揃ってから） ----
    df_pace = pd.DataFrame(rows)
    pace = predict_pace(df_pace)


    # ---- Step3: 激走指数・コメント ----
    for r in rows:
        r["展開予想"]    = pace
        # v4: 修正版 reporting.calc_gekisou_index が前走の人気・着順・上がりを
        # 読めるよう、前走テキストを渡す (従来は数値の指数しか渡っておらず、
        # 人気×着順ギャップと切れ味ボーナスが常に0だった)
        _r = dict(r)
        _r["前走テキスト"] = rawdata.get(r["馬名"], {}).get("前走", "")
        r["激走P"]    = calc_gekisou_index(_r)
        r["新聞コメント"] = make_comment(r)

    # ---- レース内最大値を10点として正規化 ----
    max_gekisou = max(r["激走P"] for r in rows)
    for r in rows:
        if max_gekisou > 0:
            gekisou_bonus = round(r["激走P"] / max_gekisou * 10, 1)
        else:
            gekisou_bonus = 0
        r["激走指数"] = gekisou_bonus        

    # ---- Step4: しくじり補正 + 斤量補正 → 補正後総合指数 ----
    max_weight, max_sex_age = get_max_weight(rows)
    for r in rows:
        mishap_comment = r.get("前走コメント", "")
        weight_str     = r.get("斤量", "")
        base           = r.get("レース指数", 0)
        sex_str        = r.get("性齢", "")        

        gekisou_bonus = r.get("激走指数", 0)

        mishap_bonus  = calc_mishap_bonus(mishap_comment)
        weight_bonus  = calc_weight_bonus(weight_str, max_weight, sex_str , max_sex_age)
        adjusted      = calc_adjusted_index(base, mishap_comment, weight_str , max_weight , sex_str , max_sex_age , gekisou_bonus)

        r["しくじり補正"] = mishap_bonus
        r["斤量補正"]     = weight_bonus
        r["adjusted_index"] = adjusted

        if mishap_bonus > 0 or weight_bonus > 0:
            print(f"  [補正] {r['馬名']}: 基礎{base} + しくじり{mishap_bonus} + 斤量{weight_bonus} + 激走指数{gekisou_bonus} = {adjusted}")

    # ---- v3 Step5': クラス調整スコア → 勝率 → 最終ランキング ----
    # モデル確率は「総合指数」ではなく「クラス調整スコア」から作る。
    # (実績検証で、総合指数は勝ち馬をほぼ当てられていなかったため)
    for r in rows:
        r["クラススコア"] = class_ability_score(rawdata.get(r["馬名"], {}))
    _class_scores = {
        r["馬番"]: (r["クラススコア"] if r["クラススコア"] is not None else 40.0)
        for r in rows
    }
    _model_probs  = model_probs_from_scores(_class_scores)
    _market_probs = market_win_probs(rows)
    _final_probs  = blend_probs(_model_probs, _market_probs)
    for r in rows:
        r["win_prob"] = _final_probs.get(r["馬番"], 0.0)
    recommendation = race_recommendation(_final_probs)
    prediction = [
        {
            "馬番"      : r["馬番"],
            "馬名"      : r["馬名"],
            "class_score": r["クラススコア"],
            "model_prob": round(_model_probs.get(r["馬番"], 0.0), 4),
            "market_prob": (round(_market_probs[r["馬番"]], 4) if r["馬番"] in _market_probs else None),
            "win_prob"  : round(_final_probs.get(r["馬番"], 0.0), 4),
        }
        for r in sorted(rows, key=lambda r: -r["win_prob"])
    ]
    print(f"[PREDICT] 推奨={recommendation['label']} "
          f"1位確率={recommendation['top1_prob']} 差={recommendation['gap']} "
          f"市場ブレンド={'あり' if _market_probs else 'なし(オッズ不足)'}")

    # ---- Step5: 補正後指数で印を付ける (印の付け方は従来通り) ----
    assign_marks(rows)

    # v3: フォーメーションは最終確率 (win_prob) の高い順で確定させる。
    # ※単勝オッズを使う「想定オッズ」の計算は行わない
    #   （単勝オッズは土日で何度も動くため、update_odds.py 側で
    #    オッズ更新のたびに再計算する）
    ranked_rows = sorted(rows, key=lambda r: -r.get("win_prob", 0))
    ranked_nos  = [str(r["馬番"]) for r in ranked_rows]
    try:
        formation = build_formation(ranked_nos)
        betting_formation = {
            "umaren"    : [list(c) for c in formation["umaren"]],
            "sanrenpuku": [list(c) for c in formation["sanrenpuku"]],
        }
    except ValueError as e:
        print(f"[FORMATION] フォーメーション生成スキップ: {e}")
        betting_formation = {}

    # 「堅い/荒れる」判定：補正後指数1位と6位（3連複フォーメーション3列目の末尾）の
    # 差を1位の値に対する比率で見る。指数の配点方式（スケール）に依存しないよう、
    # 絶対値ではなく相対差で判定する。
    #
    # ※しきい値(0.35/0.20/0.10)は実績データで検証したものではなく、
    #   経験則としての初期値。実際の出力を見ながら調整すること。
    race_shape = {"label": "判定不能", "gap_ratio": None}
    _adj_ranked = sorted(rows, key=lambda r: -r.get("adjusted_index", 0))
    if len(_adj_ranked) >= 6:
        top1 = _adj_ranked[0].get("adjusted_index", 0)
        top6 = _adj_ranked[5].get("adjusted_index", 0)
        if top1 > 0:
            gap_ratio = round((top1 - top6) / top1, 3)
            if   gap_ratio >= 0.35: label = "堅い"
            elif gap_ratio >= 0.20: label = "やや堅い"
            elif gap_ratio >= 0.10: label = "やや荒れる"
            else:                   label = "荒れる"
            race_shape = {"label": label, "gap_ratio": gap_ratio}

    # 馬番順に戻す
    rows.sort(key=lambda r: r["馬番"])

    # pyxel 表示用と rawdata 用を分離
    pyxel_rows = [{
        "馬番"    : r["馬番"],
        "馬名"    : r["馬名"],
        "オッズ戦績": r["オッズ戦績"],
        "性齢"    : r["性齢"],
        "斤量"    : r["斤量"],
        "騎手"    : r["騎手"],
        "脚質"    : r["脚質"],
        "総合指数": r.get("adjusted_index", r["レース指数"]),
        "前走"    : r["前走"],
        "前々"    : r["前々"],
        "3走"     : r["3走"],
        "前3F"    : r["前3F"],
        "調1F"    : r["調1F"],
        "印"      : r["印"],
    } for r in rows]

    summary_rows = [{
        "馬名"        : r["馬名"],
        "能力指数"    : r["レース指数"],
        "補正後指数"  : r.get("adjusted_index", r["レース指数"]),
        "しくじり補正": r.get("しくじり補正", 0),
        "斤量補正"    : r.get("斤量補正", 0),
        "追切評価"    : r["追切評価"],
        "激走指数"    : r["激走指数"],
        "クラススコア": r.get("クラススコア"),
        "勝率"        : round(r.get("win_prob", 0.0), 4),
        "新聞コメント": r["新聞コメント"],
        "前走コメント": r["前走コメント"],
        "備考"        : f"予想ペース：{pace}",
    } for r in rows]

    # v4r: 記録拡張（予想ロジックは v4 から不変更）
    _tousuu = len(rows)
    horse_data = []
    for r in rows:
        _raw = rawdata.get(r["馬名"], {})
        _feat = parse_past_race_features(
            [_raw.get(k, "") for k in ("前走", "前々走", "3走前", "4走前")])
        horse_data.append({
            "馬番"      : r["馬番"],
            "馬名"      : r["馬名"],
            "枠番"      : calc_wakuban(int(r["馬番"]), _tousuu),
            "騎手"      : r["騎手"],
            "斤量"      : r["斤量"],
            "脚質"      : r["脚質"],
            "追切評価"  : r["追切評価"],
            "追切スコア": r["追切スコア"],
            **_feat,
        })

    return {
        "race_name": race_name,
        "course"   : venue,
        "distance" : "",
        "date"     : date_str,
        "pace"     : pace,
        "pyxel"    : pyxel_rows,
        "summary"  : summary_rows,
        "rawdata"  : [rawdata.get(r["馬名"], {}) | {"馬名": r["馬名"]} for r in rows],
        "workdata" : work,
        "betting_formation": betting_formation,
        "race_shape": race_shape,
        # v2追加: 確率と買い方判定。update_odds.py 側でオッズ更新時に
        # market_win_probs / blend_probs を再計算すると、最終オッズに
        # 基づく確率・推奨に更新できる（関数はいずれも純粋関数）。
        "prediction": prediction,
        "horse_data": horse_data,
        "recommendation": recommendation,
        "prediction_params": {
            "temperature": PROB_TEMPERATURE,
            "market_blend": MARKET_BLEND if _market_probs else 0.0,
        },
    }


# ============================================================
# GitHub Pages index.json 更新
# ============================================================
def update_index_json(data_dir: str, new_filename: str):
    """
    DATA/index.json にファイル名を追加（重複なし・降順）
    """
    index_path = os.path.join(data_dir, "index.json")
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            files = json.load(f)
    else:
        files = []

    if new_filename not in files:
        files.insert(0, new_filename)   # 先頭に追加（新しい順）
        files = files[:30]              # 最大30件

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(files, f, ensure_ascii=False, indent=2)
    print(f"[INDEX] {index_path} 更新完了 ({len(files)}件)")


# ============================================================
# メイン
# ============================================================
def _load_race_from_schedule(race_name: str) -> dict:
    """
    schedule.json から指定レースの情報を読み込む。
    直接 python JRA_read_next.py で実行するときのフォールバック。
    """
    import json as _j
    from pathlib import Path as _P
    path = _P(__file__).parent / "schedule.json"
    if not path.exists():
        return {}
    sc = _j.loads(path.read_text(encoding="utf-8"))
    for r in sc.get("races", []):
        if r.get("race_name") == race_name:
            return r
    return {}


def main(race_name: str = None, date_str: str = None,
         venue: str = None, race_no: str = None, work_slug: str = None):
    """
    schedule.json から渡された情報でレースを処理する。

    race_name : レース名
    date_str  : 開催日 "YYYY/M/D"
    venue     : 開催場 "札幌"/"東京" 等
    race_no   : レース番号 "11"/"07" 等
    work_slug : keibanomiryoku.com の URL スラグ "sapporo-kinen" 等
    """
    if race_name is None:
        race_name = TARGET_RACE

    # 引数が不足している場合は schedule.json から自動補完
    # （直接 python JRA_read_next.py で実行した場合のフォールバック）
    if not date_str or not venue or not race_no:
        info = _load_race_from_schedule(race_name)
        if not info:
            print(f"[ERROR] '{race_name}' が schedule.json に見つかりません。")
            print("  schedule.json にレースを追加してください。")
            return
        date_str  = date_str  or info.get("date", "")
        venue     = venue     or info.get("venue", "")
        race_no   = race_no   or info.get("race_no", "")
        work_slug = work_slug or info.get("work_slug", "")
        print(f"[SCHEDULE] '{race_name}' の情報を schedule.json から自動読込しました")

    print(f"=== {race_name} データ生成開始 ===")

    # 1. race_id 自動生成
    if not date_str or not venue or not race_no:
        print(f"[ERROR] date/venue/race_no が schedule.json に設定されていません。")
        return

    race_id, date_str, no, id_ = build_race_params(race_name, date_str, venue, race_no)

    # RACE_DATE をレースの実際の開催日に設定
    global RACE_DATE
    RACE_DATE = datetime.strptime(date_str, "%Y/%m/%d")
    print(f"[DATE] 開催日: {RACE_DATE.strftime('%Y/%m/%d')}")
    print(f"[RACE] race_id={race_id}  date={date_str}  no={no}  id={id_}")

    # 2. kichiuma.net から出馬表取得
    horses = get_entry_table(race_id, date_str, no, id_)
    if not horses:
        print("[ERROR] 出馬表が取得できませんでした")
        return

    # 3. keibanomiryoku.com から調教データ取得
    work = get_work_data(race_name, RACE_DATE.year, work_slug or "")

    # 4. 前走レース後コメントを取得
    prev_race_comments = {}
    prev_race_year_map = {}   # {(prev_race_name, year, work_slug): [馬名, ...]}

    # schedule.json から前走レースのwork_slugを逆引きするため全レースを読む
    import json as _json
    from pathlib import Path as _Path
    schedule_path = _Path(__file__).parent / "schedule.json"
    slug_lookup = {}   # {race_name: work_slug}
    if schedule_path.exists():
        sc = _json.loads(schedule_path.read_text(encoding="utf-8"))
        for r in sc.get("races", []):
            if r.get("race_name") and r.get("work_slug"):
                slug_lookup[r["race_name"]] = r["work_slug"]

    for h in horses:
        name      = h["name"]
        prev_text = h.get("prev1", "")
        if not prev_text:
            continue

        m_yr = re.search(r"(\d{2})\.(\d{2})\.(\d{2})", prev_text)
        if not m_yr:
            continue
        prev_year = 2000 + int(m_yr.group(1))

        # 前走レース名をslug_lookupのキーと照合
        matched = ""
        for rname in slug_lookup.keys():
            if rname in prev_text and len(rname) > len(matched):
                matched = rname

        if matched:
            prev_slug = slug_lookup.get(matched, "")
            key = (matched, prev_year, prev_slug)
            prev_race_year_map.setdefault(key, []).append(name)

    print(f"[RESULT] 前走レース: {[(k[0], k[1]) for k in prev_race_year_map.keys()]}")

    for (prev_rname, prev_year, prev_slug), target_horses in prev_race_year_map.items():
        print(f"[RESULT] {prev_rname} {prev_year}年 → 対象馬: {target_horses}")
        result = get_result_comments(prev_rname, prev_year, prev_slug)
        if not result:
            result = get_result_comments(prev_rname, prev_year - 1, prev_slug)
        if result:
            for horse_name in target_horses:
                if horse_name in result:
                    prev_race_comments[horse_name] = result[horse_name]
                    print(f"  ✓ {horse_name}: {result[horse_name][:40]}...")
                else:
                    print(f"  - {horse_name}: コメントなし")

    # 5. rawdata 組み立て
    rawdata = {}
    for h in horses:
        name  = h["name"]
        w     = work.get(name, {})
        prev1 = h.get("prev1", "")
        prev2 = h.get("prev2", "")
        prev3 = h.get("prev3", "")
        print(f"[RAW] {name}: 前走={repr(prev1[:50]) if prev1 else '(空)'}")
        kyuyo   = h.get("kyuyo", "")
        absence = detect_long_absence(kyuyo, prev1)
        if absence:
            print(f"  [休養] {name}: {absence}")
        rawdata[name] = {
            "馬名"          : name,
            "前走"          : prev1,
            "前々走"        : prev2,
            "3走前"         : prev3,
            "調教場所・馬場" : w.get("調教場所・馬場", ""),
            "時計"          : w.get("時計", ""),
            "内容"          : w.get("内容", ""),
            "休養情報"      : absence,
            "適性データ"    : h.get("aptitude", ""),   # v2: dosuu_box（距離・芝ダ・コース別成績）
        }
    print(f"[RAW] rawdata {len(rawdata)}頭分 組み立て完了")

    # 6. Claude API で前走しくじりコメント生成
    comments = generate_mishap_comments(horses, prev_race_comments, rawdata)

    # 7. JSON組み立て
    data = build_json(race_name, horses, work, comments, rawdata,
                    venue=venue, date_str=date_str)
    # update_odds.py が参照するためrace_id等をJSONに追加
    data["race_id"]  = race_id
    data["race_no"]  = race_no
    data["venue_id"] = id_

    # 8. ファイル保存
    course   = data.get("course", venue)
    dist     = data.get("distance", "")
    date_tag = RACE_DATE.strftime("%y%m%d")
    filename = f"{date_tag}_{course}{dist}_{race_name}.json"

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DATA/races")
    os.makedirs(data_dir, exist_ok=True)
    out_path = os.path.join(data_dir, filename)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[SAVE] {out_path}")

    # # 9. index.json 更新
    # update_index_json(data_dir, filename)
    print(f"=== 完了: {filename} ===")


if __name__ == "__main__":
    main()
