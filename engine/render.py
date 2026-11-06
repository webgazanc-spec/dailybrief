"""Генерация статического сайта: чистый HTML + один маленький CSS, без JS,
без картинок. Типичная страница статьи весит 4–7 КБ."""
from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime, timezone
from html import escape
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

UI = {
    "ru": {"latest": "Последние новости", "source": "Источник", "read": "Читать оригинал на сайте", "context": "Контекст",
           "related": "Ещё по теме", "page": "Страница", "prev": "← Новее", "next": "Старее →", "about": "О проекте",
           "rights": "Правообладателям", "ai_note": "Пересказ подготовлен автоматически с помощью ИИ на основе открытой RSS-ленты источника. Возможны неточности — сверяйтесь с оригиналом.",
           "all": "Все", "empty": "Пока нет новостей.", "privacy": "Конфиденциальность"},
    "az": {"latest": "Son xəbərlər", "source": "Mənbə", "read": "Orijinalı oxuyun", "context": "Kontekst",
           "related": "Oxşar xəbərlər", "page": "Səhifə", "prev": "← Yenilər", "next": "Köhnələr →", "about": "Layihə haqqında",
           "rights": "Hüquq sahiblərinə", "ai_note": "Xülasə mənbənin açıq RSS lentindən süni intellekt vasitəsilə avtomatik hazırlanıb. Dəqiqlik üçün orijinala baxın.",
           "all": "Hamısı", "empty": "Hələ xəbər yoxdur.", "privacy": "Məxfilik"},
    "en": {"latest": "Latest news", "source": "Source", "read": "Read the original at", "context": "Context",
           "related": "Related", "page": "Page", "prev": "← Newer", "next": "Older →", "about": "About",
           "rights": "Copyright & Removal", "ai_note": "This brief was written automatically by AI from the source's public RSS feed. It may contain errors — check the original.",
           "all": "All", "empty": "No news yet.", "privacy": "Privacy Policy"},
}

CAT_COLORS = ["#c2410c", "#1d4ed8", "#047857", "#7c3aed", "#b45309", "#be123c", "#0e7490", "#4d7c0f"]

_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяəğıöşüç",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya", "e", "g", "i", "o", "s", "u", "c"]))


def slugify(text: str, max_len: int = 60) -> str:
    s = "".join(_TR.get(ch, ch) for ch in text.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:max_len].rstrip("-") or "news"


