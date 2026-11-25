# CreditWise — prototype GPU Challenge 2026

CreditWise aide une institution financière (banque, microfinance) à comprendre la situation d'un commerçant **avant** de lui accorder un crédit. La plateforme rassemble ses données financières, calcule les ratios, suit l'évolution mois par mois, signale les anomalies avec leur raison, puis prépare une synthèse explicable et un rapport PDF. **La décision reste à un analyste habilité.**

> Cas d'usage n° 5 du guide Epi'AI (« Évaluation du risque de crédit des petits commerçants »), construit à partir du *Guide fonctionnel et financier CreditWise*.

## Démarrage (2 minutes)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python ml/train_pd.py            # modèle PD sur données réelles (≈ 15 s CPU ; --device cuda sur GPU)
.venv/bin/python data/generate_demo.py      # fichiers des 3 commerçants fictifs (XLSX, CSV, PDF)
.venv/bin/python -m backend.seed            # base de démo : les fichiers passent par le vrai pipeline d'import
.venv/bin/uvicorn backend.app:app --port 8000
```

Ouvrir <http://127.0.0.1:8000>. Fonctionne **hors ligne** (Chart.js est servi localement). Tests : `.venv/bin/python -m pytest tests`.
Un `Dockerfile` est fourni (non testé sur cette machine).

### Comptes de démonstration (mot de passe `demo`)

| Identifiant | Profil | Situation |
|---|---|---|
| `analyste` | Institution financière (microfinance fictive) | Reçoit les 3 dossiers partagés + 3 demandes de crédit |
| `akwaba` | Commerçante A — vêtements, Cotonou | Ventes stables et saisonnières, trésorerie positive, dette maîtrisée. 24 mois, export logiciel XLSX + grand livre |
| `solidite` | Commerçant B — quincaillerie, Porto-Novo | Baisse du CA pendant 10 mois, découvert croissant. États PDF d'un cabinet (extraction automatique) |
| `bonprix` | Commerçant C — alimentation, Parakou | Sans logiciel : balance + journal de caisse/mobile money avec doublons, montant inhabituel, date impossible, loyer oublié |
| `nouveau` | Commerçant sans données | Pour l'import en direct pendant la démo |

## Scénario de démo (≈ 90 s)

1. **`nouveau`** → *Documents* : déposer `data/demo/C/*.csv`. Le type de fichier est reconnu, les valeurs sont normalisées, et le tableau de bord affiche aussitôt les points à vérifier (doublons, écart grand livre / états).
2. **`analyste`** → *Dossiers* : trois profils, trois lectures différentes (scores ≈ 88 / 26 / 82 plafonné « à examiner »).
3. Ouvrir **B** : la baisse prolongée, la trésorerie négative et un DSCR de 0,07 avec le crédit. Puis le bouton **« Simuler « et si »** (montant/durée) recalcule la capacité de remboursement.
4. Onglet *Anomalies* de **C** : chaque alerte affiche sa raison et sa méthode.
5. *Décision* : motif obligatoire → **Télécharger le rapport PDF** (décision incluse, accès tracé dans le journal du commerçant).

## Ce qui est construit

| Module (guide § 10) | Livré |
|---|---|
| Authentification et profils | Espaces commerçant / institution, sessions, mots de passe PBKDF2 |
| Gestion documentaire | Dépôt multi-fichiers PDF/XLSX/CSV, empreinte SHA-256, détection de document en double |
| Extraction | Tableaux « poste × mois », format long, balance générale (comptes type SYSCOHADA), grand livre, PDF texte (pdfplumber) |
| Normalisation | Format interne commun : période, source, date d'import, poste, montant, devise, statut (déclaré / extrait / vérifié / estimé), commentaire. Libellé inconnu → signalé, **jamais additionné** |
| Moteur financier | 20 indicateurs du guide (croissance, marges, ROA, liquidité, FR, BFR, trésorerie nette, D/CP, poids des dettes, DSCR actuel et avec le crédit, délais) ; « non calculable » quand une donnée manque |
| Analyse temporelle | Mois / mois précédent / même mois N-1, trimestres complets uniquement, 12 mois glissants, annualisation signalée |
| Anomalies | Règles explicables + Z-score désaisonnalisé (|Z| ≥ 3) |
| Scoring | Formule du guide 25/20/20/20/15, seuils explicites, explications ; plafonnement si alerte de fiabilité |
| Modèle PD | XGBoost calibré sur **données réelles**, facteurs TreeSHAP, EL = PD × LGD × EAD |
| Rapport | PDF d'analyse (formules, graphique, alertes, score, PD, limites, décision) |
| Partage sécurisé | Autorisation / retrait par le commerçant, journal des accès, dossier PDF avec données **signées HMAC-SHA256** (falsification détectée) et chiffrement AES-256 optionnel |

## Données : ce qui est réel, ce qui ne l'est pas

* **Réel** : le modèle de probabilité de défaut est entraîné sur le jeu public **UCI Polish Companies Bankruptcy** (Zięba, Tomczak & Tomczak, 2016 — licence CC BY 4.0, `data/raw/polish/5year.arff`) : 5 910 entreprises, 410 faillites dans l'année. Seuls les 15 ratios que CreditWise sait recalculer pour un commerçant sont utilisés.
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
* La définition du flux disponible du DSCR (EBE – impôt) est à valider avec Finance ; la LGD de 45 % est une hypothèse de travail.
* Isolation Forest a été testé puis écarté : sur ce volume, il ne séparait pas les opérations (scores quasi identiques).

## Après le Challenge

OCR des photos de reçus et des cahiers, connecteurs logiciels comptables, relevés mobile money, modèle entraîné sur de vrais historiques de remboursement d'une institution partenaire (pilote de 8 à 12 semaines, éventuellement via le LIF BCEAO), tests d'équité par groupe.

## Arborescence

```
backend/engine/  items.py (postes, normalisation) · extract.py · finance.py · anomalies.py · scoring.py
backend/         app.py (API FastAPI) · db.py (SQLite) · services.py · reports.py (PDF) · seed.py
ml/train_pd.py   entraînement du modèle PD     models/  modèle + fiche du modèle (model_card.json)
data/            generate_demo.py · demo/ (fichiers A, B, C) · raw/polish/ (données réelles UCI)
frontend/        interface monopage (HTML/CSS/JS, Chart.js local)     tests/  pytest
```
