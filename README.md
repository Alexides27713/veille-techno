# Ma Veille — site de veille personnel

Un script qui récupère les actus de tes centres d'intérêt, les résume, traduit
en français ce qui est en anglais, et génère un site HTML statique à ouvrir
dans ton navigateur. Il contient aussi une rubrique **Anglais** (cours,
exercices, question du jour).

## Installation (Windows / PowerShell)

```powershell
cd C:\Projets\veille-tech
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Utilisation

```powershell
python fetch_and_summarize.py
start output\index.html
```

La première exécution est plus longue (téléchargement, résumé et traduction de
chaque article). Les suivantes ne traitent que les nouveaux articles.

## Le site

- **Menu burger** : une rubrique par thème, avec le nombre d'éléments.
- **Cartes** : clic = résumé détaillé dans une fenêtre (pas de redirection).
- **Articles traduits** : bouton « Voir l'original » dans la fenêtre.
- **Sous-thèmes** : dans chaque rubrique, des pastilles filtrent les cartes
  (ex. Informatique & Sécurité → Sécurité, Actu tech, Hardware, Software, Réseaux & Infra).
- **Rubrique Anglais** : 24 leçons longues (~15 exercices chacune : QCM, texte à
  trous, phrases à remettre dans l'ordre), ta meilleure note est gardée dans le
  navigateur, et **3 questions du jour** (bouton « Encore 3 questions » pour t'entraîner davantage).

## Sous-thèmes : topics.json

Le classement est automatique, à partir de mots-clés dans le titre et le résumé.
Dans `topics.json` tu peux :
- ajouter ou renommer un sous-thème et ses mots-clés (`keywords`),
- forcer un flux dans un sous-thème (ex. CERT-FR → Sécurité),
- choisir le sous-thème par défaut quand rien ne correspond (`fallback`).
Le classement se fait à chaque génération : pas besoin de vider l'historique.

## Personnaliser : config.json

```json
{"name": "Futura-Espace", "url": "https://.../actualites.xml", "summarize": true}
```

- `summarize: true` : lit l'article complet pour en faire un résumé court + détaillé.
- `summarize: false` : affiche seulement le texte fourni par le flux.
- `"translate_to": "fr"` (en haut du fichier) : langue de traduction.
  Mets `""` pour désactiver la traduction.
- `"lang": "en"` (optionnel, sur un flux) : force la langue d'une source si la
  détection automatique se trompe.

### Sites sans flux RSS

Ajoute `"type": "html"` : le script lit la page de liste et suit les liens.
`link_contains` limite aux vrais articles :

```json
{"name": "PhotoActus", "type": "html", "url": "https://www.photoactus.com/actualites",
 "link_contains": "/post/", "summarize": true}
```

### Filtrer les articles hors sujet

Dans une rubrique, `"filters"` avec `include_any` (l'article doit parler de
l'un de ces mots) et `exclude_any` (rejeté si l'un de ces mots est dans le titre).

### Quand une source est en erreur

Le script affiche la raison : `HTTP 404` (mauvaise URL), `HTTP 403` (le site
bloque les robots : choisis une autre source), `contenu illisible` (ce n'est pas
un flux : essaie le mode `html`).

## Modifier les cours d'anglais

Tout est dans le dossier `english/` :
- `lessons/` : **un fichier par leçon** (`01-be-have.json`, …), classées par ordre
  alphabétique. Blocs de cours (`h`, `p`, `list`, `table`, `ex`, `tip`) et exercices
  `qcm`, `fill` (texte à trous) ou `order` (remettre les mots dans l'ordre).
- `daily.json` : les questions du jour (les QCM des leçons s'y ajoutent aussi)

Pour ajouter une leçon : copie un fichier existant, change l'`id` et le contenu.
Vérifie ensuite avec `python validate_english.py`.

## Automatiser (Planificateur de tâches Windows)

Action « Démarrer un programme » :
- Programme : `C:\Projets\veille-tech\venv\Scripts\python.exe`
- Arguments : `fetch_and_summarize.py`
- Démarrer dans : `C:\Projets\veille-tech`

## Limites

- Le résumé est **extractif** : il sélectionne les phrases clés de l'article,
  il ne reformule pas.
- La traduction passe par le service web public de Google Traduction (via la
  bibliothèque `deep-translator`, sans clé API). Les textes envoyés sont des
  résumés d'articles publics. Si le service ne répond pas, le script continue et
  les articles restent dans leur langue d'origine. La qualité est celle d'une
  traduction automatique.
- Certains sites bloquent la lecture de la page complète ; le résumé retombe
  alors sur le texte du flux et reste court.
- Pour regénérer les anciens articles avec traduction et résumés détaillés,
  supprime `data\history.json` avant de relancer.

## Application iPhone (PWA)

Le site s'installe sur l'écran d'accueil comme une vraie appli (plein écran, icône,
hors ligne). Il doit pour cela être **en ligne en HTTPS**.

1. Mets le dossier dans un dépôt GitHub (le workflow `.github/workflows/veille.yml`
   régénère le site tous les jours et le publie sur GitHub Pages).
2. Dépôt → Settings → Pages → Source : **GitHub Actions**. Lance le workflow une fois
   (Actions → Veille quotidienne → Run workflow).
3. Sur l'iPhone, ouvre l'adresse `https://<ton-compte>.github.io/<dépôt>/` dans **Safari**,
   puis Partager → **Sur l'écran d'accueil**.

Ta progression en anglais est enregistrée sur l'iPhone (elle n'est pas partagée avec le PC).
Attention : GitHub Pages est public, donc l'adresse est accessible à qui la connaît.
