# ============================================================
# JRA_read_next.py  競馬予想データ自動生成 次期バージョン
#
# 【変更点】
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
from records   import get_record, time_to_seconds
from pace      import get_running_style
from rating    import single_race_rating, horse_rating
from workout   import calc_workout_score, get_workout_rank
from reporting   import predict_pace, calc_gekisou_index, make_comment
from adjustment  import calc_mishap_bonus, calc_weight_bonus, \
                        get_max_weight, calc_adjusted_index, assign_marks

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
        "popularity": None, "last3f": None,
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
    # タイム
    m = re.search(r"(\d+:\d+\.\d+)[良稍重不]", text)
    if m:
        result["time"] = m.group(1)
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
    return result

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
#
# 新レースを追加する場合はここに1行追加するだけ
# ============================================================
RACE_SCHEDULE = {
    # 2026年
    "フェブラリーS":      ("東京",  "11", "2026/2/15"),
    "高松宮記念":         ("中京",  "11", "2026/3/29"),
    "大阪杯":             ("阪神",  "11", "2026/4/5"),
    "桜花賞":             ("阪神",  "11", "2026/4/12"),
    "皐月賞":             ("中山",  "11", "2026/4/19"),
    "天皇賞春":           ("京都",  "11", "2026/5/3"),
    "NHKマイルC":         ("東京",  "11", "2026/5/10"),
    "ヴィクトリアM":      ("東京",  "11", "2026/5/17"),
    "優駿牝馬":           ("東京",  "11", "2026/5/24"),
    "ダービー":           ("東京",  "11", "2026/5/31"),
    "目黒記念":           ("東京",  "12", "2026/5/31"),
    "安田記念":           ("東京",  "11", "2026/6/7"),
    "宝塚記念":           ("阪神",  "11", "2026/6/14"),
    "府中牝馬S":          ("東京",  "11", "2026/6/21"),
    "しらさぎS":          ("阪神",  "11", "2026/6/21"),
    "函館記念":           ("函館",  "11", "2026/6/28"),
    "北九州記念":         ("小倉",  "11", "2026/7/5"),
    "七夕賞":             ("福島",  "11", "2026/7/12"),
    "小倉記念":           ("小倉",  "11", "2026/7/19"),
    "関屋記念":           ("新潟",  "07", "2026/7/26"),
    "クイーンS":          ("札幌",  "11", "2026/8/2"),
    "CBC賞":              ("中京",  "07", "2026/8/9"),
    "中京記念":           ("中京",  "07", "2026/8/16"),
    "札幌記念":           ("札幌",  "11", "2026/8/23"),
    "キーンランドC":      ("札幌",  "11", "2026/8/30"),
    "新潟2歳S":           ("新潟",  "11", "2026/8/30"),
    "セントウルS":        ("阪神",  "11", "2026/9/13"),
    "オールカマー":       ("中山",  "11", "2026/9/27"),
    "神戸新聞杯":         ("阪神",  "11", "2026/9/27"),
    "スプリンターズS":    ("中山",  "11", "2026/10/4"),
    "毎日王冠":           ("東京",  "11", "2026/10/11"),
    "秋華賞":             ("京都",  "11", "2026/10/18"),
    "菊花賞":             ("京都",  "11", "2026/10/25"),
    "天皇賞秋":           ("東京",  "11", "2026/11/1"),
    "アルゼンチン共和国杯": ("東京","11", "2026/11/8"),
    "エリザベス女王杯":   ("京都",  "11", "2026/11/15"),
    "マイルCS":           ("京都",  "11", "2026/11/22"),
    "ジャパンC":          ("東京",  "11", "2026/11/29"),
    "チャンピオンズC":    ("中京",  "11", "2026/12/6"),
    "阪神JF":             ("阪神",  "11", "2026/12/13"),
    "朝日杯FS":           ("阪神",  "11", "2026/12/20"),
    "有馬記念":           ("中山",  "11", "2026/12/27"),
}

