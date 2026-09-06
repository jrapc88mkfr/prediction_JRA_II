"""
3ハロンVII - レース結果 自動取得スクリプト

DATA/races/*.json を確認し、
  ・DATA/results/{stem}_result.json がまだ無い
  ・レース日が今日以前（＝もう開催済みのはず）
なものだけ netkeiba から結果・払戻(1〜3着 / 馬連 / 3連複)を取得して
DATA/results/{stem}_result.json を新規作成する。

・馬番はnetkeiba側の列構成に依存せず、取得した馬名を
  DATA/races/*.json 内の馬名と突き合わせて確定させる(安定重視)。
・まだ発走前 or ページが見つからない場合は静かにスキップし、
  次回の定期実行(毎週月曜12:00 JST / push時)で再トライする。

実行方法:
    pip install requests beautifulsoup4
    python3 scripts/fetch_result.py
"""
import json
import os
import re
import sys
import time
import datetime

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[エラー] requests / beautifulsoup4 が必要です: pip install requests beautifulsoup4")
    sys.exit(1)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACES_DIR = os.path.join(BASE, "DATA", "races")
RESULTS_DIR = os.path.join(BASE, "DATA", "results")

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_DEBUG = os.environ.get("KEIBA_DEBUG") == "1"
REQUEST_INTERVAL_SEC = 2  # netkeibaへの負荷配慮


def _http_get(session, url, timeout=10):
    r = session.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    raw = r.content
    tried = []
    for enc in ("euc-jp", "cp932", "utf-8", r.apparent_encoding or "utf-8"):
        if not enc or enc.lower() in tried:
            continue
        tried.append(enc.lower())
        try:
            text = raw.decode(enc)
        except Exception:
            continue
        if ("レース" in text) or ("馬" in text) or ("払戻" in text):
            return text
    return raw.decode(r.apparent_encoding or "utf-8", errors="replace")


def _parse_race_key_from_stem(stem):
    """ 'YYMMDD_場_レース名' -> (date8, track, race_name) """
    parts = stem.split("_")
    if len(parts) < 3:
        return None
    ymd = parts[0]
    if not re.fullmatch(r"\d{6}", ymd):
        return None
    date8 = "20" + ymd
    track = parts[1]
    race_name = parts[2]
    if not track or not race_name:
        return None
    return date8, track, race_name


_RACE_SUFFIX_WORDS = ["ステークス", "スペシャル", "特別", "記念", "賞典", "杯", "賞", "S"]
_RACE_ALIASES = {
    "東京優駿": "日本ダービー", "日本ダービー": "東京優駿",
    "優駿牝馬": "オークス", "オークス": "優駿牝馬",
}


def _race_core(name):
    n = name
    if " " in n or "　" in n:
        n = re.split(r"[ 　]+", n)[-1]
    for suf in _RACE_SUFFIX_WORDS:
        if n.endswith(suf) and len(n) > len(suf):
            n = n[: -len(suf)]
            break
    return n.strip()


def _find_kaisai_id(session, date8, track):
    url = f"https://race.netkeiba.com/top/payback_list.html?kaisai_date={date8}"
    html = _http_get(session, url)
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select('a[href*="kaisai_id="]'):
        href = a.get("href", "")
        m = re.search(r"kaisai_id=(\d+)", href)
        if m and track in a.get_text(strip=True):
            return m.group(1)
    return None


def _find_race_section(soup, race_name):
    core = _race_core(race_name)
    candidates = {race_name, core}
    if core in _RACE_ALIASES:
        candidates.add(_RACE_ALIASES[core])

    for p in soup.find_all("p", class_="AllResultRaceTitle"):
        span = p.find("span", class_="RacePaybackType")
        if not span:
            continue
        title_txt = span.get_text(strip=True)
        name_only = re.sub(r"^\d+R\s*", "", title_txt)
        for cand in candidates:
            if cand == name_only or cand in name_only or name_only in cand:
                container = p.find_parent("div", id=re.compile(r"^tab_PaybackRaceNum_\d+_con$"))
                if container:
                    return container
    return None


