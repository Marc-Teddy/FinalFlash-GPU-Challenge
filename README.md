# CreditWise, prototype GPU Challenge 2026

CreditWise aide un établissement de crédit (banque, microfinance) à comprendre la situation d'un commerçant **avant** de lui accorder un crédit. La plateforme rassemble ses données financières, calcule les ratios, suit l'évolution mois par mois, signale les anomalies avec leur raison, puis prépare une synthèse explicable et un rapport PDF. **La décision reste à un analyste habilité.**

> Cas d'usage n° 5 du guide Epi'AI (« Évaluation du risque de crédit des petits commerçants »), construit à partir du *Guide fonctionnel et financier CreditWise*.

## Démarrage (2 minutes)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python ml/train_pd.py            # modèle PD sur données réelles (≈ 15 s CPU ; --device cuda sur GPU)
.venv/bin/python ml/export_model.py        # export JSON du modèle (lu en production avec numpy seul)
.venv/bin/python data/generate_demo.py      # fichiers des 3 commerçants fictifs (XLSX, CSV, PDF)
.venv/bin/uvicorn backend.app:app --port 8000   # la base de démo se crée seule au premier appel
```

Ouvrir <http://127.0.0.1:8000>. Fonctionne **hors ligne** (Chart.js et la police sont servis localement). Tests : `.venv/bin/python -m pytest tests`. Réinitialiser la démo : `.venv/bin/python -m backend.seed`.
`requirements.txt` contient uniquement ce qu'il faut en production ; `requirements-dev.txt` ajoute l'entraînement et les tests. Un `Dockerfile` est fourni (non testé sur cette machine).

### Comptes de démonstration

Sur les pages de connexion, rubrique « Comptes de démonstration » (accès direct, sans code).

| Identifiant | Profil | Situation |
|---|---|---|
| `analyste` | Établissement de crédit (microfinance fictive) | Reçoit les 3 dossiers partagés + 3 demandes de crédit |
| `akwaba` | Commerçante A : vêtements, Cotonou | Ventes stables et saisonnières, trésorerie positive, dette maîtrisée. 24 mois, export logiciel XLSX + grand livre |
| `solidite` | Commerçant B : quincaillerie, Porto-Novo | Baisse du CA pendant 10 mois, découvert croissant. États PDF d'un cabinet (extraction automatique) |
| `bonprix` | Commerçant C : alimentation, Parakou | Sans logiciel : balance + journal de caisse/mobile money avec doublons, montant inhabituel, date impossible, loyer oublié |
| `nouveau` | Commerçant sans données | Pour l'import en direct pendant la démo |

## Scénario de démo (≈ 90 s)

1. Compte **`nouveau`**, page *Documents* : déposer `data/demo/C/*.csv`. Le type de fichier est reconnu, les valeurs sont normalisées, et le tableau de bord affiche aussitôt les points à vérifier (doublons, écart grand livre / états).
2. Compte **`analyste`**, page *Dossiers* : trois profils, trois lectures différentes (scores ≈ 88 / 26 / 82 plafonné « à examiner »).
3. Ouvrir **B** : la baisse prolongée, la trésorerie négative et un DSCR de 0,07 avec le crédit. Puis le bouton **« Simuler « et si »** (montant/durée) recalcule la capacité de remboursement.
4. Onglet *Anomalies* de **C** : chaque alerte affiche sa raison et sa méthode.
5. Onglet *Décision* : saisir le motif (obligatoire), puis **Télécharger le rapport PDF** (décision incluse, accès tracé dans le journal du commerçant).

## Ce qui est construit

| Module (guide § 10) | Livré |
|---|---|
| Authentification et profils | Espaces commerçant / établissement de crédit, inscription et connexion par code e-mail à usage unique ou Google, acceptation des conditions horodatée |
| Gestion documentaire | Dépôt multi-fichiers PDF/XLSX/CSV, empreinte SHA-256, détection de document en double |
| Extraction | Tableaux « poste × mois », format long, balance générale (comptes type SYSCOHADA), grand livre, PDF texte (pdfplumber) |
| Normalisation | Format interne commun : période, source, date d'import, poste, montant, devise, statut (déclaré / extrait / vérifié / estimé), commentaire. Un libellé inconnu est signalé et **jamais additionné** |
| Moteur financier | 20 indicateurs du guide (croissance, marges, ROA, liquidité, FR, BFR, trésorerie nette, D/CP, poids des dettes, DSCR actuel et avec le crédit, délais) ; « non calculable » quand une donnée manque |
| Analyse temporelle | Mois / mois précédent / même mois N-1, trimestres complets uniquement, 12 mois glissants, annualisation signalée |
| Anomalies | Règles explicables + Z-score désaisonnalisé (|Z| ≥ 3) |
| Scoring | Formule du guide 25/20/20/20/15, seuils explicites, explications ; plafonnement si alerte de fiabilité |
| Modèle PD | XGBoost calibré sur **données réelles**, facteurs explicatifs par variable, EL = PD × LGD × EAD |
| Rapport | PDF d'analyse (formules, graphique, alertes, score, PD, limites, décision) |
| Partage sécurisé | Autorisation / retrait par le commerçant, journal des accès, dossier PDF avec données **signées HMAC-SHA256** (falsification détectée) et chiffrement AES-256 optionnel |

## Sécurité

* **Connexion sans mot de passe** : code à 6 chiffres envoyé par e-mail, valable 10 min, 5 essais au plus, 5 envois par adresse sur 15 min. Le code n'est jamais stocké : le navigateur reçoit un défi signé (HMAC) contenant son empreinte. Une adresse inconnue reçoit la même réponse qu'une adresse connue. Option « Continuer avec Google » : le jeton est vérifié auprès de Google (audience, émetteur, adresse vérifiée, expiration).
* **Session** : cookie signé `HttpOnly`, `SameSite=Strict`, `Secure` en production, expiré après 8 h. Comptes de démonstration : mot de passe haché (PBKDF2, 200 000 itérations), blocage 15 min après 5 échecs.
* **Données** : une institution ne voit un dossier que si le commerçant l'a autorisée (accès retirable), chaque consultation est journalisée. Le chemin des fichiers sur le serveur n'est jamais renvoyé.
* **Entrées** : formats, tailles (15 Mo, 10 fichiers par envoi), longueurs de texte et montants validés ; noms de fichiers assainis ; erreurs techniques journalisées côté serveur, message générique côté utilisateur.
* **Navigateur** : en-têtes CSP, `X-Frame-Options`, `nosniff` ; pas de documentation d'API publique ; toutes les valeurs affichées sont échappées.
* **Secrets** : la clé de signature (sessions, codes, dossiers) vient de `CREDITWISE_SECRET` ; en local, à défaut, une clé aléatoire est créée dans `data/.secret` (non versionnée). Sur Vercel la variable est obligatoire.
* **Hors périmètre prototype** : chiffrement de la base au repos, révocation d'une session avant son expiration.

## Déploiement sur Vercel

L'application tourne dans une fonction Python (`api/index.py`, configuration `vercel.json`). Le paquet de production pèse environ 166 Mo : le modèle est lu depuis `models/pd_model.json` avec numpy seul, sans xgboost, scikit-learn, scipy, pandas ni matplotlib.

```bash
npx vercel login                       # une fois, avec votre compte Vercel
npx vercel link                        # associe le dossier à un projet Vercel
openssl rand -hex 32 | npx vercel env add CREDITWISE_SECRET production
npx vercel --prod                      # déploie
```

Variables d'environnement :

| Variable | Rôle | Obligatoire |
|---|---|---|
| `CREDITWISE_SECRET` | Signature des sessions, des codes et des dossiers | Oui |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | Envoi des codes par e-mail (tout fournisseur SMTP) | Non : sans elles, le code s'affiche à l'écran (mode démonstration) |
| `CREDITWISE_DEMO_CODES` | `0` pour interdire l'affichage du code à l'écran | Non |
| `GOOGLE_CLIENT_ID` | Identifiant client OAuth (console Google Cloud, origine autorisée = l'adresse Vercel) pour afficher « Continuer avec Google » | Non |

**À savoir sur Vercel** : le disque n'est pas conservé. Chaque démarrage à froid recrée la base de démonstration dans `/tmp`. Les comptes créés et les fichiers importés en ligne disparaissent donc au bout d'un moment et ne sont pas partagés entre instances. C'est suffisant pour une démonstration ; pour un pilote, il faut une base hébergée (PostgreSQL) et un stockage de fichiers.

## Données : ce qui est réel, ce qui ne l'est pas

* **Réel** : le modèle de probabilité de défaut est entraîné sur le jeu public **UCI Polish Companies Bankruptcy** (Zięba, Tomczak & Tomczak, 2016, licence CC BY 4.0, `data/raw/polish/5year.arff`) : 5 910 entreprises, 410 faillites dans l'année. Seuls les 15 ratios que CreditWise sait recalculer pour un commerçant sont utilisés.
* **Fictif** : les trois commerçants de démonstration (générateur `data/generate_demo.py`, graine fixe, bilans équilibrés par construction). Aucune donnée réelle de commerçant béninois n'est publique.

### Résultats du modèle (jeu de test de 25 % mis de côté avant tout réglage)

| Variante | Modèle | ROC-AUC | PR-AUC | Brier |
|---|---|---|---|---|
| Avec croissance annuelle (≥ 24 mois) | Régression logistique (référence) | 0,833 | 0,379 | 0,052 |
| | **XGBoost (retenu)** | **0,885** | **0,586** | **0,042** |
| Sans croissance (< 24 mois d'historique) | Régression logistique (référence) | 0,837 | 0,367 | 0,054 |
| | **XGBoost (retenu)** | **0,880** | **0,436** | **0,050** |

Taux de base : 6,9 %. XGBoost n'est retenu que parce qu'il bat la référence. GPU : `python ml/train_pd.py --device cuda` ; le modèle tourne ensuite sans GPU.

## Limites (à dire au jury)

* Le modèle PD est appris sur des entreprises polonaises (2000-2013), pas sur des commerçants de l'UEMOA : sa PD est **indicative et relative**, pas une PD réglementaire.
* Le score à base de règles n'est pas un modèle prédictif ; ses seuils et pondérations sont illustratifs, à valider par l'équipe Finance.
* Une anomalie est un signal à vérifier, jamais une preuve de fraude.
* La définition du flux disponible du DSCR (EBE - impôt) est à valider avec Finance ; la LGD de 45 % est une hypothèse de travail.
* Isolation Forest a été testé puis écarté : sur ce volume, il ne séparait pas les opérations (scores quasi identiques).

## Après le Challenge

OCR des photos de reçus et des cahiers, connecteurs logiciels comptables, relevés mobile money, modèle entraîné sur de vrais historiques de remboursement d'une institution partenaire (pilote de 8 à 12 semaines, éventuellement via le LIF BCEAO), tests d'équité par groupe.

## Arborescence

```
backend/engine/  items.py (postes, normalisation) · extract.py · finance.py · anomalies.py · scoring.py · pd_runtime.py
backend/         app.py (API FastAPI) · otp.py (codes, Google) · db.py (SQLite) · services.py · reports.py (PDF) · seed.py
api/index.py     point d'entrée Vercel        vercel.json · .vercelignore · .python-version
ml/              train_pd.py (entraînement) · export_model.py (export JSON vérifié)
models/          pd_model.json (production) · pd_model.joblib (développement) · model_card.json
data/            generate_demo.py · demo/ (fichiers A, B, C) · raw/polish/ (données réelles UCI)
frontend/        interface monopage (HTML/CSS/JS, Chart.js et police locaux) · assets/ (logo)     tests/  pytest
```
