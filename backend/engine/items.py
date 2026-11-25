"""Format interne commun : postes standardisés et règles de normalisation.

Chaque valeur importée est rattachée à un poste interne. Les libellés et numéros de
compte (plan de comptes d'inspiration SYSCOHADA, aucune conformité n'est revendiquée)
sont associés aux postes ci-dessous. Un libellé non reconnu n'est JAMAIS additionné :
il est remonté à l'utilisateur comme « poste non reconnu ».
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# poste -> (libellé, nature)  nature: "flux" (sur une période) ou "stock" (à une date)
ITEMS: dict[str, tuple[str, str]] = {
    # Compte de résultat (flux)
    "ventes": ("Chiffre d'affaires (ventes)", "flux"),
    "autres_produits": ("Autres produits d'exploitation", "flux"),
    "cout_ventes": ("Coût d'achat des marchandises vendues", "flux"),
    "achats_marchandises": ("Achats de marchandises", "flux"),
    "variation_stocks": ("Variation des stocks de marchandises", "flux"),
    "transport": ("Transports", "flux"),
    "loyers": ("Loyers", "flux"),
    "autres_charges_externes": ("Autres charges externes", "flux"),
    "impots_taxes": ("Impôts et taxes", "flux"),
    "charges_personnel": ("Charges de personnel", "flux"),
    "dotations_amortissements": ("Dotations aux amortissements", "flux"),
    "charges_financieres": ("Charges financières (intérêts)", "flux"),
    "produits_financiers": ("Produits financiers", "flux"),
    "impot_resultat": ("Impôt sur le résultat", "flux"),
    "resultat_net": ("Résultat net déclaré", "flux"),
    "remboursement_emprunts": ("Remboursement du capital des emprunts", "flux"),
    # Bilan (stocks)
    "immobilisations": ("Immobilisations nettes", "stock"),
    "stocks": ("Stocks de marchandises", "stock"),
    "creances_clients": ("Créances clients", "stock"),
    "autres_creances": ("Autres créances", "stock"),
    "tresorerie": ("Trésorerie (caisse + banque)", "stock"),
    "capitaux_propres": ("Capitaux propres", "stock"),
    "dettes_financieres_lt": ("Emprunts et dettes financières à long terme", "stock"),
    "dettes_financieres_ct": ("Dettes financières à court terme / découverts", "stock"),
    "dettes_fournisseurs": ("Dettes fournisseurs", "stock"),
    "dettes_fiscales_sociales": ("Dettes fiscales et sociales", "stock"),
    "autres_dettes": ("Autres dettes", "stock"),
    "total_actif": ("Total actif déclaré", "stock"),
    "total_passif": ("Total passif déclaré", "stock"),
}

# Postes déclarés « de contrôle » : comparés au recalcul, jamais utilisés à sa place.
CONTROL_ITEMS = {"resultat_net", "total_actif", "total_passif"}

SYNONYMS: dict[str, list[str]] = {
    "ventes": ["chiffre d'affaires", "ca", "ventes", "ventes de marchandises", "chiffre affaires",
               "ventes de produits", "recettes des ventes", "revenue", "sales"],
    "autres_produits": ["autres produits", "autres produits d'exploitation", "subventions d'exploitation"],
    "cout_ventes": ["cout d'achat des marchandises vendues", "cout des marchandises vendues", "cmv",
                    "cout des ventes", "cout d'achat des ventes"],
    "achats_marchandises": ["achats de marchandises", "achats marchandises", "achats"],
    "variation_stocks": ["variation des stocks", "variation de stocks", "variation des stocks de marchandises"],
    "transport": ["transports", "transport", "frais de transport"],
    "loyers": ["loyers", "loyer", "locations", "loyers et charges locatives"],
    "autres_charges_externes": ["autres charges externes", "services exterieurs", "autres achats et charges externes",
                                "electricite et eau", "charges externes"],
    "impots_taxes": ["impots et taxes", "taxes", "patente"],
    "charges_personnel": ["charges de personnel", "salaires", "salaires et charges", "frais de personnel"],
    "dotations_amortissements": ["dotations aux amortissements", "amortissements", "dotations"],
    "charges_financieres": ["charges financieres", "interets", "frais financiers", "interets des emprunts"],
    "produits_financiers": ["produits financiers"],
    "impot_resultat": ["impot sur le resultat", "impot sur les benefices", "is", "bic"],
    "resultat_net": ["resultat net", "benefice net", "resultat de l'exercice", "resultat net de la periode"],
    "remboursement_emprunts": ["remboursement des emprunts", "remboursement emprunts",
                               "remboursement du capital", "remboursement du capital des emprunts"],
    "immobilisations": ["immobilisations", "immobilisations nettes", "actif immobilise", "materiel et equipements"],
    "stocks": ["stocks", "stock", "stocks de marchandises", "marchandises en stock"],
    "creances_clients": ["creances clients", "clients", "clients et comptes rattaches"],
    "autres_creances": ["autres creances", "debiteurs divers"],
    "tresorerie": ["tresorerie", "tresorerie actif", "caisse et banque", "disponibilites", "banque et caisse"],
    "capitaux_propres": ["capitaux propres", "fonds propres", "capital et reserves", "situation nette"],
    "dettes_financieres_lt": ["emprunts", "dettes financieres", "emprunts et dettes financieres",
                              "emprunts a long terme", "dettes financieres a long terme"],
    "dettes_financieres_ct": ["dettes financieres a court terme", "decouverts bancaires", "concours bancaires",
                              "tresorerie passif"],
    "dettes_fournisseurs": ["dettes fournisseurs", "fournisseurs", "fournisseurs et comptes rattaches"],
    "dettes_fiscales_sociales": ["dettes fiscales et sociales", "dettes fiscales", "dettes sociales"],
    "autres_dettes": ["autres dettes", "crediteurs divers"],
    "total_actif": ["total actif", "total de l'actif", "total bilan actif"],
    "total_passif": ["total passif", "total du passif", "total bilan passif"],
}

# Préfixes de comptes (le plus long préfixe l'emporte). Signe : +1 si le solde du compte
# s'ajoute au poste dans son sens naturel (débit pour les charges/actifs, crédit pour
# les produits/passifs).
ACCOUNT_PREFIXES: dict[str, str] = {
    "70": "ventes", "71": "autres_produits", "75": "autres_produits",
    "601": "achats_marchandises", "6031": "variation_stocks",
    "61": "transport", "622": "loyers", "62": "autres_charges_externes", "63": "autres_charges_externes",
    "605": "autres_charges_externes", "64": "impots_taxes", "66": "charges_personnel",
    "68": "dotations_amortissements", "67": "charges_financieres", "77": "produits_financiers",
    "89": "impot_resultat",
    "10": "capitaux_propres", "11": "capitaux_propres", "12": "capitaux_propres", "13": "capitaux_propres",
    "16": "dettes_financieres_lt", "2": "immobilisations", "3": "stocks", "41": "creances_clients",
    "40": "dettes_fournisseurs", "42": "dettes_fiscales_sociales", "43": "dettes_fiscales_sociales",
    "44": "dettes_fiscales_sociales", "47": "autres_dettes", "46": "autres_creances",
    "52": "tresorerie", "57": "tresorerie", "56": "dettes_financieres_ct",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def clean_label(s: str) -> str:
    s = strip_accents(str(s)).lower().replace("’", "'")
    s = re.sub(r"^[\s\-–•*]*(?:[a-z]{1,2}[.)]|\d{1,3}[.)\-–]?)\s*(?=[a-z])", "", s)  # « A. », « 1) »
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_LOOKUP = {clean_label(syn): item for item, syns in SYNONYMS.items() for syn in syns}
_LOOKUP.update({clean_label(lbl): item for item, (lbl, _) in ITEMS.items()})
_LOOKUP.update({item: item for item in ITEMS})


def match_label(label: str) -> tuple[str | None, float]:
    """Retourne (poste, confiance). Confiance 1.0 = correspondance exacte."""
    key = clean_label(label)
    if not key:
        return None, 0.0
    if key in _LOOKUP:
        return _LOOKUP[key], 1.0
    close = difflib.get_close_matches(key, list(_LOOKUP), n=1, cutoff=0.86)
    if close:
        ratio = difflib.SequenceMatcher(None, key, close[0]).ratio()
        return _LOOKUP[close[0]], round(ratio, 2)
    return None, 0.0


def match_account(account: str) -> str | None:
    acc = re.sub(r"\D", "", str(account))
    for n in range(len(acc), 0, -1):
        if acc[:n] in ACCOUNT_PREFIXES:
            return ACCOUNT_PREFIXES[acc[:n]]
    return None


def account_sign(account: str) -> int:
    """Sens naturel : classes 2,3,4(créances),5,6 au débit ; 1,4(dettes),7 au crédit."""
    acc = re.sub(r"\D", "", str(account))
    item = match_account(acc)
    credit_items = {"ventes", "autres_produits", "produits_financiers", "capitaux_propres",
                    "dettes_financieres_lt", "dettes_financieres_ct", "dettes_fournisseurs",
                    "dettes_fiscales_sociales", "autres_dettes"}
    return -1 if item in credit_items else 1
