"""
3ハロンVII - schedule.json 自動アクティブ化スクリプト

・「次の日曜日（今日が日曜ならその日）」の日付に一致するレースを active:true にする
  → run_schedule.py が拾って JRA_read_next.py による予想生成の対象にする
・すでに active:true だが日付が過去になっているレース（前週分の消し忘れ）は
  active:false, memo:"処理済み" に戻す

実行方法:
    python3 scripts/activate_weekly.py
"""
import json
import os
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_PATH = os.path.join(BASE, "schedule.json")


def _parse_date(s):
    try:
        return datetime.datetime.strptime(s, "%Y/%m/%d").date()
    except ValueError:
        return None


def next_target_sunday(today=None):
    today = today or datetime.date.today()
    days_ahead = (6 - today.weekday()) % 7  # 月曜=0 ... 日曜=6
    return today + datetime.timedelta(days=days_ahead)


def main():
    if not os.path.exists(SCHEDULE_PATH):
        print(f"[警告] {SCHEDULE_PATH} が見つかりません。")
        return

    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        schedule = json.load(f)

    today = datetime.date.today()
    target = next_target_sunday(today)
    print(f"今日: {today}  対象日(今週末): {target}")

    activated, deactivated = [], []
    for race in schedule.get("races", []):
        d = _parse_date(race.get("date", ""))
        if d is None:
            continue

        if d == target:
            if not race.get("active"):
                activated.append(race["race_name"])
            race["active"] = True
            race["memo"] = ""
        elif race.get("active") and d < today:
            # 前週以前の分で active のまま残っているものは処理済みに戻す
            deactivated.append(race["race_name"])
            race["active"] = False
            race["memo"] = "処理済み"

    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)

    if activated:
        print("active:true にしたレース: " + ", ".join(activated))
    else:
        print(f"{target} に該当するレースはありませんでした（開催なし週の可能性）。")
    if deactivated:
        print("処理済みに戻したレース: " + ", ".join(deactivated))


if __name__ == "__main__":
    main()