# ============================================================
# keibanomiryoku.com 調教URL辞書
# ============================================================
WORK_SLUG_MAP = {
    "有馬記念":           "arima-kinen",
    "ジャパンC":          "japan-cup",
    "ジャパンカップ":     "japan-cup",
    "天皇賞秋":           "tenno-sho-autumn",
    "天皇賞（秋）":       "tenno-sho-autumn",
    "秋華賞":             "shuka-sho",
    "菊花賞":             "kikka-sho",
    "スプリンターズS":    "sprinters-stakes",
    "宝塚記念":           "takarazuka-kinen",
    "安田記念":           "yasuda-kinen",
    "オークス":           "oaks",
    "優駿牝馬":           "oaks",
    "ダービー":           "derby",
    "東京優駿":           "derby",
    "NHKマイルC":         "nhk-mile-cup",
    "天皇賞春":           "tenno-sho-spring",
    "天皇賞（春）":       "tenno-sho-spring",
    "皐月賞":             "satsuki-sho",
    "桜花賞":             "oka-sho",
    "フェブラリーS":      "february-stakes",
    "ヴィクトリアM":      "victoria-mile",
    "ヴィクトリアマイル": "victoria-mile",
    "高松宮記念":         "takamatsu-no-miya-kinen",
    "大阪杯":             "osaka-hai",
    "目黒記念":           "meguro-kinen",
    "府中牝馬S":          "fuchu-himba-stakes",
    "しらさぎS":          "shirasagi-stakes",
    "函館記念":           "hakodate-kinen",
    "北九州記念":         "kitakyushu-kinen",
    "札幌記念":           "sapporo-kinen",
    "関屋記念":           "sekiya-kinen",
    "新潟記念":           "niigata-kinen",
    "中山記念":           "nakayama-kinen",
    "阪神大賞典":         "hanshin-daishoten",
    "金鯱賞":             "kinko-sho",
    "マイラーズC":        "milers-cup",
    "京王杯SC":           "keio-hai-spring-cup",
    "エプソムC":          "epsom-cup",
    "マーメイドS":        "mermaid-stakes",
    "オールカマー":       "all-comers",
    "神戸新聞杯":         "kobe-shimbun-hai",
    "毎日王冠":           "mainichi-osho",
    "富士S":              "fuji-stakes",
    "スワンS":            "swan-stakes",
    "アルゼンチン共和国杯": "argentina-kyowakoku-hai",
    "エリザベス女王杯":   "queen-elizabeth-2-cup",
    "マイルCS":           "mile-championship",
    "七夕賞":             "tanabata-sho",
    "小倉記念":           "kokura-kinen",
    "クイーンS":          "queen-stakes",
    "CBC賞":              "cbc-sho",
    "中京記念":           "chukyo-kinen",
    "プロキオンS":        "procyon-stakes",
    "アイビスSD":         "ibis-summer-dash",
    "小倉2歳S":           "kokura-nisai-stakes",
    "キーンランドC":      "keenland-cup",
    "新潟2歳S":           "niigata-nisai-stakes",
    "セントウルS":        "centaur-stakes",
    "スプリンターズS":    "sprinters-stakes",
}

# ============================================================
# 日付ユーティリティ
# ============================================================
def next_sunday(d: datetime) -> datetime:
    """月〜土なら次の日曜、日曜ならそのまま"""
    wd = d.weekday()  # 月=0 ... 日=6
    return d if wd == 6 else d + timedelta(days=6 - wd)

def get_race_date(race_name: str) -> datetime:
    """
    RACE_SCHEDULE から開催日を取得する。
    未登録の場合は next_sunday() にフォールバック。
    """
    if race_name in RACE_SCHEDULE:
        _, _, date_str = RACE_SCHEDULE[race_name]
        return datetime.strptime(date_str, "%Y/%m/%d")
    return next_sunday(datetime.today())

