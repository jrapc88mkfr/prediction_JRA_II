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
from common import build_horses, evaluate_race_bet, summarize_bets, generate_pace_forecast  # noqa: E402

from jinja2 import Environment, FileSystemLoader

DATA_DIR = os.path.join(BASE, "DATA")
RACES_DIR = os.path.join(DATA_DIR, "races")
RESULTS_DIR = os.path.join(DATA_DIR, "results")
TEMPLATES_DIR = os.path.join(BASE, "templates")
STATIC_DIR = os.path.join(BASE, "static")
PUBLIC_DIR = os.path.join(BASE, "public")

env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))

# race_shape.label（日本語）→ CSSクラス名に使える英字スラッグへの変換
SHAPE_CLASS = {
    "堅い"    : "kata",
    "やや堅い" : "yaya-kata",
    "やや荒れる": "yaya-are",
    "荒れる"   : "are",
}


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

    # 枠有利度表（コース・距離別）と、コースキー解決用の schedule マップ
    waku_data = {}
    waku_path = os.path.join(BASE, "waku_advantage.json")
    if os.path.exists(waku_path):
        waku_data = (load_json(waku_path) or {}).get("data", {})
    schedule_map = {}
    sched_path = os.path.join(BASE, "schedule.json")
    if os.path.exists(sched_path):
        for r in (load_json(sched_path) or {}).get("races", []):
            if r.get("surface") and r.get("distance"):
                schedule_map[r.get("race_name", "")] = \
                    f"{r.get('venue', '')}_{r['surface']}_{r['distance']}"

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
        pace_forecast = generate_pace_forecast(horses, race)

        # 枠順の有利不利: 候補のコースキーを優先し、無ければ schedule から引く
        # 障害レースは平地の枠統計の対象外（候補キーの残留値も使わない）
        waku_key = (race.get("candidate_prediction") or {}).get("コースキー") \
            or schedule_map.get(race.get("race_name", ""))
        if "ジャンプ" in race.get("race_name", ""):
            waku_key = None
        waku = waku_data.get(waku_key) if waku_key else None
        waku_total = sum(int(v.get("出走", 0)) for v in waku.values()) if waku else 0

        html = race_tmpl.render(
            race=race,
            horses=horses,
            result=result,
            pace_forecast=pace_forecast,
            waku=waku,
            waku_key=waku_key,
            waku_total=waku_total,
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
            bet=None,
            race_shape=race.get("race_shape"),
            race_shape_class=SHAPE_CLASS.get((race.get("race_shape") or {}).get("label"), ""),
            betting_estimate=race.get("betting_estimate"),
        ))
        status = "確定" if manifest[-1]["has_result"] else "予想"
        print(f"  - {stem}.html ({status})")

        bet = evaluate_race_bet(horses, result, race)
        if bet:
            manifest[-1]["bet"] = bet
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
