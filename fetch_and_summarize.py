#!/usr/bin/env python3
"""
Veille techno personnelle.

- Récupère les flux RSS (ou les pages de liste HTML) définis dans config.json
- Filtre les articles hors sujet (filtres par rubrique)
- Produit un résumé court (carte) et un résumé détaillé (fenêtre au clic)
- Traduit en français les résumés des articles étrangers
- Ajoute la rubrique « Anglais » (cours + exercices dans le dossier english/)
- Génère un site statique : output/index.html

Usage :
    python fetch_and_summarize.py
"""

import json
import os
import random
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

import translator
from summarizer import summarize, summarize_long

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DATA_PATH = os.path.join(BASE_DIR, "data", "history.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
TOPICS_PATH = os.path.join(BASE_DIR, "topics.json")
LESSONS_DIR = os.path.join(BASE_DIR, "english", "lessons")      # un fichier .json par leçon
LESSONS_PATH = os.path.join(BASE_DIR, "english", "lessons.json")  # ancien format (secours)
DAILY_PATH = os.path.join(BASE_DIR, "english", "daily.json")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
REQUEST_TIMEOUT = 10

DEFAULT_COLOR = "#93a0b3"
DEFAULT_ICON = "📰"
ENGLISH_NAME = "Anglais"
ENGLISH_ICON = "🇬🇧"
ENGLISH_COLOR = "#f0b429"

# liens de pages HTML déjà examinés et rejetés par le filtre (évite de les
# re-télécharger à chaque lancement)
REJECTED = set()


def log(msg):
    print(msg, file=sys.stderr)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def load_config():
    return load_json(CONFIG_PATH, {})


def load_history():
    return load_json(DATA_PATH, {"seen_links": [], "days": []})


def save_history(history):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def strip_html(html_fragment):
    return BeautifulSoup(html_fragment or "", "html.parser").get_text(" ", strip=True)


# --------------------------------------------------------------------------
# Lecture des pages d'articles
# --------------------------------------------------------------------------

def fetch_article_full(url):
    """
    Télécharge la page d'un article. Renvoie un dict :
    text, image, title, description, date (AAAA-MM-JJ). Champs vides en cas d'échec.
    """
    empty = {"text": "", "image": "", "title": "", "description": "", "date": ""}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return empty

    def meta(*names):
        for name in names:
            tag = (soup.find("meta", attrs={"property": name})
                   or soup.find("meta", attrs={"name": name}))
            if tag and tag.get("content", "").strip():
                return tag["content"].strip()
        return ""

    image = meta("og:image", "twitter:image")
    if image and not image.startswith("http"):
        image = urljoin(url, image)

    title = meta("og:title", "twitter:title")
    if not title and soup.h1:
        title = soup.h1.get_text(" ", strip=True)
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    date_match = re.match(r"\d{4}-\d{2}-\d{2}",
                          meta("article:published_time", "datePublished", "date", "og:updated_time"))
    date = date_match.group(0) if date_match else ""

    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    container = soup.find("article") or soup
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    # on ignore les paragraphes très courts (menus, légendes, mentions)
    text = " ".join(p for p in paragraphs if len(p) >= 40)

    return {
        "text": text,
        "image": image,
        "title": title,
        "description": meta("og:description", "description"),
        "date": date,
    }


def extract_image(entry):
    """Cherche une image dans les métadonnées d'une entrée de flux RSS."""
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key, []) or []:
            url = media.get("url", "")
            if url.startswith("http"):
                return url
    for enc in entry.get("enclosures", []) or []:
        if enc.get("type", "").startswith("image") and enc.get("href", "").startswith("http"):
            return enc["href"]
    html = entry.get("summary", "") + "".join(
        c.get("value", "") for c in entry.get("content", []) or []
    )
    img = BeautifulSoup(html, "html.parser").find("img")
    if img and img.get("src", "").startswith("http"):
        return img["src"]
    return ""