# RACE_DATE は main() 内で get_race_date(race_name) を使って設定する
# モジュールレベルではフォールバック値を設定
RACE_DATE = next_sunday(datetime.today())


def build_race_params(race_name: str) -> tuple:
    """
    レース名から (race_id, date_str, no, id_) を返す。
    RACE_SCHEDULE に未登録なら手動入力を促して終了する。

    race_id 形式: YYYYMMDDRRCC
      YYYY = 年, MM = 月, DD = 日
      RR   = レース番号(01〜12)
      CC   = 開催場ID(kichiuma形式)
    """
    if race_name not in RACE_SCHEDULE:
        print(f"[ERROR] '{race_name}' が RACE_SCHEDULE に未登録です。")
        print("  JRA_read_next.py の RACE_SCHEDULE に追加してください:")
        print(f'  "{race_name}": ("開催場", "RR", "YYYY/M/D"),')
        raise SystemExit(1)

    venue, race_no, date_str = RACE_SCHEDULE[race_name]
    vid = VENUE_ID.get(venue)
    if not vid:
        raise ValueError(f"開催場 '{venue}' のIDが VENUE_ID に未登録です")

    d       = datetime.strptime(date_str, "%Y/%m/%d")
    race_id = f"{d.year}{d.month:02d}{d.day:02d}{race_no}{vid}"
    no      = str(int(race_no))   # "07" → "7"
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
        })
        print(f"  [{num}] {name}  前走={repr(prev1[:40])}")

    print(f"[kichiuma] {len(horses)}頭 取得完了")
    return horses


# ============================================================
# keibanomiryoku.com 調教URL辞書
# ============================================================
WORK_SLUG_MAP = {
    "有馬記念":           "arima-kinen",
    "ジャパンC":          "japan-cup",
    "ジャパンカップ":     "japan-cup",
    "天皇賞秋":           "tenno-sho-autumn",
    "天皇賞（秋）":       "tenno-sho-autumn",
    "秋華賞":             "shuka-sho",
    "菊花賞":             "kikka-sho",
    "スプリンターズS":    "sprinters-stakes",
    "宝塚記念":           "takarazuka-kinen",
    "安田記念":           "yasuda-kinen",
    "オークス":           "oaks",
    "優駿牝馬":           "oaks",
    "ダービー":           "derby",
    "東京優駿":           "derby",
    "NHKマイルC":         "nhk-mile-cup",
    "天皇賞春":           "tenno-sho-spring",
    "天皇賞（春）":       "tenno-sho-spring",
    "皐月賞":             "satsuki-sho",
    "桜花賞":             "oka-sho",
    "フェブラリーS":      "february-stakes",
    "ヴィクトリアM":      "victoria-mile",
    "ヴィクトリアマイル": "victoria-mile",
    "高松宮記念":         "takamatsu-no-miya-kinen",
    "大阪杯":             "osaka-hai",
    "目黒記念":           "meguro-kinen",
    "府中牝馬S":          "fuchu-himba-stakes",
    "しらさぎS":          "shirasagi-stakes",
    "函館記念":           "hakodate-kinen",
    "北九州記念":         "kitakyushu-kinen",
    "札幌記念":           "sapporo-kinen",
    "関屋記念":           "sekiya-kinen",
    "新潟記念":           "niigata-kinen",
    "中山記念":           "nakayama-kinen",
    "阪神大賞典":         "hanshin-daishoten",
    "金鯱賞":             "kinko-sho",
    "マイラーズC":        "milers-cup",
    "京王杯SC":           "keio-hai-spring-cup",
    "エプソムC":          "epsom-cup",
    "マーメイドS":        "mermaid-stakes",
    "オールカマー":       "all-comers",
    "神戸新聞杯":         "kobe-shimbun-hai",
    "毎日王冠":           "mainichi-osho",
    "富士S":              "fuji-stakes",
    "スワンS":            "swan-stakes",
    "アルゼンチン共和国杯": "argentina-kyowakoku-hai",
    "エリザベス女王杯":   "queen-elizabeth-2-cup",
    "マイルCS":           "mile-championship",
    "七夕賞":             "tanabata-sho",
    "小倉記念":           "kokura-kinen",
    "クイーンS":          "queen-stakes",
    "CBC賞":              "cbc-sho",
    "中京記念":           "chukyo-kinen",
    "プロキオンS":        "procyon-stakes",
    "アイビスSD":         "ibis-summer-dash",
    "小倉2歳S":           "kokura-nisai-stakes",
    "キーンランドC":      "keenland-cup",
    "新潟2歳S":           "niigata-nisai-stakes",
    "セントウルS":        "centaur-stakes",
    "スプリンターズS":    "sprinters-stakes",
}

