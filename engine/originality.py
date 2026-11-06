"""Автоматическая проверка, что текст действительно пересказан, а не скопирован.

Две метрики:
  * доля общих n-грамм (по умолчанию 6 слов подряд) между нашим текстом и
    исходным заголовком+описанием;
  * самая длинная общая последовательность слов.

Если ИИ «схитрил» и оставил куски оригинала — статья отправляется на
переписывание, а при повторной неудаче вообще не публикуется как пересказ.
"""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def shingles(ws: list[str], n: int) -> set[tuple[str, ...]]:
    if len(ws) < n:
        return set()
    return {tuple(ws[i:i + n]) for i in range(len(ws) - n + 1)}


def longest_common_run(a: list[str], b: list[str]) -> int:
    """Самая длинная общая подпоследовательность подряд идущих слов (DP, O(n*m),
    тексты короткие — это быстро)."""
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def check(generated: str, source: str, cfg: dict) -> dict:
    n = int(cfg.get("shingle_size", 6))
    gw, sw = words(generated), words(source)
    g_sh, s_sh = shingles(gw, n), shingles(sw, n)
    ratio = (len(g_sh & s_sh) / len(g_sh)) if g_sh else 0.0
    run = longest_common_run(gw, sw)
    ok = ratio <= float(cfg.get("max_shared_ratio", 0.12)) and run < int(cfg.get("max_common_run_words", 10))
    return {"ok": ok, "shared_ratio": round(ratio, 3), "common_run": run}