def entry_date(entry, fallback):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return time.strftime("%Y-%m-%d", parsed)
    return fallback


# --------------------------------------------------------------------------
# Sources : flux RSS et pages HTML
# --------------------------------------------------------------------------

def fetch_feed(url):
    """Télécharge un flux avec des en-têtes de navigateur. Renvoie (flux, diagnostic)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        parsed = feedparser.parse(resp.content)
        if resp.status_code != 200:
            return parsed, f"HTTP {resp.status_code}"
        if not parsed.entries:
            return parsed, "HTTP 200 mais contenu illisible comme flux RSS (page web ?)"
        return parsed, "OK"
    except Exception as e:
        return feedparser.parse(b""), f"erreur réseau : {e.__class__.__name__}"


def fetch_listing(feed_cfg):
    """
    Pour un site SANS flux RSS (type "html") : lit la page de liste et renvoie
    les liens d'articles trouvés. `link_contains` (ex. "/post/") aide à ne
    garder que les vrais articles.
    """
    url = feed_cfg["url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        return [], f"erreur réseau : {e.__class__.__name__}"
    if resp.status_code != 200:
        return [], f"HTTP {resp.status_code}"

    soup = BeautifulSoup(resp.text, "html.parser")
    host = urlparse(url).netloc.replace("www.", "")
    must = feed_cfg.get("link_contains", "")
    seen, links = set(), []

    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"]).split("#")[0]
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https") or parsed.netloc.replace("www.", "") != host:
            continue
        if must:
            if must not in href:
                continue
        else:
            # sans indication : lien avec un chemin et un intitulé assez long
            segments = [s for s in parsed.path.split("/") if s]
            if not segments or len(a.get_text(" ", strip=True)) < 25:
                continue
            if href.rstrip("/") == url.rstrip("/"):
                continue
        if href not in seen:
            seen.add(href)
            links.append(href)

    if not links:
        return [], "aucun lien d'article trouvé (ajoute \"link_contains\" dans config.json)"
    return links, "OK"


# --------------------------------------------------------------------------
# Filtres par mots-clés
# --------------------------------------------------------------------------

def compile_terms(terms, stem):
    """
    Construit une regex à partir d'une liste de mots-clés.
    stem=True  : « photo » trouve aussi photos, photographe, photoshop...
    stem=False : mot entier (+ pluriel simple), « mac » ne trouve pas « machine ».
    """
    if not terms:
        return None
    alternatives = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    tail = r"\w*" if stem else r"(?:s|x)?(?!\w)"
    return re.compile(r"(?<!\w)(?:" + alternatives + r")" + tail, re.IGNORECASE)


def make_filter(category_cfg, use_include=True):
    """
    Renvoie accept(title, text) -> bool d'après la clé "filters" de la rubrique :
      exclude_any : article rejeté si UN de ces mots est dans le TITRE
      include_any : article gardé seulement si UN de ces mots est dans le
                    titre, le résumé du flux ou les tags (si use_include)
    """
    filters = category_cfg.get("filters") or {}
    exclude = compile_terms(filters.get("exclude_any"), stem=False)
    include = compile_terms(filters.get("include_any"), stem=True) if use_include else None

    def accept(title, text):
        if exclude and exclude.search(title):
            return False
        if include and not include.search(f"{title} {text}"):
            return False
        return True

    return accept


# --------------------------------------------------------------------------
# Classement par sous-thème (règles dans topics.json)
# --------------------------------------------------------------------------

def build_topic_classifier(category_name, topics_cfg):
    """
    Renvoie classify(source, title, body) -> nom du sous-thème, ou None si la
    rubrique n'a pas de règles. Ordre de décision :
      1. le flux est « verrouillé » sur un thème (ex. CERT-FR -> Sécurité)
      2. le thème qui marque le plus de points (mot dans le titre = 3 points,
         dans le texte = 1 point par occurrence, plafonné à 6)
      3. le thème par défaut du flux, puis celui de la rubrique, puis « Autres »
    """
    cfg = topics_cfg.get(category_name)
    if not cfg or not cfg.get("topics"):
        return None

    compiled = []
    for topic in cfg["topics"]:
        stem = compile_terms(topic.get("keywords"), stem=True)
        exact = compile_terms(topic.get("exact"), stem=False)
        if stem or exact:
            compiled.append((topic["name"], stem, exact))
    if not compiled:
        return None

    feed_rules = cfg.get("feeds", {})
    fallback = cfg.get("fallback", "Autres")

    def hits(stem, exact, text):
        return (len(stem.findall(text)) if stem else 0) + (len(exact.findall(text)) if exact else 0)

    def classify(source, title, body):
        rule = feed_rules.get(source)
        if isinstance(rule, str):
            return rule
        default = rule.get("default") if isinstance(rule, dict) else None

        best_name, best_score = None, 0
        for name, stem, exact in compiled:
            score = 3 * hits(stem, exact, title) + min(hits(stem, exact, body), 6)
            if score > best_score:
                best_name, best_score = name, score
        return best_name or default or fallback

    return classify


def section_topics(category_name, topics_cfg, articles, keep_empty=False):
    """Liste des sous-thèmes à afficher en pastilles : [{name, icon, count}]."""
    defined = (topics_cfg.get(category_name) or {}).get("topics", [])
    icons = {t["name"]: t.get("icon", "🏷️") for t in defined}
    counts = Counter(a["topic"] for a in articles if a["topic"])
    names = [t["name"] for t in defined if keep_empty or counts[t["name"]]]
    names += [n for n in counts if n not in icons]          # ex. « Autres », thèmes de flux
    return [{"name": n, "icon": icons.get(n, "🏷️"), "count": counts[n]} for n in names]


# --------------------------------------------------------------------------
# Fabrication d'un article (résumés + traduction)
# --------------------------------------------------------------------------

def translate_article(article, feed_cfg, target):
    """Traduit titre + résumés vers `target` si l'article n'est pas déjà dans cette langue."""
    if not target:
        return article
    lang = feed_cfg.get("lang") or translator.detect_lang(
        f"{article['title']}. {article['summary_long']}")
    article["lang"] = lang
    if lang in (target, "unknown"):
        return article

    long_parts = [p for p in article["summary_long"].split("\n\n") if p.strip()]
    parts = [article["title"], article["summary_short"]] + long_parts
    result = translator.translate_parts(parts, target)
    if not result or len(result) != len(parts):
        return article

    article["title_orig"] = article["title"]
    article["summary_short_orig"] = article["summary_short"]
    article["summary_long_orig"] = article["summary_long"]
    article["title"] = result[0] or article["title"]
    article["summary_short"] = result[1] or article["summary_short"]
    article["summary"] = article["summary_short"]
    article["summary_long"] = "\n\n".join(r for r in result[2:] if r.strip()) or article["summary_long"]
    article["translated"] = True
    return article


def make_article(feed_cfg, title, link, blurb, image, date, page, target_lang):
    if feed_cfg.get("summarize", False):
        page = page or fetch_article_full(link)
        image = image or page["image"]
        full_text = page["text"]
        source_text = full_text if len(full_text) > len(blurb) else blurb
        summary_short = summarize(source_text, max_sentences=2) or blurb
        summary_long = summarize_long(source_text, max_sentences=9) or blurb
    else:
        summary_short = blurb
        summary_long = blurb

    article = {
        "title": title,
        "link": link,
        "date": date,
        "summary": summary_short,        # champ conservé pour compatibilité
        "summary_short": summary_short,
        "summary_long": summary_long,
        "image": image,
        "source": feed_cfg["name"],
        "translated": False,
    }
    return translate_article(article, feed_cfg, target_lang)


def process_feed(feed_cfg, max_articles, seen_links, today_str, accept=None, target_lang=None):
    if feed_cfg.get("type") == "html":
        return process_html(feed_cfg, max_articles, seen_links, today_str, accept, target_lang)

    articles = []
    skipped = 0
    scanned = 0
    parsed, status = fetch_feed(feed_cfg["url"])

    if not parsed.entries:
        log(f"   ! Aucun article pour « {feed_cfg['name']} » ({status}). "
            f"Vérifie l'URL dans config.json : {feed_cfg['url']}")
        return articles

    for entry in parsed.entries:
        # on garde `max_articles` articles utiles, en regardant jusqu'à 4x plus
        # d'entrées pour compenser celles que le filtre écarte
        if len(articles) >= max_articles or scanned >= max_articles * 4:
            break
        scanned += 1

        link = entry.get("link", "")
        if not link or link in seen_links:
            continue

        title = entry.get("title", "(sans titre)")
        blurb = strip_html(entry.get("summary", ""))
        tags = " ".join(t.get("term", "") or "" for t in entry.get("tags", []) or [])

        if accept and not accept(title, f"{blurb} {tags}"):
            skipped += 1
            continue

        articles.append(make_article(
            feed_cfg, title, link, blurb, extract_image(entry),
            entry_date(entry, today_str), None, target_lang))
        seen_links.add(link)

    if skipped:
        log(f"   ({skipped} article(s) écarté(s) par le filtre)")
    return articles


def process_html(feed_cfg, max_articles, seen_links, today_str, accept, target_lang):
    links, status = fetch_listing(feed_cfg)
    if not links:
        log(f"   ! Aucun article pour « {feed_cfg['name']} » ({status}). URL : {feed_cfg['url']}")
        return []

    articles, skipped, scanned = [], 0, 0
    for link in links:
        if len(articles) >= max_articles or scanned >= max_articles * 3:
            break
        if link in seen_links or link in REJECTED:
            continue
        scanned += 1

        page = fetch_article_full(link)
        title = re.split(r"\s+[|–—]\s+", page["title"])[0].strip() if page["title"] else ""
        if not title:
            continue
        blurb = page["description"]

        if accept and not accept(title, blurb):
            REJECTED.add(link)
            skipped += 1
            continue

        articles.append(make_article(
            feed_cfg, title, link, blurb, page["image"],
            page["date"] or today_str, page, target_lang))
        seen_links.add(link)

    if skipped:
        log(f"   ({skipped} article(s) écarté(s) par le filtre)")
    return articles


# --------------------------------------------------------------------------
# Construction des rubriques pour le site
# --------------------------------------------------------------------------

def format_date(iso_date):
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return iso_date or ""


def split_paragraphs(text):
    return [p.strip() for p in (text or "").split("\n\n") if p.strip()]


def article_view(art, date, view_id):
    long_text = art.get("summary_long") or art.get("summary") or ""
    return {
        "id": view_id,
        "kind": "article",
        "title": art["title"],
        "link": art["link"],
        "source": art["source"],
        "date": date,
        "date_label": format_date(date),
        "image": art.get("image", ""),
        "summary_short": art.get("summary_short") or art.get("summary") or "",
        "paragraphs": split_paragraphs(long_text),
        "translated": bool(art.get("translated")),
        "title_orig": art.get("title_orig", ""),
        "paragraphs_orig": split_paragraphs(art.get("summary_long_orig", "")),
        "blocks": [],
        "exercises": [],
        "lesson_id": "",
        "level": "",
        "topic": "",
        "topic_icon": "",
    }


def lesson_view(lesson, number, view_id):
    return {
        "id": view_id,
        "kind": "lesson",
        "title": lesson["title"],
        "link": "",
        "source": f"{lesson.get('level', '')} · {lesson.get('topic', '')}".strip(" ·"),
        "date": "",
        "date_label": f"Leçon {number}",
        "image": "",
        "summary_short": lesson.get("summary", ""),
        "paragraphs": [],
        "translated": False,
        "title_orig": "",
        "paragraphs_orig": [],
        "blocks": lesson.get("blocks", []),
        "exercises": lesson.get("exercises", []),
        "lesson_id": lesson["id"],
        "level": lesson.get("level", ""),
        "topic": lesson.get("topic", ""),
        "topic_icon": "",
    }


def load_lessons():
    """Leçons : un fichier .json par leçon dans english/lessons/ (ordre alphabétique)."""
    lessons = []
    if os.path.isdir(LESSONS_DIR):
        for name in sorted(os.listdir(LESSONS_DIR)):
            if name.endswith(".json"):
                lesson = load_json(os.path.join(LESSONS_DIR, name), None)
                if lesson:
                    lessons.append(lesson)
    if not lessons:  # ancien format : toutes les leçons dans english/lessons.json
        lessons = load_json(LESSONS_PATH, {}).get("lessons", [])
    return lessons


def build_daily_pool(lessons):
    """
    Questions du jour : english/daily.json + tous les QCM des leçons,
    mélangés avec une graine fixe (même ordre à chaque génération).
    """
    pool, seen = [], set()

    def add(q, topic):
        key = (q["q"], tuple(q["options"]))
        if key in seen:
            return
        seen.add(key)
        pool.append({"q": q["q"], "options": q["options"], "answer": q["answer"],
                     "explain": q.get("explain", ""), "topic": topic})

    for q in load_json(DAILY_PATH, {}).get("questions", []):
        add(q, q.get("topic", "Culture générale"))
    for lesson in lessons:
        for ex in lesson.get("exercises", []):
            if ex.get("type") == "qcm":
                add(ex, lesson["title"])
    random.Random(2026).shuffle(pool)
    return pool


def build_sections(config, history):
    """
    Regroupe tous les articles de l'historique par rubrique (ordre du
    config.json), du plus récent au plus ancien, classe chaque article dans un
    sous-thème, puis ajoute la rubrique Anglais.
    Renvoie (sections, questions_du_jour).
    """
    topics_cfg = load_json(TOPICS_PATH, {})
    meta = {
        c["name"]: {"icon": c.get("icon", DEFAULT_ICON), "color": c.get("color", DEFAULT_COLOR)}
        for c in config["categories"]
    }
    order = [c["name"] for c in config["categories"]]
    buckets = {name: [] for name in order}
    # filtre « exclure » appliqué aussi à l'historique : les anciens articles
    # hors sujet disparaissent sans avoir à vider data/history.json
    exclusions = {c["name"]: make_filter(c, use_include=False) for c in config["categories"]}

    for day in history["days"]:
        for cat in day["categories"]:
            if cat["name"] not in buckets:
                buckets[cat["name"]] = []
                order.append(cat["name"])
            accept = exclusions.get(cat["name"])
            for art in cat["articles"]:
                if accept and not (accept(art.get("title_orig") or art["title"], "")
                                   and accept(art["title"], "")):
                    continue
                buckets[cat["name"]].append((art.get("date") or day["date"], art))

    sections = []
    counter = 0
    for sec_index, name in enumerate(order):
        items = sorted(buckets[name], key=lambda x: x[0], reverse=True)
        classify = build_topic_classifier(name, topics_cfg)
        icons = {t["name"]: t.get("icon", "🏷️") for t in (topics_cfg.get(name) or {}).get("topics", [])}
        articles = []
        for date, art in items:
            counter += 1
            view = article_view(art, date, f"a{counter}")
            if classify:
                title_text = f"{art['title']} {art.get('title_orig', '')}"
                body_text = " ".join([
                    art.get("summary_short", ""), art.get("summary_long", ""),
                    art.get("summary_short_orig", ""), art.get("summary_long_orig", ""),
                ])[:3000]
                view["topic"] = classify(art["source"], title_text, body_text)
                view["topic_icon"] = icons.get(view["topic"], "🏷️")
            articles.append(view)
        m = meta.get(name, {"icon": DEFAULT_ICON, "color": DEFAULT_COLOR})
        sections.append({
            "id": f"s{sec_index}", "name": name, "icon": m["icon"], "color": m["color"],
            "articles": articles, "is_english": False,
            "topics": section_topics(name, topics_cfg, articles),
        })

    # Rubrique Anglais (contenu fixe du dossier english/)
    daily = []
    lessons = load_lessons()
    if lessons and ENGLISH_NAME not in order:
        daily = build_daily_pool(lessons)
        icons = {t["name"]: t.get("icon", "🏷️") for t in (topics_cfg.get(ENGLISH_NAME) or {}).get("topics", [])}
        views = []
        for number, lesson in enumerate(lessons, start=1):
            counter += 1
            view = lesson_view(lesson, number, f"l{counter}")
            view["topic_icon"] = icons.get(view["topic"], "🏷️")
            views.append(view)
        sections.append({
            "id": f"s{len(sections)}", "name": ENGLISH_NAME, "icon": ENGLISH_ICON,
            "color": ENGLISH_COLOR, "articles": views, "is_english": True,
            "topics": section_topics(ENGLISH_NAME, topics_cfg, views),
        })
    return sections, daily


# --------------------------------------------------------------------------

def main():
    config = load_config()
    history = load_history()
    seen_links = set(history["seen_links"])
    REJECTED.update(history.get("rejected_links", []))

    target_lang = config.get("translate_to", "fr") or None
    if target_lang and not translator.available():
        log("! Traduction désactivée : installe-la avec  pip install deep-translator")
        target_lang = None

    today_str = datetime.now().strftime("%Y-%m-%d")
    categories_result = []
    total_new = 0

    for category in config["categories"]:
        cat_articles = []
        accept = make_filter(category)
        for feed_cfg in category["feeds"]:
            log(f"-> Récupération : {feed_cfg['name']}")
            new_articles = process_feed(
                feed_cfg, config.get("max_articles_per_feed", 6), seen_links,
                today_str, accept, target_lang)
            cat_articles.extend(new_articles)
            total_new += len(new_articles)
        if cat_articles:
            categories_result.append({"name": category["name"], "articles": cat_articles})

    translated = sum(1 for c in categories_result for a in c["articles"] if a.get("translated"))
    log(f"{total_new} nouvel(le)s article(s) trouvé(s), dont {translated} traduit(s) en français.")
    if target_lang and translator.stats()["fails"] >= translator.MAX_CONSECUTIVE_FAILS:
        log("! Le service de traduction ne répond plus : les derniers articles sont restés "
            "dans leur langue d'origine.")

    # Mise à jour de l'historique
    history["seen_links"] = list(seen_links)
    history["rejected_links"] = sorted(REJECTED)[-3000:]
    if categories_result:
        history["days"] = [d for d in history["days"] if d["date"] != today_str]
        history["days"].insert(0, {"date": today_str, "categories": categories_result})
        history["days"] = history["days"][:60]  # garde ~2 mois d'historique
    save_history(history)

    # Génération du site
    sections, daily = build_sections(config, history)
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("index.html.j2")
    html = template.render(
        site_title=config.get("site_title", "Ma Veille"),
        generated_at=datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M"),
        sections=sections,
        total=sum(len(s["articles"]) for s in sections),
        data={a["id"]: a for s in sections for a in s["articles"]},
        daily=daily,
    )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    static_dir = os.path.join(BASE_DIR, "static")  # manifest, service worker, icônes (appli iPhone)
    if os.path.isdir(static_dir):
        for name in os.listdir(static_dir):
            shutil.copy(os.path.join(static_dir, name), os.path.join(OUTPUT_DIR, name))
    out_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    log(f"Site généré : {out_path}")


if __name__ == "__main__":
    main()
