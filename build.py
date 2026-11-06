#!/usr/bin/env python3
"""Один запуск = собрать ленты → переписать новое → пересобрать сайт.

    python build.py                 # рабочий режим (нужен ANTHROPIC_API_KEY)
    python build.py --mock          # без ИИ, для проверки вёрстки
    python build.py --feeds-dir samples  # брать ленты из локальных .xml (тест без сети)

Сайт собирается в папку public/, база статей хранится в data/articles.json.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine import fetch, rewrite
from engine.render import Site, slugify

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--mock", action="store_true", help="не вызывать ИИ, писать тестовые тексты")
    ap.add_argument("--feeds-dir", help="читать ленты из локальной папки вместо интернета")
    ap.add_argument("--render-only", action="store_true", help="только пересобрать HTML")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.mock:
        cfg["ai"]["provider"] = "mock"

    articles: list[dict] = load(DATA / "articles.json", [])
    seen: dict = load(DATA / "seen.json", {})          # id -> дата, чтобы не обрабатывать повторно
    feed_state: dict = load(DATA / "feed_state.json", {})
    blocked_src = set(cfg.get("blocked_sources", []))
    blocked_url = set(cfg.get("blocked_urls", []))

    if not args.render_only:
        # 1. сбор
        fresh = []
        for src in cfg["sources"]:
            if src["name"] in blocked_src:
                continue
            if args.feeds_dir:
                f = Path(args.feeds_dir) / (slugify(src["name"]) + ".xml")
                items = fetch.parse_feed(f.read_bytes(), src) if f.exists() else []
            else:
                items = fetch.fetch_source(src, feed_state)
            new = [i for i in items if i["id"] not in seen and i["source_url"] not in blocked_url]
            print(f"· {src['name']}: в ленте {len(items)}, новых {len(new)}")
            fresh.extend(new)

        # самые свежие — первыми; лимит на запуск держит расходы на ИИ под контролем
        fresh.sort(key=lambda i: i["published"], reverse=True)
        fresh = fresh[: int(cfg["ai"].get("max_new_per_run", 25))]

        # 2. пересказ
        now = datetime.now(timezone.utc).isoformat()
        published = skipped = 0
        for item in fresh:
            print(f"  → {item['source_title'][:80]}")
            result = rewrite.rewrite(item, cfg)
            seen[item["id"]] = now
            if not result:
                skipped += 1
                print("    пропущено: не удалось сделать оригинальный пересказ")
                continue
            art = {**item, **result}
            art["slug"] = f"{slugify(result['title'])}-{item['id'][:6]}"
            articles.append(art)
            published += 1
        print(f"Опубликовано {published}, пропущено {skipped}")

    # 3. чистка: храним только retention_days — сайт остаётся маленьким
    days = int(cfg["site"].get("retention_days", 30))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    articles = [a for a in articles if a["published"] >= cutoff
                and a["source_name"] not in blocked_src and a["source_url"] not in blocked_url]
    seen_cut = (datetime.now(timezone.utc) - timedelta(days=days + 7)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= seen_cut}

    save(DATA / "articles.json", articles)
    save(DATA / "seen.json", seen)
    save(DATA / "feed_state.json", feed_state)

    # 4. сборка сайта
    Site(cfg, ROOT / "public", ROOT).build(articles)
    print(f"Сайт собран: {len(articles)} материалов → public/")


if __name__ == "__main__":
    main()
