"""
3ハロンVII - HTML生成スクリプト

DATA/races/*.json を全件読み込み、
  public/races/{stem}.html   … レース予想＋結果ページ
  public/index.html          … レース一覧ページ
  DATA/index.json            … レース一覧マニフェスト（自動生成）
  public/static/             … style.css / script.js をコピー

を出力する。パスはすべて相対参照なので、
- ローカルで public/index.html をダブルクリックして開く (file://)
- GitHub Pages で公開する
のどちらでもそのまま動作する。

実行方法:
    python3 scripts/generate_html.py
"""
import json
import os
import shutil
import sys
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "scripts"))
from common import build_horses, evaluate_race_bet, summarize_bets  # noqa: E402

from jinja2 import Environment, FileSystemLoader

DATA_DIR = os.path.join(BASE, "DATA")
RACES_DIR = os.path.join(DATA_DIR, "races")
RESULTS_DIR = os.path.join(DATA_DIR, "results")
TEMPLATES_DIR = os.path.join(BASE, "templates")
STATIC_DIR = os.path.join(BASE, "static")
PUBLIC_DIR = os.path.join(BASE, "public")

env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def result_path_for(stem):
    return os.path.join(RESULTS_DIR, f"{stem}_result.json")


def build_all():
    if not os.path.isdir(RACES_DIR):
        print(f"[警告] {RACES_DIR} が見つかりません。DATA/races/ に予想JSONを配置してください。")
        return

    race_files = sorted(
        f for f in os.listdir(RACES_DIR) if f.endswith(".json")
    )
    if not race_files:
        print(f"[警告] {RACES_DIR} にレースJSONがありません。")

    os.makedirs(os.path.join(PUBLIC_DIR, "races"), exist_ok=True)

    race_tmpl = env.get_template("race.html")
    manifest = []
    bet_rows = []

    for fname in race_files:
        stem = fname[:-5]  # ".json" を除去
        race = load_json(os.path.join(RACES_DIR, fname))

        result = None
        rpath = result_path_for(stem)
        if os.path.exists(rpath):
            result = load_json(rpath)

        horses = build_horses(race)

        html = race_tmpl.render(
            race=race,
            horses=horses,
            result=result,
            static_prefix="../static/",
            index_href="../index.html",
        )
        out_path = os.path.join(PUBLIC_DIR, "races", f"{stem}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        manifest.append(dict(
            file=f"races/{stem}.html",
            stem=stem,
            date=race.get("date", ""),
            venue=race.get("course", ""),
            race_name=race.get("race_name", ""),
            race_no=race.get("race_no"),
            has_result=bool(result and result.get("confirmed")),
        ))
        status = "確定" if manifest[-1]["has_result"] else "予想"
        print(f"  - {stem}.html ({status})")

        bet = evaluate_race_bet(horses, result)
        if bet:
            bet_rows.append(dict(
                stem=stem, date=race.get("date", ""),
                race_name=race.get("race_name", ""), **bet,
            ))

    # 新しい日付のレースが上に来るよう、ファイル名(先頭が日付)の降順に並べる
    manifest.sort(key=lambda r: r["stem"], reverse=True)

    index_json_path = os.path.join(DATA_DIR, "index.json")
    with open(index_json_path, "w", encoding="utf-8") as f:
        json.dump(dict(
            generated_at=datetime.datetime.now().isoformat(timespec="seconds"),
            races=manifest,
        ), f, ensure_ascii=False, indent=2)
    print(f"  - index.json を更新 ({len(manifest)}件)")

    # 新しい日付順に並べる（bet_rowsも同じ順に）
    bet_rows.sort(key=lambda r: r["stem"], reverse=True)
    bet_summary = summarize_bets(bet_rows)

    index_tmpl = env.get_template("index.html")
    index_html = index_tmpl.render(
        races=manifest,
        bet_rows=bet_rows,
        bet_summary=bet_summary,
        static_prefix="static/",
        generated_at=datetime.datetime.now().strftime("%Y/%m/%d %H:%M"),
    )
    with open(os.path.join(PUBLIC_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print("  - index.html を出力")

    # static/ を public/static/ にコピー（毎回作り直す）
    public_static = os.path.join(PUBLIC_DIR, "static")
    if os.path.isdir(public_static):
        shutil.rmtree(public_static)
    shutil.copytree(STATIC_DIR, public_static)
    print("  - static/ を public/static/ にコピー")


if __name__ == "__main__":
    print("=== 3ハロンVII: HTML生成 ===")
    build_all()
    print("=== 完了 ===")
