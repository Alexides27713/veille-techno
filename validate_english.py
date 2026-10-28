"""Vérifie la cohérence des leçons et questions d'anglais (lance : python validate_english.py)."""
import glob, json, sys

errors = []
def err(where, msg): errors.append(f"{where}: {msg}")

def check_qcm(w, e):
    if not (2 <= len(e["options"]) <= 5): err(w, "nombre d'options")
    if len(set(e["options"])) != len(e["options"]): err(w, "options en double")
    if not (0 <= e["answer"] < len(e["options"])): err(w, "answer hors limites")
    if not e.get("explain"): err(w, "explication manquante")

ids, nq = set(), 0
files = sorted(glob.glob("english/lessons/*.json"))
for path in files:
    l = json.load(open(path, encoding="utf-8"))
    if l["id"] in ids: err(path, "id en double")
    ids.add(l["id"])
    for k in ("title", "level", "topic", "summary", "blocks", "exercises"):
        if not l.get(k): err(path, f"champ manquant : {k}")
    for i, e in enumerate(l["exercises"]):
        w = f"{path} ex#{i+1}"; nq += 1
        t = e.get("type")
        if t == "qcm": check_qcm(w, e)
        elif t == "fill":
            if "___" not in e["q"]: err(w, "fill sans ___")
            if not e.get("answers"): err(w, "pas de réponses")
        elif t == "order":
            if not e.get("words") or not e.get("answers"): err(w, "order incomplet")
            else:
                for a in e["answers"]:
                    if sorted(a.lower().replace("’","'").split()) != sorted(w2.lower() for w2 in e["words"]) \
                       and a is e["answers"][0]:
                        err(w, f"mots ≠ réponse : {a}")
        else: err(w, f"type inconnu {t}")
    if len(l["exercises"]) < 14: err(path, "moins de 14 exercices")
for i, q in enumerate(json.load(open("english/daily.json", encoding="utf-8"))["questions"]):
    check_qcm(f"daily#{i+1}", q)

print(f"{len(files)} leçons, {nq} exercices")
if errors:
    print("\n".join(errors)); sys.exit(1)
print("OK")
