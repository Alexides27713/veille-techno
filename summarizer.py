"""
Résumé extractif : on note chaque phrase selon la fréquence de ses mots
(hors mots vides FR/EN), puis on garde les meilleures phrases dans leur ordre
d'origine. Aucune dépendance externe, aucun téléchargement de modèle.

Le texte reste dans la langue de l'article (pas de traduction).
"""

import re
from collections import Counter

STOPWORDS = set("""
le la les de des du un une et en à au aux ce cet cette ces il elle ils elles
on nous vous je tu que qui quoi dont où pour par sur sous dans avec sans plus
moins très trop tout tous toute toutes est sont a ont été être avoir son sa
ses leur leurs mais ou donc or ni car ne pas se sa ça cela cet comme aussi
alors ainsi entre vers depuis pendant après avant selon
the a an of to in on for and or is are was were be been being this that
these those it its as at by from with without more less very too all any
have has had will would can could should may might not no so than then
""".split())

SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')
WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ']{3,}")


def summarize_sentences(text, max_sentences=3, min_chars=40):
    """Retourne la liste des `max_sentences` phrases les plus représentatives."""
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []

    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if len(s.strip()) >= min_chars]
    if len(sentences) <= max_sentences:
        return sentences

    words = [w.lower() for w in WORD_RE.findall(text) if w.lower() not in STOPWORDS]
    freq = Counter(words)
    if not freq:
        return sentences[:max_sentences]

    max_freq = max(freq.values())
    for w in freq:
        freq[w] /= max_freq

    scores = []
    for i, sentence in enumerate(sentences):
        sent_words = [w.lower() for w in WORD_RE.findall(sentence)]
        score = (sum(freq.get(w, 0) for w in sent_words) / len(sent_words)) if sent_words else 0
        # petit bonus aux premières phrases (souvent les plus informatives)
        position_bonus = 0.15 if i < 2 else 0
        scores.append((score + position_bonus, i, sentence))

    best = sorted(scores, key=lambda x: x[0], reverse=True)[:max_sentences]
    return [s for _, _, s in sorted(best, key=lambda x: x[1])]


def summarize(text, max_sentences=3):
    """Résumé court : phrases retenues, collées en un seul bloc."""
    return " ".join(summarize_sentences(text, max_sentences))


def summarize_long(text, max_sentences=9, per_paragraph=3):
    """
    Résumé détaillé : plus de phrases, regroupées en paragraphes de
    `per_paragraph` phrases (séparés par une ligne vide).
    """
    sentences = summarize_sentences(text, max_sentences)
    paragraphs = [
        " ".join(sentences[i:i + per_paragraph])
        for i in range(0, len(sentences), per_paragraph)
    ]
    return "\n\n".join(paragraphs)