# ============================================================
# 日付ユーティリティ
# ============================================================
def get_work_data(race_name: str, year: int) -> dict:
    """
    keibanomiryoku.com から調教データを取得する。
    元の JRA_read.py の get_workout_data() ロジックをそのまま流用。
    h3タグ（馬名）→ 「最終追い切り」ブロック → 調教場所・時計・内容 を抽出。
    戻り値: {馬名: {"調教場所・馬場": ..., "時計": ..., "内容": ..., "調1F": ...}}
    """
    slug = WORK_SLUG_MAP.get(race_name)
    if not slug:
        print(f"[WORK] '{race_name}' が辞書に未登録です。スキップします。")
        return {}

    url = f"https://www.keibanomiryoku.com/article/{slug}-{year}-work-out.html"
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
        node  = h3.next_sibling
        place = ""
        clock = ""
        content = ""

        while node:
            node = getattr(node, "next_sibling", None)
            if not node:
                break
            if getattr(node, "name", None) == "h3":
                break

            txt = node.get_text("\n", strip=True) if hasattr(node, "get_text") else ""

            if "最終追い切り" in txt:
                lines = [x.strip() for x in txt.split("\n") if x.strip()]
                if len(lines) >= 3:
                    place = lines[1]
                    clock = lines[2]
                    m = re.search(r"（(.*?)）", clock)
                    if m:
                        content = m.group(1)
                break

        if horse_name:
            # 調1F を時計文字列から抽出
            last1f = _extract_last1f(clock)
            work_data[horse_name] = {
                "調教場所・馬場": place,
                "時計"          : clock,
                "内容"          : content,
                "調1F"          : last1f,
            }

    print(f"[WORK] {len(work_data)}頭分の調教データ取得")
    return work_data


def get_result_comments(race_name: str, year: int) -> dict:
    """
    keibanomiryoku.com のレース結果ページから騎手コメントを取得する。
    URL: {slug}-{year}-results.html  (調教ページと同じ命名規則)
    戻り値: {馬名: コメント文字列}
    """
    slug = WORK_SLUG_MAP.get(race_name)
    if not slug:
        print(f"[RESULT] '{race_name}' が辞書に未登録。スキップ。")
        return {}

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


