"""Пересказ новости своими словами с помощью ИИ.

ИИ получает только заголовок и короткое описание из RSS и пишет:
  * собственный заголовок;
  * пересказ фактов своими словами (факты и «новости дня» авторским
    правом не охраняются — охраняется форма изложения);
  * блок «Контекст» — пояснение терминов/фона, без выдумывания новых фактов;
  * теги.
Результат проходит проверку originality.check(); при неудаче — повтор.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from . import originality

LANG_NAMES = {"ru": "Russian", "az": "Azerbaijani (Latin script)", "en": "English", "tr": "Turkish"}

PROMPT = """You are an editor of a news digest website. Write an ORIGINAL short news brief in {lang} based ONLY on the facts below.

Strict rules:
1. Do NOT copy phrases from the source. Never reuse more than 5 consecutive words from it (names, titles and numbers are fine). Use your own sentence structure.
2. Use ONLY facts present in the source. Do not invent quotes, numbers, names, dates or outcomes. If the source is thin, write less rather than make things up.
3. No direct quotations at all.
4. "context" explains background a general reader may need (what an organisation is, what a term means, why the topic matters in general). It must not add new claims about this specific event. If nothing useful, return an empty string.
5. Neutral, factual tone. No clickbait, no opinions.
6. Summary length: {wmin}-{wmax} words, 2-3 short paragraphs separated by \\n\\n.

Pick "category" from: {cats}.

Return ONLY valid JSON, no markdown:
{{"title": "...", "summary": "...", "context": "...", "category": "...", "tags": ["...", "..."]}}

SOURCE ({source_name}):
Title: {title}
Description: {desc}
"""


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={**headers, "content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _call_llm(prompt: str, ai: dict) -> str:
    provider = ai.get("provider", "anthropic")
    if provider == "mock":
        return _mock_answer(prompt)
    key = os.environ.get(ai.get("api_key_env", "ANTHROPIC_API_KEY"), "")
    if not key:
        raise RuntimeError(f"нет API-ключа в переменной {ai.get('api_key_env')}")
    if provider == "anthropic":
        data = _post_json("https://api.anthropic.com/v1/messages",
                          {"x-api-key": key, "anthropic-version": "2023-06-01"},
                          {"model": ai["model"], "max_tokens": 1200, "temperature": 0.7,
                           "messages": [{"role": "user", "content": prompt}]})
        return "".join(b.get("text", "") for b in data.get("content", []))
    # любой OpenAI-совместимый API (OpenAI, OpenRouter, локальная модель и т.п.)
    data = _post_json(ai.get("openai_base_url", "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
                      {"authorization": f"Bearer {key}"},
                      {"model": ai["model"], "temperature": 0.7,
                       "messages": [{"role": "user", "content": prompt}]})
    return data["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("ИИ вернул не JSON")
    return json.loads(m.group(0))


def rewrite(item: dict, cfg: dict) -> dict | None:
    """Возвращает словарь с полями пересказа или None, если пересказ
    не удалось сделать достаточно оригинальным."""
    ai, orig_cfg = cfg["ai"], cfg["originality"]
    wmin, wmax = ai.get("summary_words", [110, 180])
    lang = LANG_NAMES.get(cfg["site"]["language"], cfg["site"]["language"])
    prompt = PROMPT.format(lang=lang, wmin=wmin, wmax=wmax, cats=", ".join(cfg["categories"]),
                           source_name=item["source_name"], title=item["source_title"],
                           desc=item["source_desc"] or "(no description)")
    source_text = item["source_title"] + " " + item["source_desc"]
    attempts = int(orig_cfg.get("retries", 2)) + 1
    for attempt in range(attempts):
        p = prompt
        if attempt:
            p += "\nYour previous version reused too much wording from the source. Rephrase everything more freely.\n"
        try:
            data = _extract_json(_call_llm(p, ai))
        except Exception as e:
            print(f"    ИИ: ошибка ({e})")
            continue
        title = str(data.get("title", "")).strip()
        summary = str(data.get("summary", "")).strip()
        if not title or len(originality.words(summary)) < 25:
            continue
        report = originality.check(title + " " + summary, source_text, orig_cfg)
        if not report["ok"]:
            print(f"    оригинальность не пройдена {report}, повтор")
            continue
        cat = data.get("category") if data.get("category") in cfg["categories"] else item["category"]
        return {
            "title": title[:180],
            "summary": summary,
            "context": str(data.get("context", "")).strip(),
            "category": cat,
            "tags": [str(t).strip()[:40] for t in (data.get("tags") or [])][:6],
            "originality": report,
        }
    return None


# ---------- тестовый режим без ИИ ----------
def _mock_answer(prompt: str) -> str:
    """Заглушка для локальной проверки сборки без API-ключа."""
    t = re.search(r"Title: (.*)", prompt).group(1)
    return json.dumps({
        "title": "Brief: " + " ".join(t.split()[:7]),
        "summary": ("This is a placeholder brief generated in test mode without calling the AI. "
                    "In production this area holds an original two or three paragraph summary "
                    "written from the facts in the publisher's feed.\n\nEach brief is checked "
                    "automatically for wording overlap with the source, and anything that borrows "
                    "too much is rewritten or dropped before it can be published."),
        "context": "Here the AI explains background and terms a general reader may need.",
        "category": "us",
        "tags": ["test", "demo"],
}, ensure_ascii=False)
