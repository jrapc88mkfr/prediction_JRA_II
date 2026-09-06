"""schedule.json の読み書き共通処理。

元のファイルのスタイル（1行目に description、以降レース1件ごとに
コンパクトな1行JSON）を保ったまま保存する。
json.dump(indent=2)を使うと全レースが多階層に展開されて見づらくなるため、
専用のシリアライズ処理を用意している。
"""
import json


def load_schedule(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_schedule(schedule, path):
    desc = schedule.get("description", "")
    races = schedule.get("races", [])
    lines = ['{"description": ' + json.dumps(desc, ensure_ascii=False) + ', "races": [']
    for i, r in enumerate(races):
        comma = "," if i < len(races) - 1 else ""
        lines.append("  " + json.dumps(r, ensure_ascii=False) + comma)
    lines.append("]}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
