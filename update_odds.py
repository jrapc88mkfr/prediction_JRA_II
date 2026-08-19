"""
update_odds.py  オッズ更新スクリプト

kichiuma.net から最新オッズを取得して既存 JSON を更新する。
Claude API は使用しないため無料で実行可能。

実行タイミング（weekly_odds.yml から呼ばれる）:
  土曜 8:00 / 12:00 / 17:00
  日曜 8:00 / 12:00 / 15:00
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ============================================================
# 設定
# ============================================================
DATA_DIR = Path(__file__).parent / "DATA"
HEADERS  = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ============================================================
# kichiuma からオッズ取得
# ============================================================
def fetch_odds(race_id: str, date: str, no: str, id_: str) -> dict:
    """
    kichiuma.net の出馬表ページから最新オッズを取得する。
    戻り値: {馬名: "12.3 (3.1.2.5)"} 形式の辞書
    """
    url = (f"https://kichiuma.net/php/search.php"
           f"?race_id={race_id}&date={date}&no={no}&id={id_}&p=rf")
    print(f"[ODDS] {url}")

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = r.apparent_encoding
    except Exception as e:
        print(f"[ODDS ERROR] {e}")
        return {}

    soup      = BeautifulSoup(r.text, "html.parser")
    race_form = soup.find("div", id="race_form")
    if not race_form:
        print("[ODDS] race_form が見つかりません")
        return {}

    table = race_form.find("table")
    rows  = table.find_all("tr")
    odds_dict = {}

    for row in rows:
        num_td   = row.find("td", class_=re.compile(r"W\d+"))
        horse_td = row.find("td", class_="horse_box")
        kisyu_td = row.find("td", class_="kisyu_box")
        if not num_td or not horse_td:
            continue

        # 馬名
        name_tag = horse_td.find("span", class_="RHName")
        name     = name_tag.get_text(strip=True) if name_tag else ""
        if not name:
            continue

        # テキストからオッズ取得
        text  = horse_td.get_text(separator=" ").replace("\u3000", " ")
        m     = re.search(r"\d{2}\.\dkg\s+([\d.]+)", text)
        odds  = m.group(1) if m else ""

        # 戦績（kisyu_box）
        kisyu_text = kisyu_td.get_text(separator="\n", strip=True) if kisyu_td else ""
        total = [0, 0, 0, 0]
        for line in kisyu_text.split("\n"):
            m2 = re.match(r"(\d+)-(\d+)-(\d+)-(\d+)", line.strip())
            if m2:
                for i in range(4):
                    total[i] += int(m2.group(i + 1))
        record = f"{total[0]}.{total[1]}.{total[2]}.{total[3]}" if sum(total) > 0 else ""

        odds_record = f"{odds} ({record})" if odds and record else odds
        odds_dict[name] = odds_record
        print(f"  {name}: {odds_record}")

    print(f"[ODDS] {len(odds_dict)}頭分のオッズ取得完了")
    return odds_dict


# ============================================================
# JSON 更新
# ============================================================
def update_json_odds(json_path: Path, odds_dict: dict) -> bool:
    """
    既存の JSON ファイルのオッズ戦績を更新する。
    戻り値: 更新があった場合 True
    """
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    updated = False
    for row in data.get("pyxel", []):
        name = row.get("馬名", "")
        if name in odds_dict:
            new_odds = odds_dict[name]
            if row.get("オッズ戦績", "") != new_odds:
                row["オッズ戦績"] = new_odds
                updated = True

    # summary も更新
    for row in data.get("summary", []):
        name = row.get("馬名", "")
        if name in odds_dict:
            row["オッズ戦績"] = odds_dict.get(name, "")

    if updated:
        # 更新日時を記録
        data["odds_updated"] = datetime.now().strftime("%Y/%m/%d %H:%M")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[ODDS] {json_path.name} を更新しました")
    else:
        print(f"[ODDS] {json_path.name} 変更なし")

    return updated


# ============================================================
# 処理対象 JSON を特定
# ============================================================
def find_target_jsons() -> list[Path]:
    """
    DATA/ フォルダから今週・来週のレース JSON を返す。
    index.json に登録されているファイルを対象とする。
    """
    index_path = DATA_DIR / "index.json"
    if not index_path.exists():
        print("[ODDS] index.json が見つかりません")
        return []

    with open(index_path, encoding="utf-8") as f:
        files = json.load(f)

    today    = datetime.today()
    targets  = []
    for fname in files:
        json_path = DATA_DIR / fname
        if not json_path.exists():
            continue
        # ファイル名の先頭 6 文字が日付 (YYMMDD)
        try:
            file_date = datetime.strptime(fname[:6], "%y%m%d")
            # 今日から ±7日以内のファイルを対象
            diff = abs((file_date - today).days)
            if diff <= 7:
                targets.append(json_path)
                print(f"[ODDS] 対象: {fname} (開催日との差: {diff}日)")
        except ValueError:
            continue

    return targets


# ============================================================
# race_id を JSON から取得
# ============================================================
def get_race_params_from_json(json_path: Path) -> tuple:
    """
    JSON ファイルから race_id 関連パラメータを取得する。
    戻り値: (race_id, date_str, no, id_) or (None, None, None, None)
    """
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    race_name = data.get("race_name", "")
    date_str  = data.get("date", "")

    if not date_str:
        print(f"[ODDS] {json_path.name} に date フィールドがありません")
        return None, None, None, None

    # RACE_SCHEDULE から race_id を再構築
    # JRA_read_next.py の定数を再利用
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from JRA_read_next import RACE_SCHEDULE, VENUE_ID, build_race_params
        if race_name in RACE_SCHEDULE:
            race_id, date_str, no, id_ = build_race_params(race_name)
            return race_id, date_str, no, id_
    except Exception as e:
        print(f"[ODDS] build_race_params エラー: {e}")

    return None, None, None, None


# ============================================================
# メイン
# ============================================================
def main():
    print(f"=== オッズ更新開始 {datetime.now().strftime('%Y/%m/%d %H:%M')} ===\n")

    targets = find_target_jsons()
    if not targets:
        print("更新対象の JSON がありません")
        return

    total_updated = 0
    for json_path in targets:
        print(f"\n--- {json_path.name} ---")
        race_id, date_str, no, id_ = get_race_params_from_json(json_path)
        if not race_id:
            print("  race_id 取得失敗。スキップします")
            continue

        odds_dict = fetch_odds(race_id, date_str, no, id_)
        if odds_dict:
            if update_json_odds(json_path, odds_dict):
                total_updated += 1

    print(f"\n=== オッズ更新完了: {total_updated}ファイル更新 ===")


if __name__ == "__main__":
    main()
