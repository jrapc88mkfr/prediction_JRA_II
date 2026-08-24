"""
run_schedule.py  スケジューラー

schedule.json を読み込み、active:true のレースを順番に処理する。
GitHub Actions から呼ばれる。ローカルでも動作する。

動作:
  1. schedule.json を読む
  2. active:true のレースを全て処理
  3. 処理が完了したレースを active:false に更新
  4. schedule.json を保存（GitHub Actions がコミット）

環境変数:
  ANTHROPIC_API_KEY ... Claude API キー
  MANUAL_RACE       ... 手動指定レース名（GitHub Actions の workflow_dispatch から）
"""

import json
import os
import sys
from pathlib import Path

# ============================================================
# schedule.json のパス
# ============================================================
SCHEDULE_PATH = Path(__file__).parent / "schedule.json"


def load_schedule() -> dict:
    """schedule.json を読み込む"""
    if not SCHEDULE_PATH.exists():
        print(f"[ERROR] schedule.json が見つかりません: {SCHEDULE_PATH}")
        sys.exit(1)
    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_schedule(schedule: dict):
    """schedule.json を保存する（レースごとに1行）"""
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        f.write(f'{{"description": "{schedule["description"]}", "races": [\n')
        for i, r in enumerate(schedule["races"]):
            f.write("  " + json.dumps(r, ensure_ascii=False))
            if i < len(schedule["races"]) - 1:
                f.write(",")
            f.write("\n")
        f.write("]}")
    print("[SCHEDULE] schedule.json を更新しました")


def get_target_races(schedule: dict) -> list[str]:
    """
    処理対象のレース名リストを返す。
    環境変数 MANUAL_RACE が指定されている場合はそれを優先。
    """
    # GitHub Actions の workflow_dispatch で手動指定された場合
    manual = os.environ.get("MANUAL_RACE", "").strip()
    if manual:
        print(f"[SCHEDULE] 手動指定レース: {manual}")
        # schedule.json から該当レースの辞書を返す
        for r in schedule.get("races", []):
            if r["race_name"] == manual:
                return [r]
        # 見つからない場合は最低限の辞書を返す
        return [{"race_name": manual, "date": "", "venue": "", "race_no": "", "work_slug": ""}]

    # schedule.json から active:true のレースを取得
    # 辞書リストを返す（race_name/date/venue/race_no/work_slug）
    targets = [
        r for r in schedule.get("races", [])
        if r.get("active", False)
    ]

    if not targets:
        print("[SCHEDULE] active なレースが見つかりません")
        print("  schedule.json で処理したいレースを active:true にしてください")
    else:
        names = [r["race_name"] for r in targets]
        print(f"[SCHEDULE] 処理対象: {names}")

    return targets


def mark_as_done(schedule: dict, race_name: str, date: str = ""):
    """処理完了したレースを active:false に更新する"""
    for r in schedule.get("races", []):
        if r["race_name"] == race_name and r.get("active", False):
            r["active"] = False
            r["memo"] = r.get("memo", "") + " ✓処理済み"
            print(f"[SCHEDULE] {race_name} ({date}) → active:false に更新")
            break


def run_race(race: dict) -> bool:
    """
    schedule.json の1レース分の辞書を受け取って処理する。
    JRA_read_next.py の main() を直接呼び出す。
    戻り値: 成功=True、失敗=False
    """
    race_name = race.get("race_name", "")
    date      = race.get("date", "")
    venue     = race.get("venue", "")
    race_no   = race.get("race_no", "")
    work_slug = race.get("work_slug", "")

    print(f"\n{'='*60}")
    print(f"処理開始: {race_name} ({date} {venue}{race_no}R)")
    print(f"{'='*60}")

    try:
        import JRA_read_next as jra

        # schedule.json の全情報を main() に渡す
        jra.main(
            race_name = race_name,
            date_str  = date,
            venue     = venue,
            race_no   = race_no,
            work_slug = work_slug,
        )
        print(f"\n✓ {race_name} 処理完了")
        return True

    except SystemExit as e:
        # build_race_params で RACE_SCHEDULE 未登録の場合
        print(f"\n✗ {race_name} 処理失敗: schedule.json の設定を確認してください")
        print(f"  venue / race_no / work_slug が正しく設定されているか確認してください")
        return False

    except Exception as e:
        print(f"\n✗ {race_name} 処理失敗: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# メイン
# ============================================================
def main():
    print("=== 競馬予想スケジューラー 起動 ===\n")

    schedule = load_schedule()
    targets  = get_target_races(schedule)

    if not targets:
        print("処理するレースがありません。終了します。")
        sys.exit(0)

    results = {}
    for race in targets:
        race_name = race.get("race_name", "")
        date      = race.get("date", "")
        ok = run_race(race)
        results[race_name] = ok

        manual = os.environ.get("MANUAL_RACE", "").strip()
        if ok and not manual:
            mark_as_done(schedule, race_name, date)

    # schedule.json を保存（手動指定でない場合のみ）
    manual = os.environ.get("MANUAL_RACE", "").strip()
    if not manual:
        save_schedule(schedule)

    # 結果サマリー
    print(f"\n{'='*60}")
    print("=== 処理結果サマリー ===")
    for race_name, ok in results.items():
        status = "✓ 完了" if ok else "✗ 失敗"
        print(f"  {status}: {race_name}")
    print(f"{'='*60}")

    # 1つでも失敗したら終了コード1
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
