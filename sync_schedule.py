"""
3ハロンVII - schedule.json 自動更新スクリプト（netkeiba 重賞日程より）

netkeiba の重賞日程ページから (開催日・場・レース番号・レース名) を取得し、
schedule.json に未登録のレースだけを新規追加する。

・既存エントリ（race_name + date が一致するもの）は上書きしない
  （active/memo/work_slug を人が編集済みの可能性があるため）
・新規追加分は work_slug が分からないため空欄("")で追加する。
  → 追加された行は memo に "要work_slug設定" と入るので、
    調教データ取得(workout.py)に使う slug を手動で埋めてください。

⚠️ 注意:
  このスクリプトは netkeiba のページ構造の詳細な検証ができていない状態で
  作成している(fetch_result.pyと同様、実際のサイト構造にはある程度の
  柔軟性を持たせているが確実ではない)。初回実行時にログを確認し、
  想定通りに取得できているか確認してほしい。取得できなかった場合は
  KEIBA_DEBUG=1 を付けて実行すると生HTMLの断片を出力する。

実行方法:
    pip install requests beautifulsoup4
    python3 scripts/sync_schedule.py
"""
import json
import os
import re
import sys
import datetime

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[エラー] requests / beautifulsoup4 が必要です: pip install requests beautifulsoup4")
    sys.exit(1)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_PATH = os.path.join(BASE, "schedule.json")
SCHEDULE_URL = "https://race.netkeiba.com/top/schedule.html?rf=race_list"

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_DEBUG = os.environ.get("KEIBA_DEBUG") == "1"

_RACE_SUFFIX_WORDS = ["ステークス", "スペシャル", "特別", "記念", "賞典", "杯", "賞", "S"]


def _race_core(name):
    n = name
    if " " in n or "　" in n:
        n = re.split(r"[ 　]+", n)[-1]
    for suf in _RACE_SUFFIX_WORDS:
        if n.endswith(suf) and len(n) > len(suf):
            n = n[: -len(suf)]
            break
    return n.strip()


def _http_get(url, timeout=10):
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    raw = r.content
    for enc in ("euc-jp", "cp932", "utf-8", r.apparent_encoding or "utf-8"):
        try:
            text = raw.decode(enc)
        except Exception:
            continue
        if ("レース" in text) or ("開催" in text):
            return text
    return raw.decode(r.apparent_encoding or "utf-8", errors="replace")


def fetch_grade_schedule():
    """
    netkeibaの重賞日程ページから重賞レースの一覧を取得する。
    戻り値: [{"date": "2026/9/6", "venue": "阪神", "race_no": "11", "race_name": "セントウルS"}, ...]

    ページ構造の想定(要検証):
      日付・場・レース名らしきテキストを含むリンク/行を広めに拾い、
      正規表現で "M月D日" や "M/D" 形式の日付とレース名を抽出する。
    """
    html = _http_get(SCHEDULE_URL)
    soup = BeautifulSoup(html, "html.parser")
    if _DEBUG:
        print(f"[DEBUG] ページ取得: {len(html)} 文字")

    races = []
    year = datetime.date.today().year

    # 候補1: よくあるクラス名で行要素を探す
    rows = soup.select(".RaceList_DataItem, .Schedule_RaceList li, table tr")
    if _DEBUG:
        print(f"[DEBUG] 候補行数: {len(rows)}")

    date_re = re.compile(r"(\d{1,2})月(\d{1,2})日|(\d{1,2})/(\d{1,2})")

    for row in rows:
        text = row.get_text(" ", strip=True)
        if not text:
            continue
        m = date_re.search(text)
        if not m:
            continue
        if m.group(1):
            month, day = int(m.group(1)), int(m.group(2))
        else:
            month, day = int(m.group(3)), int(m.group(4))

        # レース名っぽい部分（カタカナ/漢字が続く塊）を大まかに抽出
        name_m = re.findall(r"[一-龠ぁ-んァ-ヴーA-Za-z0-9]{3,}(?:S|ステークス|記念|賞|杯|カップ|C)", text)
        if not name_m:
            continue
        race_name = name_m[-1]

        venue_m = re.search(r"(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)", text)
        venue = venue_m.group(1) if venue_m else ""

        raceno_m = re.search(r"(\d{1,2})\s*R", text)
        race_no = raceno_m.group(1).zfill(2) if raceno_m else ""

        races.append({
            "date": f"{year}/{month}/{day}",
            "venue": venue,
            "race_no": race_no,
            "race_name": race_name,
        })

    # 重複除去（同じ date+race_name）
    seen = set()
    uniq = []
    for r in races:
        key = (r["date"], r["race_name"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    if _DEBUG:
        print(f"[DEBUG] 抽出できたレース数: {len(uniq)}")
    return uniq


def main():
    if not os.path.exists(SCHEDULE_PATH):
        print(f"[警告] {SCHEDULE_PATH} が見つかりません。")
        return
    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        schedule = json.load(f)

    existing_keys = {(_race_core(r["race_name"]), r["date"]) for r in schedule.get("races", [])}

    try:
        scraped = fetch_grade_schedule()
    except Exception as e:
        print(f"[警告] netkeibaからの日程取得に失敗しました: {e}")
        return

    added = []
    for r in scraped:
        key = (_race_core(r["race_name"]), r["date"])
        if key in existing_keys:
            continue  # 既に登録済み
        if not r["venue"] or not r["race_name"]:
            continue  # 情報不足はスキップ(誤検出対策)
        schedule.setdefault("races", []).append({
            "race_name": r["race_name"],
            "date": r["date"],
            "venue": r["venue"],
            "race_no": r["race_no"] or "11",
            "work_slug": "",
            "active": False,
            "memo": "要work_slug設定",
        })
        existing_keys.add(key)
        added.append(r["race_name"])

    if added:
        with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)
        print("新規追加: " + ", ".join(added))
        print("→ 追加されたレースは work_slug が空欄です。手動で設定してください。")
    else:
        print("新規に追加するレースはありませんでした（取得0件、または既に登録済み）。")


if __name__ == "__main__":
    main()