def generate_mishap_comments(horses: list[dict], result_comments: dict = None, rawdata: dict = None) -> dict[str, str]:
    """
    前走しくじりコメントを生成する。
    ANTHROPIC_API_KEY が設定されていれば Claude API を使用。
    未設定またはエラー時はルールベースにフォールバック。
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    # ---- Claude API ----
    if api_key:
        targets = [h for h in horses if h.get("prev_raw")]
        if targets:
            horse_list_parts = []
            for h in targets:
                name = h['name']
                prev = h.get('prev_raw', '')
                # 前走レース後の騎手コメントがあれば追加
                rc = (result_comments or {}).get(name, '')
                entry = f"・{name}({h['no']}番): {prev}"
                if rc:
                    entry += f"\n  【前走後コメント】{rc}"
                # 休養情報をプロンプトに含める
                absence = rawdata.get(name, {}).get("休養情報", "")
                if absence:
                    entry += f"\n  【休養情報】{absence}"
                horse_list_parts.append(entry)
            horse_list = "\n".join(horse_list_parts)
            prompt = (
                "以下は競馬の各馬の前走情報です。\n"
                "各馬について、前走で「しくじり」があれば15文字以内で簡潔にコメントしてください。\n"
                "しくじりとは: 出遅れ、入れ込み、直線で進路が狭くなる、大外を回した、"
                "不利を受けた、馬場が合わなかった、距離が長かった/短かった など。\n"
                "しくじりがない場合は空文字を返してください。\n\n"
                "必ずJSON形式で返してください。例:\n"
                '{"馬名A": "出遅れ響いた", "馬名B": "", "馬名C": "直線進路なし"}\n\n'
                f"馬のリスト:\n{horse_list}"
            )
            try:
                client = anthropic.Anthropic(api_key=api_key)
                msg = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw    = msg.content[0].text.strip()
                json_m = re.search(r"\{.*\}", raw, re.DOTALL)
                if json_m:
                    comments = json.loads(json_m.group(0))
                    print(f"[COMMENT] Claude API: {len(comments)}頭分 生成完了")
                    return comments
            except Exception as e:
                print(f"[COMMENT] Claude APIエラー: {e}")
                print("[COMMENT] ルールベースにフォールバック")

    # ---- ルールベース（フォールバック） ----
    print("[COMMENT] ルールベースでコメント生成")
    return {
        h["name"]: rule_based_mishap(h.get("prev_raw", ""))
        for h in horses
    }


# ============================================================
# JSON組み立て
# ============================================================
def build_json(race_name: str, horses: list[dict],
               work: dict, comments: dict,
               rawdata: dict) -> dict:
    """
    kichiuma / keibanomiryoku / 各モジュールのデータを統合して
    pyxelビューア用JSONを生成する

    rawdata: {馬名: {前走, 前々走, 3走前, ...}} kichiuma から取得した生データ
    """
    venue, race_no, date_str = RACE_SCHEDULE[race_name]

    # ---- Step1: 全馬の基本行を作る ----
    rows = []
    for h in horses:
        name = h["name"]
        w    = work.get(name, {})
        raw  = rawdata.get(name, {})
        no   = int(h["no"]) if h["no"].isdigit() else 0

        # 脚質判定（rawdata の前走テキストから）
        style = get_running_style(raw)

        # レース指数（前走・前々走・3走前それぞれ）
        r1 = single_race_rating(raw.get("前走",   ""))
        r2 = single_race_rating(raw.get("前々走",  ""))
        r3 = single_race_rating(raw.get("3走前",   ""))

        # 平均指数
        avg_scores = [s for s in [r1, r2, r3] if s > 0]
        avg_rating = round(sum(avg_scores)/len(avg_scores)) if avg_scores else 0

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
            # --- pyxel ビューア用フィールド ---
            "馬番"      : no,
            "馬名"      : name,
            "オッズ戦績": h.get("odds_record", ""),
            "性齢"      : h["sex_age"],
            "斤量"      : h["weight"] + "kg" if h["weight"] else "",
            "騎手"      : h["jockey"],
            "脚質"      : style,
            "総合指数"  : avg_rating,
            "前走"      : r1 if r1 > 0 else None,
            "前々"      : r2 if r2 > 0 else None,
            "3走"       : r3 if r3 > 0 else None,
            "前3F"      : prev_3f,
            "調1F"      : last1f,
            "印"        : "",
            # --- 追加フィールド ---
            "前走指数"  : r1,
            "前々走指数": r2,
            "3走前指数" : r3,
            "能力指数"  : avg_rating,
            "追切評価"  : w_rank,
            "追切スコア": w_score,
            "前走コメント": comments.get(name, ""),
        })

    # ---- Step2: 展開予想（全馬の脚質が揃ってから） ----
    # reporting.predict_pace は DataFrame + pace_module 形式だが
    # ここでは脚質カウントで簡易判定する
    from collections import Counter
    style_counts = Counter(r["脚質"] for r in rows)
    lead = style_counts.get("逃", 0)
    late = style_counts.get("差", 0) + style_counts.get("追", 0)
    if   lead >= 3:              pace = "Hペース"
    elif lead == 2:              pace = "Mペース"
    elif lead <= 1 and late >= 8: pace = "Sペース"
    else:                        pace = "Mペース"

    # ---- Step3: 激走指数・コメント ----
    for r in rows:
        r["展開予想"]    = pace
        r["激走指数"]    = calc_gekisou_index(r)
        r["新聞コメント"] = make_comment(r)

    # ---- Step4: しくじり補正 + 斤量補正 → 補正後総合指数 ----
    max_w = get_max_weight(rows)
    for r in rows:
        mishap_comment = r.get("前走コメント", "")
        weight_str     = r.get("斤量", "")
        base           = r.get("総合指数", 0)

        mishap_bonus  = calc_mishap_bonus(mishap_comment)
        weight_bonus  = calc_weight_bonus(weight_str, max_w)
        adjusted      = calc_adjusted_index(base, mishap_comment, weight_str, max_w)

        r["しくじり補正"] = mishap_bonus
        r["斤量補正"]     = weight_bonus
        r["adjusted_index"] = adjusted

        if mishap_bonus > 0 or weight_bonus > 0:
            print(f"  [補正] {r['馬名']}: 基礎{base} + しくじり{mishap_bonus} + 斤量{weight_bonus} = {adjusted}")

    # ---- Step5: 補正後指数で印を付ける ----
    assign_marks(rows)

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
        "総合指数": r["総合指数"],
        "前走"    : r["前走"],
        "前々"    : r["前々"],
        "3走"     : r["3走"],
        "前3F"    : r["前3F"],
        "調1F"    : r["調1F"],
        "印"      : r["印"],
    } for r in rows]

    summary_rows = [{
        "馬名"        : r["馬名"],
        "能力指数"    : r["能力指数"],
        "補正後指数"  : r.get("adjusted_index", r["能力指数"]),
        "しくじり補正": r.get("しくじり補正", 0),
        "斤量補正"    : r.get("斤量補正", 0),
        "追切評価"    : r["追切評価"],
        "激走指数"    : r["激走指数"],
        "新聞コメント": r["新聞コメント"],
        "前走コメント": r["前走コメント"],
        "備考"        : f"予想ペース：{pace}",
    } for r in rows]

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
def main(race_name: str = None):
    """
    race_name: 処理するレース名。
               Noneの場合はモジュール変数 TARGET_RACE を使用。
               run_schedule.py から呼ぶ場合は直接渡す。
    """
    if race_name is None:
        race_name = TARGET_RACE

    print(f"=== {race_name} データ生成開始 ===")

    # 1. race_id 自動生成
    race_id, date_str, no, id_ = build_race_params(race_name)

    # RACE_DATE をレーススケジュールの実際の日付に設定
    global RACE_DATE
    RACE_DATE = get_race_date(race_name)
    print(f"[DATE] 開催日: {RACE_DATE.strftime('%Y/%m/%d')} (ファイル名: {RACE_DATE.strftime('%y%m%d')})")
    print(f"[RACE] race_id={race_id}  date={date_str}  no={no}  id={id_}")

    # 2. kichiuma.net から出馬表取得
    horses = get_entry_table(race_id, date_str, no, id_)
    if not horses:
        print("[ERROR] 出馬表が取得できませんでした")
        return

    # 3. keibanomiryoku.com から調教データ取得
    work = get_work_data(race_name, RACE_DATE.year)

    # 4. 前走レース後コメントを取得（keibanomiryoku.com results ページ）
    # 前走のレース名を各馬から抽出して取得
    prev_race_comments = {}
    prev_race_names = set()
    # 前走テキストから (レース名, 年) のセットを収集
    # キー: (レース名, 年)  値: 対象馬名リスト（デバッグ用）
    prev_race_year_map = {}   # {(rname, year): [馬名, ...]}

    for h in horses:
        name     = h["name"]
        prev_text = h.get("prev1", "")
        if not prev_text:
            continue

        # 前走の年を日付から正確に抽出: "26.06.21" → 2026
        m_yr = re.search(r"(\d{2})\.(\d{2})\.(\d{2})", prev_text)
        if not m_yr:
            continue
        prev_year = 2000 + int(m_yr.group(1))

        # レース名をWORK_SLUG_MAPと照合（最長一致優先）
        matched = ""
        for rname in WORK_SLUG_MAP.keys():
            if rname in prev_text and len(rname) > len(matched):
                matched = rname

        if matched:
            key = (matched, prev_year)
            prev_race_year_map.setdefault(key, []).append(name)

    print(f"[RESULT] 前走レース: {list(prev_race_year_map.keys())}")

    # 各(レース名, 年)の組み合わせでresultsページを取得
    for (prev_rname, prev_year), target_horses in prev_race_year_map.items():
        print(f"[RESULT] {prev_rname} {prev_year}年 → 対象馬: {target_horses}")
        result = get_result_comments(prev_rname, prev_year)
        if not result:
            print(f"[RESULT] {prev_year}年が取得できず、{prev_year-1}年を試します")
            result = get_result_comments(prev_rname, prev_year - 1)
        if result:
            # 対象馬のコメントのみ採用（他レースの馬と混在防止）
            for horse_name in target_horses:
                if horse_name in result:
                    prev_race_comments[horse_name] = result[horse_name]
                    print(f"  ✓ {horse_name}: {result[horse_name][:40]}...")
                else:
                    print(f"  - {horse_name}: コメントなし")

    print(f"[RESULT] 前走コメント取得: {len(prev_race_comments)}頭分")

    # 4b. rawdata（前走生テキスト）を馬名辞書に変換
    rawdata = {}
    for h in horses:
        name = h["name"]
        w    = work.get(name, {})
        prev1 = h.get("prev1", "")
        prev2 = h.get("prev2", "")
        prev3 = h.get("prev3", "")
        print(f"[RAW] {name}: 前走={repr(prev1[:50]) if prev1 else '(空)'}")
        kyuyo = h.get("kyuyo", "")
        absence = detect_long_absence(kyuyo, prev1)
        if absence:
            print(f"  [休養] {name}: {absence}")
        rawdata[name] = {
            "馬名"        : name,
            "前走"        : prev1,
            "前々走"      : prev2,
            "3走前"       : prev3,
            "調教場所・馬場": w.get("調教場所・馬場", ""),
            "時計"        : w.get("時計", ""),
            "内容"        : w.get("内容", ""),
            "休養情報"    : absence,
        }
    print(f"[RAW] rawdata {len(rawdata)}頭分 組み立て完了")

    # 5. Claude API で前走しくじりコメント生成（結果コメントも渡す）
    comments = generate_mishap_comments(horses, prev_race_comments, rawdata)

    # 6. JSON組み立て
    data = build_json(race_name, horses, work, comments, rawdata)

    # 7. ファイル保存
    venue, race_no, date_str2 = RACE_SCHEDULE[race_name]
    d         = datetime.strptime(date_str2, "%Y/%m/%d")
    course    = data.get("course", venue)
    dist      = data.get("distance", "")
    date_tag  = RACE_DATE.strftime("%y%m%d")
    filename  = f"{date_tag}_{course}{dist}_{race_name}.json"

    data_dir  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DATA")
    os.makedirs(data_dir, exist_ok=True)
    out_path  = os.path.join(data_dir, filename)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[SAVE] {out_path}")

    # 8. index.json 更新
    update_index_json(data_dir, filename)

    print(f"=== 完了: {filename} ===")


if __name__ == "__main__":
    main()
