"""
Traduction automatique des résumés vers le français.

Utilise la bibliothèque `deep-translator` (pas de clé API) qui interroge le
service web public de Google Traduction. Si la bibliothèque n'est pas
installée ou si le service ne répond pas, le script continue sans traduire :
les articles restent simplement dans leur langue d'origine.
"""

import re
import time

try:
    from deep_translator import GoogleTranslator
except Exception:  # bibliothèque absente
    GoogleTranslator = None

MAX_CHARS = 4500          # limite du service : ~5000 caractères par requête
MAX_CONSECUTIVE_FAILS = 3  # après 3 échecs d'affilée, on arrête d'essayer

_state = {"fails": 0, "ok": 0}

_FR = set("le la les des une est sont dans pour que qui pas sur avec cette plus mais "
          "comme aussi nous vous ils elles ont été être très par ces ses leur aux du et".split())
_EN = set("the and of to is are was were that for with this from have has not but they "
          "which their will can been more about it at by be or".split())


def available():
    return GoogleTranslator is not None


def stats():
    return dict(_state)


def detect_lang(text):
    """Renvoie 'fr', 'en' ou 'unknown' d'après les mots courants du texte."""
    tokens = re.findall(r"[a-zà-ÿ']+", (text or "").lower()[:3000])
    fr = sum(1 for t in tokens if t in _FR)
    en = sum(1 for t in tokens if t in _EN)
    if fr + en < 3:
        return "unknown"
    return "fr" if fr > en else "en"


def _call(translator, text, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            out = translator.translate(text)
            if out:
                return out
        except Exception as exc:  # réseau, limite de débit...
            last = exc
        time.sleep(1.0 * (attempt + 1))
    raise last or RuntimeError("traduction vide")


def translate_parts(parts, target="fr"):
    """
    Traduit une liste de textes. Renvoie une liste de même longueur,
    ou None si la traduction est impossible.
    Une seule requête quand c'est possible (plus rapide, moins de risques de
    limite de débit) ; sinon morceau par morceau.
    """
    if GoogleTranslator is None or _state["fails"] >= MAX_CONSECUTIVE_FAILS:
        return None

    translator = GoogleTranslator(source="auto", target=target)
    try:
        joined = "\n\n".join(parts)
        if len(joined) <= MAX_CHARS and all(p.strip() for p in parts):
            out = _call(translator, joined)
            pieces = [p.strip() for p in re.split(r"\n\s*\n", out.strip())]
            if len(pieces) == len(parts):
                _state["fails"] = 0
                _state["ok"] += 1
                return pieces

        result = []
        for part in parts:
            result.append(_call(translator, part[:MAX_CHARS]).strip() if part.strip() else "")
            time.sleep(0.2)
        _state["fails"] = 0
        _state["ok"] += 1
        return result
    except Exception:
        _state["fails"] += 1
        return None