def _parse_race_section(container):
    """該当レースの結果コンテナから 1-3着(名前) / 馬連 / 3連複 を取り出す"""
    result = {"top3": [], "umaren": "", "sanrenpuku": ""}

    result_table = container.find("table", class_="TablePaybackResult")
    if result_table:
        for tr in result_table.select("tbody tr"):
            rank_div = tr.select_one("td.Result_Num div.Rank")
            name_div = tr.select_one("td.Horse_Info div.Horse_Name")
            if not rank_div or not name_div:
                continue
            rank = rank_div.get_text(strip=True)
            name = name_div.get_text(strip=True)
            if rank and name:
                result["top3"].append({"rank": rank, "name": name})

    for table in container.find_all("table", class_="Payout_Detail_Table"):
        for tr in table.find_all("tr"):
            th = tr.find("th")
            if not th:
                continue
            label = th.get_text(strip=True)
            if label not in ("馬連", "3連複", "３連複"):
                continue
            combo_items = [li.get_text(strip=True)
                           for li in tr.select("td.Result li")
                           if li.get_text(strip=True)]
            combo = "-".join(combo_items)
            payout_td = tr.find("td", class_="Payout")
            payout = payout_td.get_text(" ", strip=True) if payout_td else ""
            payout = re.sub(r"\s+", " ", payout).strip()
            text = f"{combo}　{payout}".strip()
            if label == "馬連":
                result["umaren"] = text
            else:
                result["sanrenpuku"] = text

    if not result["top3"]:
        return None
    return result


def fetch_race_result(stem):
    key = _parse_race_key_from_stem(stem)
    if not key:
        if _DEBUG: print(f"[DEBUG] ファイル名からレースキーを解析できません: {stem!r}")
        return None
    date8, track, race_name = key

    session = requests.Session()
    try:
        kaisai_id = _find_kaisai_id(session, date8, track)
        if not kaisai_id:
            if _DEBUG: print(f"[DEBUG] kaisai_id not found: {track} {date8}")
            return None
        time.sleep(REQUEST_INTERVAL_SEC)
        day_url = (f"https://race.netkeiba.com/top/payback_list.html"
                   f"?kaisai_id={kaisai_id}&kaisai_date={date8}")
        html = _http_get(session, day_url)
        soup = BeautifulSoup(html, "html.parser")
        container = _find_race_section(soup, race_name)
        if not container:
            if _DEBUG: print(f"[DEBUG] race section not matched: {race_name}")
            return None
        return _parse_race_section(container)
    except Exception as e:
        print(f"[警告] {stem}: 結果取得に失敗しました ({e})")
        return None


def resolve_horse_numbers(top3_names, race):
    """netkeibaで取れた馬名から、DATA/races側の馬番を突き合わせる"""
    name_to_no = {h["馬名"]: h["馬番"] for h in race.get("pyxel", [])}
    resolved = []
    for entry in top3_names:
        name = entry["name"]
        no = name_to_no.get(name)
        if no is None:
            # 全角/半角スペースや表記ゆれを軽く吸収して再トライ
            norm = name.replace(" ", "").replace("　", "")
            for k, v in name_to_no.items():
                if k.replace(" ", "").replace("　", "") == norm:
                    no = v
                    break
        resolved.append({"rank": entry["rank"], "no": no, "name": name})
    return resolved


def is_race_over(date_str):
    try:
        race_date = datetime.datetime.strptime(date_str, "%Y/%m/%d").date()
    except ValueError:
        return False
    return race_date <= datetime.date.today()


def main():
    if not os.path.isdir(RACES_DIR):
        print(f"[警告] {RACES_DIR} が見つかりません。")
        return
    os.makedirs(RESULTS_DIR, exist_ok=True)

    targets = []
    for fname in sorted(os.listdir(RACES_DIR)):
        if not fname.endswith(".json"):
            continue
        stem = fname[:-5]
        if os.path.exists(os.path.join(RESULTS_DIR, f"{stem}_result.json")):
            continue  # 取得済み
        with open(os.path.join(RACES_DIR, fname), encoding="utf-8") as f:
            race = json.load(f)
        if not is_race_over(race.get("date", "")):
            continue  # まだ開催前
        targets.append((stem, race))

    if not targets:
        print("取得対象（未確定かつ開催済み）のレースはありません。")
        return

    print(f"{len(targets)}件のレース結果を確認します。")
    got, skipped = 0, 0
    for stem, race in targets:
        raw = fetch_race_result(stem)
        if not raw:
            print(f"  - {stem}: まだ結果ページが見つかりません（未確定 or 掲載待ち）")
            skipped += 1
            time.sleep(REQUEST_INTERVAL_SEC)
            continue

        top3 = resolve_horse_numbers(raw["top3"], race)
        result = {
            "race_name": race.get("race_name", ""),
            "date": race.get("date", ""),
            "confirmed": True,
            "top3": top3,
            "umaren": raw.get("umaren", ""),
            "sanrenpuku": raw.get("sanrenpuku", ""),
        }
        out_path = os.path.join(RESULTS_DIR, f"{stem}_result.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  - {stem}: 結果を取得しました ({top3[0]['name'] if top3 else '?'} 1着)")
        got += 1
        time.sleep(REQUEST_INTERVAL_SEC)

    print(f"完了: 新規取得 {got}件 / 未確定・スキップ {skipped}件")


if __name__ == "__main__":
    main()