class Site:
    def __init__(self, cfg: dict, out: Path, root: Path):
        self.cfg, self.out, self.root = cfg, out, root
        s = cfg["site"]
        self.base = s["base_url"].rstrip("/")
        self.lang = s.get("language", "ru")
        self.t = UI.get(self.lang, UI["en"])
        self.cats = cfg["categories"]
        self.cat_color = {k: CAT_COLORS[i % len(CAT_COLORS)] for i, k in enumerate(self.cats)}
        tz = s.get("timezone", "Asia/Baku")
        try:
            self.tz = ZoneInfo(tz) if ZoneInfo else timezone.utc
        except Exception:
            self.tz = timezone.utc
        # путь сайта внутри домена (для GitHub Pages вида user.github.io/repo)
        self.prefix = "/" + self.base.split("://", 1)[-1].split("/", 1)[1] if "/" in self.base.split("://", 1)[-1] else ""
        self.prefix = self.prefix.rstrip("/")

    # ---------- ads ----------
    def ad(self, slot: str) -> str:
        """Рекламный блок. Если код слота пуст — показывается аккуратная
        заглушка фиксированной высоты (чтобы видеть разметку и не было
        «прыжков» вёрстки, когда реклама подключится)."""
        ads = self.cfg.get("ads", {})
        if not ads.get("enabled"):
            return ""
        code = ads.get("slots", {}).get(slot, "")
        inner = code if code else f'<span>Ad · {slot}</span>'
        return f'<div class="ad ad-{slot}{"" if code else " ph"}" aria-label="Advertisement">{inner}</div>'

    # ---------- helpers ----------
    def url(self, path: str) -> str:
        return f"{self.prefix}/{path.lstrip('/')}"

    def abs(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    def fmt_date(self, iso: str) -> str:
        d = datetime.fromisoformat(iso).astimezone(self.tz)
        if self.lang == "en":
            return d.strftime("%b ") + str(d.day) + d.strftime(", %Y, ") + d.strftime("%I:%M %p").lstrip("0")
        return d.strftime("%d.%m.%Y, %H:%M")

    def write(self, rel: str, content: str):
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def article_path(self, a: dict) -> str:
        return f"a/{a['slug']}/"

    def layout(self, title: str, body: str, *, desc: str = "", canonical: str = "", extra_head: str = "", active: str = "") -> str:
        s = self.cfg["site"]
        nav = [f'<a href="{self.url("")}"{" class=on" if active == "" else ""}>{self.t["all"]}</a>']
        for key, name in self.cats.items():
            on = " class=on" if active == key else ""
            nav.append(f'<a href="{self.url(f"c/{key}/")}"{on}>{escape(name)}</a>')
        full_title = title if title == s["name"] else f"{title} — {s['name']}"
        if s.get("google_site_verification"):
            extra_head += f'<meta name="google-site-verification" content="{escape(s["google_site_verification"])}">'
        if self.cfg.get("ads", {}).get("enabled") and self.cfg["ads"].get("head_code"):
            extra_head += self.cfg["ads"]["head_code"]
        return f"""<!doctype html>
<html lang="{self.lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(full_title)}</title>
<meta name="description" content="{escape(desc or s['tagline'])}">
{f'<link rel="canonical" href="{canonical}">' if canonical else ''}
<link rel="stylesheet" href="{self.url('style.css')}">
<link rel="alternate" type="application/rss+xml" title="{escape(s['name'])}" href="{self.url('feed.xml')}">
<meta property="og:site_name" content="{escape(s['name'])}"><meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(desc or s['tagline'])}">
{extra_head}</head><body>
<header><div class="w"><a class="logo" href="{self.url('')}">{escape(s['name'])}</a><span class="tag">{escape(s['tagline'])}</span></div>
<nav class="w">{''.join(nav)}</nav></header>
<div class="w">{self.ad('header')}</div>
<main class="w">{body}</main>
<div class="w">{self.ad('footer')}</div>
<footer><div class="w">© {datetime.now().year} {escape(s['name'])} · <a href="{self.url('about/')}">{self.t['about']}</a> · <a href="{self.url('privacy/')}">{self.t['privacy']}</a> · <a href="{self.url('rights/')}">{self.t['rights']}</a> · <a href="{self.url('feed.xml')}">RSS</a></div></footer>
</body></html>"""

    def card(self, a: dict) -> str:
        words = a["summary"].split()
        teaser = " ".join(words[:28]) + ("…" if len(words) > 28 else "")
        color = self.cat_color.get(a["category"], "#555")
        return f"""<article class="card" style="--c:{color}">
<div class="meta"><span class="cat">{escape(self.cats.get(a['category'], a['category']))}</span> · {self.fmt_date(a['published'])}</div>
<h2><a href="{self.url(self.article_path(a))}">{escape(a['title'])}</a></h2>
<p>{escape(teaser)}</p>
<div class="src">{self.t['source']}: {escape(a['source_name'])}</div></article>"""

    def pager(self, base: str, page: int, pages: int) -> str:
        if pages <= 1:
            return ""
        def href(p):
            return self.url(base if p == 1 else f"{base}page/{p}/")
        prev = f'<a href="{href(page - 1)}">{self.t["prev"]}</a>' if page > 1 else "<span></span>"
        nxt = f'<a href="{href(page + 1)}">{self.t["next"]}</a>' if page < pages else "<span></span>"
        return f'<div class="pager">{prev}<span>{self.t["page"]} {page}/{pages}</span>{nxt}</div>'

    # ---------- pages ----------
    def listing(self, items: list[dict], base: str, heading: str, active: str):
        per = int(self.cfg["site"].get("per_page", 24))
        pages = max(1, math.ceil(len(items) / per))
        for p in range(1, pages + 1):
            chunk = items[(p - 1) * per: p * per]
            n_ad = int(self.cfg.get("ads", {}).get("every_n_cards", 6) or 0)
            parts = []
            for i, a in enumerate(chunk, 1):
                parts.append(self.card(a))
                if n_ad and i % n_ad == 0 and i < len(chunk):
                    parts.append(f'<div class="feed-ad">{self.ad("in_feed")}</div>')
            cards = "".join(parts) or f"<p>{self.t['empty']}</p>"
            body = f'<h1>{escape(heading)}</h1><div class="grid">{cards}</div>{self.pager(base, p, pages)}'
            rel = base if p == 1 else f"{base}page/{p}/"
            title = heading if p == 1 else f"{heading} — {self.t['page']} {p}"
            self.write(rel + "index.html", self.layout(title, body, canonical=self.abs(rel), active=active))

    def article(self, a: dict, related: list[dict]):
        plist = [f"<p>{escape(x.strip())}</p>" for x in a["summary"].split("\n\n") if x.strip()]
        if len(plist) >= 2:
            plist.insert(1, self.ad("article_middle"))
        paras = "".join(plist)
        ctx = f'<aside class="ctx"><h3>{self.t["context"]}</h3><p>{escape(a["context"])}</p></aside>' if a.get("context") else ""
        tags = "".join(f"<span>#{escape(t)}</span>" for t in a.get("tags", []))
        rel_html = ""
        if related:
            rel_html = f'<section class="rel"><h3>{self.t["related"]}</h3><ul>' + "".join(
                f'<li><a href="{self.url(self.article_path(r))}">{escape(r["title"])}</a></li>' for r in related) + "</ul></section>"
        ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": a["title"],
              "datePublished": a["published"], "inLanguage": self.lang,
              "isBasedOn": a["source_url"], "publisher": {"@type": "Organization", "name": self.cfg["site"]["name"]}}
        head = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'
        color = self.cat_color.get(a["category"], "#555")
        body = f"""<article class="post" style="--c:{color}">
<div class="meta"><a class="cat" href="{self.url(f"c/{a['category']}/")}">{escape(self.cats.get(a['category'], a['category']))}</a> · {self.fmt_date(a['published'])}</div>
<h1>{escape(a['title'])}</h1>
{paras}{ctx}
<div class="source"><b>{self.t['source']}:</b> {escape(a['source_name'])} — «{escape(a['source_title'])}»
<a class="btn" href="{escape(a['source_url'])}" target="_blank" rel="noopener">{self.t['read']} {escape(a['source_name'])} →</a></div>
<p class="note">{self.t['ai_note']}</p>
<div class="tags">{tags}</div>{self.ad('article_bottom')}</article>{rel_html}"""
        desc = " ".join(a["summary"].split()[:30])
        self.write(self.article_path(a) + "index.html",
                   self.layout(a["title"], body, desc=desc, canonical=self.abs(self.article_path(a)), extra_head=head, active=a["category"]))

    def static_pages(self):
        s = self.cfg["site"]
        mail = escape(s["contact_email"])
        name = escape(s["name"])
        about = f"""<article class="post"><h1>{self.t['about']}</h1>
<p>{name} is an automated news digest. We do not republish other outlets' articles. From each publisher's public RSS feed we take only the headline and short description, and an AI system writes an original brief summary of the reported facts plus background context in its own words.</p>
<p>Every brief names its original source and links directly to the original story. We do not use publishers' photos or illustrations.</p>
<p>Every text is automatically checked for wording overlap with its source; briefs that reuse source wording are not published. Briefs are machine-written and may contain errors — always check the original report.</p>
<p>Contact: <a href="mailto:{mail}">{mail}</a></p></article>"""
        rights = f"""<article class="post"><h1>{self.t['rights']}</h1>
<p>If you represent a publisher and do not want your content referenced on {name}, or you believe any page infringes your rights, email <a href="mailto:{mail}">{mail}</a> with the URL of the page. Notices under the U.S. DMCA (17 U.S.C. § 512) are welcome at the same address.</p>
<p>We remove the page and exclude the source from processing within 24 hours of a valid request.</p></article>"""
        privacy = f"""<article class="post"><h1>{self.t['privacy']}</h1>
<p>{name} does not require registration and does not collect personal information directly. Our pages contain no tracking scripts of our own.</p>
<p>We show advertising. Third-party vendors, including Google, use cookies to serve ads based on a user's prior visits to this and other websites. Google's use of advertising cookies enables it and its partners to serve ads based on visits to this and/or other sites. You can opt out of personalized advertising at <a href="https://adssettings.google.com" rel="nofollow">Google Ads Settings</a> or <a href="https://www.aboutads.info/choices/" rel="nofollow">aboutads.info</a>.</p>
<p>Residents of California and other U.S. states with privacy laws may opt out of the sale or sharing of personal information for targeted advertising through the links above or by contacting us.</p>
<p>Questions: <a href="mailto:{mail}">{mail}</a></p></article>"""
        self.write("about/index.html", self.layout(self.t["about"], about))
        self.write("rights/index.html", self.layout(self.t["rights"], rights))
        self.write("privacy/index.html", self.layout(self.t["privacy"], privacy))
        ads_txt = self.cfg.get("ads", {}).get("ads_txt", "")
        if ads_txt:
            self.write("ads.txt", ads_txt.strip() + "\n")
        self.write("404.html", self.layout("404", f'<h1>404</h1><p><a href="{self.url("")}">← {escape(s["name"])}</a></p>'))

    def feeds(self, items: list[dict]):
        s = self.cfg["site"]
        urls = [self.abs("")] + [self.abs(f"c/{k}/") for k in self.cats] + [self.abs(self.article_path(a)) for a in items]
        self.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                   + "".join(f"<url><loc>{escape(u)}</loc></url>" for u in urls) + "</urlset>")
        self.write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {self.abs('sitemap.xml')}\n")
        from email.utils import format_datetime
        rss_items = "".join(
            f"<item><title>{escape(a['title'])}</title><link>{escape(self.abs(self.article_path(a)))}</link>"
            f"<guid>{escape(self.abs(self.article_path(a)))}</guid><pubDate>{format_datetime(datetime.fromisoformat(a['published']))}</pubDate>"
            f"<description>{escape(' '.join(a['summary'].split()[:40]))}</description></item>" for a in items[:50])
        self.write("feed.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>{escape(s["name"])}</title>'
                   f"<link>{escape(self.abs(''))}</link><description>{escape(s['tagline'])}</description>{rss_items}</channel></rss>")

    def build(self, items: list[dict]):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        shutil.copy(self.root / "assets" / "style.css", self.out / "style.css")
        (self.out / ".nojekyll").write_text("")
        items = sorted(items, key=lambda a: a["published"], reverse=True)
        self.listing(items, "", self.t["latest"], "")
        for key, name in self.cats.items():
            self.listing([a for a in items if a["category"] == key], f"c/{key}/", name, key)
        for a in items:
            related = [r for r in items if r["category"] == a["category"] and r["id"] != a["id"]][:4]
            self.article(a, related)
        self.static_pages()
        self.feeds(items)
