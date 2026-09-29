# -*- coding: utf-8 -*-
"""
AtlasAir Analytics : tableau de bord du trafic aérien du Maroc.

Compare les passagers aériens transportés par le Maroc avec l'Algérie, la Tunisie,
l'Égypte, la France et l'Espagne (OACI via Banque mondiale, traité par Our World in Data).

Organisation du fichier :
  1. Constantes et configuration          5. Composants HTML (logo, icônes, cartes)
  2. Authentification (SHA-256)           6. Callbacks (saisie, import, reset)
  3. Données : chargement / validation    7. Pages : connexion et application
  4. Indicateurs et graphiques
"""
from __future__ import annotations

import hashlib
import hmac
import html
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # rendu sans interface graphique (serveur)
import numpy as np
import pandas as pd
import seaborn as sns
import streamlit as st
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

# ════════════════════════════════════════════════════════════════════════════
# 1. CONSTANTES ET CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════
APP_NAME = "AtlasAir Analytics"
DATA_PATH = Path(__file__).parent / "data" / "dataset.csv"
SOURCE = "Source : OACI via Banque mondiale, traité par Our World in Data"

PAYS = ["Maroc", "Algérie", "Tunisie", "Égypte", "France", "Espagne"]
EN_TO_FR = {"Morocco": "Maroc", "Algeria": "Algérie", "Tunisia": "Tunisie",
            "Egypt": "Égypte", "France": "France", "Spain": "Espagne"}

# Une couleur fixe par pays, identique dans tous les graphiques
COULEURS = {"Maroc": "#FF3D54", "Algérie": "#7BD35B", "Tunisie": "#FF9F1C",
            "Égypte": "#2EC4B6", "France": "#4DA8FF", "Espagne": "#C77DFF"}

ORIGINE_BASE = "OWID / OACI"
ANNEE_SAISIE_MIN, ANNEE_SAISIE_MAX = 1950, 2100
PASSAGERS_MAX = 1_000_000_000          # plafond de vraisemblance pour la saisie
MAX_ECHECS = 5                         # tentatives de connexion par session

# Compte de démonstration (utilisé seulement si aucun secret n'est configuré)
DEMO_USER = "demo"
DEMO_HASH = "43c27b4e263fa191a6a7ec198cd4d5b47d17413c49d77dc533a01720707e3202"  # SHA-256("demo2026")

# Thème des graphiques Matplotlib / Seaborn (bleu nuit)
BG, FG, MUTED, GRID = "#0E1837", "#DCE6FF", "#93A3CC", "#25325C"
RC_SOMBRE = {
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": FG, "axes.labelcolor": FG, "axes.edgecolor": GRID,
    "axes.titlecolor": FG, "xtick.color": MUTED, "ytick.color": MUTED,
    "grid.color": GRID, "grid.linewidth": 0.7, "axes.grid": True,
    "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "legend.labelcolor": FG, "font.size": 10,
}
sns.set_theme(style="ticks", rc=RC_SOMBRE)


# ════════════════════════════════════════════════════════════════════════════
# 2. AUTHENTIFICATION (hash SHA-256, comptes dans st.secrets, repli démo)
# ════════════════════════════════════════════════════════════════════════════
def sha256_hex(texte: str) -> str:
    """Empreinte SHA-256 hexadécimale d'un texte."""
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def charger_utilisateurs() -> tuple[dict[str, str], str, bool]:
    """Retourne (comptes {identifiant: hash}, sel, mode_demo).

    Les comptes viennent de st.secrets ([users] et [auth].salt). Sans secrets
    configurés, on bascule sur le compte de démonstration."""
    try:
        users = {str(k).lower(): str(v) for k, v in dict(st.secrets["users"]).items()}
        salt = str(st.secrets["auth"]["salt"]) if "auth" in st.secrets else ""
        if users:
            return users, salt, False
    except Exception:
        pass
    return {DEMO_USER: DEMO_HASH}, "", True


def verifier_identifiants(identifiant: str, mot_de_passe: str) -> bool:
    """Compare les empreintes en temps constant (le hash est calculé même si le compte n'existe pas)."""
    users, salt, _ = charger_utilisateurs()
    identifiant = identifiant.strip().lower()
    attendu = users.get(identifiant, "0" * 64).lower()
    calcule = sha256_hex(salt + mot_de_passe)
    return hmac.compare_digest(calcule, attendu) and identifiant in users


# ════════════════════════════════════════════════════════════════════════════
# 3. DONNÉES : CHARGEMENT, VALIDATION, TABLEAU ANNÉES x PAYS
# ════════════════════════════════════════════════════════════════════════════
def normaliser(brut: pd.DataFrame, origine: str) -> tuple[pd.DataFrame, dict]:
    """Convertit un CSV (format OWID ou format français) en tableau propre
    [Pays, Année, Passagers, Origine]. Les lignes invalides sont écartées et comptées ;
    aucune valeur n'est jamais inventée ni interpolée."""
    brut = brut.rename(columns=lambda c: str(c).strip())
    if {"Entity", "Year"}.issubset(brut.columns):                    # format OWID
        exclus = {"Entity", "Code", "Year", "World region according to OWID"}
        colonnes_valeur = [c for c in brut.columns if c not in exclus]
        if not colonnes_valeur:
            raise ValueError("Colonne de passagers introuvable dans le fichier OWID.")
        d = brut[["Entity", "Year", colonnes_valeur[0]]].copy()
        d.columns = ["Pays", "Année", "Passagers"]
    elif {"Pays", "Année", "Passagers"}.issubset(brut.columns):     # format français
        d = brut[["Pays", "Année", "Passagers"]].copy()
    else:
        raise ValueError("Colonnes attendues : Entity, Year, <passagers>  ou  Pays, Année, Passagers.")

    rapport = {"lignes": len(d)}
    d["Pays"] = d["Pays"].astype(str).str.strip().map(lambda x: EN_TO_FR.get(x, x))
    hors = ~d["Pays"].isin(PAYS)
    rapport["hors_perimetre"] = int(hors.sum())
    d = d[~hors].copy()

    d["Année"] = pd.to_numeric(d["Année"], errors="coerce")
    d["Passagers"] = pd.to_numeric(d["Passagers"], errors="coerce")
    valide = (d["Année"].between(1900, 2100) & (d["Année"] % 1 == 0)
              & d["Passagers"].notna() & (d["Passagers"] > 0))
    rapport["invalides"] = int((~valide).sum())
    d = d[valide].copy()

    d["Année"] = d["Année"].astype(int)
    d["Passagers"] = d["Passagers"].astype(float)
    avant = len(d)
    d = d.drop_duplicates(["Pays", "Année"], keep="last")
    rapport["doublons"] = avant - len(d)
    d["Origine"] = origine
    return d.sort_values(["Pays", "Année"]).reset_index(drop=True), rapport


@st.cache_data(show_spinner=False)
def charger_base(chemin: str) -> pd.DataFrame:
    """Charge le jeu de données d'origine (mis en cache)."""
    df, _ = normaliser(pd.read_csv(chemin), ORIGINE_BASE)
    return df


def lire_csv(fichier) -> pd.DataFrame:
    """Lit un CSV importé en essayant les séparateurs courants (, ; tabulation)."""
    for sep in (",", ";", "\t"):
        fichier.seek(0)
        try:
            d = pd.read_csv(fichier, sep=sep, encoding="utf-8-sig")
        except Exception:
            continue
        if d.shape[1] >= 3:
            return d
    raise ValueError("Fichier illisible : vérifiez qu'il s'agit d'un CSV avec au moins 3 colonnes.")


@st.cache_data(show_spinner=False)
def tableau_annuel(df: pd.DataFrame) -> pd.DataFrame:
    """Tableau Année x Pays (grille complète : les années absentes restent NaN)."""
    p = df.pivot(index="Année", columns="Pays", values="Passagers")
    p = p.reindex(index=range(int(p.index.min()), int(p.index.max()) + 1), columns=PAYS)
    p.index.name = "Année"
    return p


def manquants(p: pd.DataFrame, sel: list[str], a0: int, a1: int) -> list[tuple[str, int]]:
    """Liste des couples (pays, année) sans valeur dans la sélection courante."""
    sub = p.loc[a0:a1, sel]
    return [(sub.columns[j], int(sub.index[i])) for i, j in np.argwhere(sub.isna().to_numpy())]


# ════════════════════════════════════════════════════════════════════════════
# 4. INDICATEURS ET GRAPHIQUES
# ════════════════════════════════════════════════════════════════════════════
def fmt(x, d: int = 1, signe: bool = False, suffixe: str = "") -> str:
    """Format français : espace fine pour les milliers, virgule décimale, « n/d » si vide."""
    if x is None or pd.isna(x):
        return "n/d"
    s = f"{x:+,.{d}f}" if signe else f"{x:,.{d}f}"
    s = s.replace(",", "\u202f").replace(".", ",").replace("-", "\u2212")
    return s + suffixe.replace(" ", "\u00a0")


def ordinal(n: int) -> str:
    return "1er" if n == 1 else f"{n}e"


def val(p: pd.DataFrame, annee: int, pays: str) -> float:
    """Valeur du tableau, NaN si l'année n'existe pas."""
    try:
        return p.at[annee, pays]
    except KeyError:
        return np.nan


def croissance(p: pd.DataFrame) -> pd.DataFrame:
    """Taux de croissance annuel (%) ; NaN si l'une des deux années manque."""
    return p.pct_change(fill_method=None) * 100


def tcam(p: pd.DataFrame, pays: str, a0: int, a1: int) -> float:
    """Taux de croissance annuel moyen (%) entre deux années."""
    v0, v1 = val(p, a0, pays), val(p, a1, pays)
    if a1 <= a0 or pd.isna(v0) or pd.isna(v1) or v0 <= 0:
        return np.nan
    return ((v1 / v0) ** (1 / (a1 - a0)) - 1) * 100


def rang_pays(p: pd.DataFrame, sel: list[str], annee: int, pays: str = "Maroc"):
    """Rang du pays parmi la sélection ; None si une valeur manque cette année-là."""
    s = p.loc[annee, sel]
    return None if s.isna().any() else int(s.rank(ascending=False)[pays])


def calculer_kpi(p, sel, a0, a1, ref) -> dict:
    """Les 6 indicateurs clés du Maroc pour l'année de référence."""
    v, prev = val(p, ref, "Maroc"), val(p, ref - 1, "Maroc")
    total = p.loc[ref, sel].sum(skipna=False)
    v19 = val(p, 2019, "Maroc")
    return {
        "passagers": v,
        "variation": (v / prev - 1) * 100 if pd.notna(v) and pd.notna(prev) and prev > 0 else np.nan,
        "rang": rang_pays(p, sel, ref) if pd.notna(v) else None,
        "part": v / total * 100 if pd.notna(v) and pd.notna(total) and total > 0 else np.nan,
        "tcam": tcam(p, "Maroc", a0, a1),
        "reprise": (v / v19 - 1) * 100 if ref >= 2020 and pd.notna(v) and pd.notna(v19) else np.nan,
    }


def tableau_comparatif(p, sel, a0, a1, ref) -> pd.DataFrame:
    """Une ligne par pays : trafic, croissance, part, TCAM et niveau par rapport à 2019."""
    total = p.loc[ref, sel].sum(skipna=False)
    lignes = []
    for c in sel:
        v, prev, v19 = val(p, ref, c), val(p, ref - 1, c), val(p, 2019, c)
        lignes.append({
            "Pays": c,
            "Passagers (M)": v / 1e6 if pd.notna(v) else np.nan,
            "Variation annuelle (%)": (v / prev - 1) * 100 if pd.notna(v) and pd.notna(prev) and prev > 0 else np.nan,
            "Part du groupe (%)": v / total * 100 if pd.notna(v) and pd.notna(total) and total > 0 else np.nan,
            f"TCAM {a0}–{a1} (%)": tcam(p, c, a0, a1),
            "Écart vs 2019 (%)": (v / v19 - 1) * 100 if ref >= 2020 and pd.notna(v) and pd.notna(v19) else np.nan,
        })
    return pd.DataFrame(lignes).set_index("Pays")


def generer_insights(p, sel, a0, a1, ref, kpi) -> list[str]:
    """Phrases d'analyse générées à partir des chiffres (HTML léger : <b> uniquement)."""
    out: list[str] = []
    v = kpi["passagers"]
    if pd.isna(v):
        return [f"Aucune donnée pour le Maroc en <b>{ref}</b> : choisissez une autre année de référence."]

    serie = p.loc[ref, sel]
    if kpi["rang"] is not None:
        tete = serie.idxmax()
        fin = (f"le Maroc est en tête du groupe." if tete == "Maroc" else
               f"{tete} est en tête avec <b>{fmt(serie[tete] / 1e6, 1)}&nbsp;M</b>.")
        out.append(f"En {ref}, le Maroc a transporté <b>{fmt(v / 1e6, 2)}&nbsp;M</b> de passagers, "
                   f"au <b>{ordinal(kpi['rang'])} rang sur {len(sel)}</b> ; {fin}")
    else:
        out.append(f"En {ref}, le Maroc a transporté <b>{fmt(v / 1e6, 2)}&nbsp;M</b> de passagers "
                   f"(classement impossible : des valeurs manquent pour certains pays).")

    if pd.notna(kpi["variation"]):
        sens = "progressé" if kpi["variation"] >= 0 else "reculé"
        out.append(f"Le trafic a {sens} de <b>{fmt(abs(kpi['variation']), 1)}&nbsp;%</b> par rapport à {ref - 1}.")

    if pd.notna(kpi["part"]):
        ancienne = ""
        if ref - 10 >= p.index.min():
            tot10 = p.loc[ref - 10, sel].sum(skipna=False)
            v10 = val(p, ref - 10, "Maroc")
            if pd.notna(tot10) and pd.notna(v10) and tot10 > 0:
                ancienne = f" (contre <b>{fmt(v10 / tot10 * 100, 1)}&nbsp;%</b> en {ref - 10})"
        out.append(f"Le Maroc représente <b>{fmt(kpi['part'], 1)}&nbsp;%</b> du trafic cumulé "
                   f"des {len(sel)} pays{ancienne}.")

    tc = pd.Series({c: tcam(p, c, a0, a1) for c in sel}).dropna()
    if "Maroc" in tc.index and len(tc) > 1:
        r = int(tc.rank(ascending=False)["Maroc"])
        meilleur = tc.idxmax()
        suite = "" if meilleur == "Maroc" else f" ; le plus rapide est {meilleur} (<b>{fmt(tc[meilleur], 2)}&nbsp;%</b>)"
        out.append(f"Sur {a0}–{a1}, le trafic marocain croît de <b>{fmt(tc['Maroc'], 2)}&nbsp;%</b> par an, "
                   f"au <b>{ordinal(r)} rang sur {len(tc)}</b> pays comparables{suite}.")

    v19, v20 = val(p, 2019, "Maroc"), val(p, 2020, "Maroc")
    if pd.notna(v19) and pd.notna(v20) and v19 > 0:
        phrase = f"Le COVID-19 a fait chuter le trafic marocain de <b>{fmt(abs((v20 / v19 - 1) * 100), 1)}&nbsp;%</b> entre 2019 et 2020"
        if pd.notna(kpi["reprise"]):
            comp = "au-dessus" if kpi["reprise"] >= 0 else "en dessous"
            phrase += (f" ; en {ref}, il se situe <b>{fmt(abs(kpi['reprise']), 1)}&nbsp;%</b> {comp} du niveau de 2019")
        out.append(phrase + ".")
    return out


# ── Graphiques ────────────────────────────────────────────────────────────
def _message_vide(texte: str) -> Figure:
    fig = Figure(figsize=(6, 2.4))
    ax = fig.subplots()
    ax.axis("off")
    ax.text(0.5, 0.5, texte, ha="center", va="center", color=MUTED, transform=ax.transAxes)
    return fig


def _ordre(sel: list[str]) -> list[str]:
    return [c for c in PAYS if c in sel]


def fig_courbes(p, sel, a0, a1, log: bool) -> Figure:
    """Évolution du nombre de passagers (millions), Maroc en évidence, échelle log optionnelle."""
    sub = p.loc[a0:a1, sel] / 1e6
    fig = Figure(figsize=(11, 5.0))
    ax = fig.subplots()
    for c in [x for x in _ordre(sel) if x != "Maroc"] + (["Maroc"] if "Maroc" in sel else []):
        est_maroc = c == "Maroc"
        ax.plot(sub.index, sub[c], color=COULEURS[c], lw=3.8 if est_maroc else 1.8,
                alpha=1 if est_maroc else 0.8, label=c, zorder=5 if est_maroc else 3)
    if log:
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    if a0 <= 2020 <= a1:
        ax.axvspan(2019.5, 2020.5, color="#FFFFFF", alpha=0.09, zorder=1)
        ax.text(2019.2, 0.04, "COVID-19 : chute de 2020", transform=ax.get_xaxis_transform(),
                ha="right", va="bottom", fontsize=9, color=FG)
    ax.set_xlabel("Année")
    ax.set_ylabel("Passagers transportés (millions" + (", échelle log)" if log else ")"))
    h, l = ax.get_legend_handles_labels()
    tri = sorted(range(len(l)), key=lambda i: PAYS.index(l[i]))
    ax.legend([h[i] for i in tri], [l[i] for i in tri], ncol=len(l), loc="upper center",
              bbox_to_anchor=(0.5, -0.16))
    fig.tight_layout()
    return fig


def fig_classement(p, sel, ref) -> Figure:
    """Classement horizontal des pays pour l'année de référence."""
    s = (p.loc[ref, sel] / 1e6).dropna().sort_values(ascending=False)
    if s.empty:
        return _message_vide(f"Aucune donnée en {ref}")
    d = pd.DataFrame({"Pays": s.index, "M": s.values})
    fig = Figure(figsize=(6.4, 4.4))
    ax = fig.subplots()
    sns.barplot(data=d, x="M", y="Pays", hue="Pays", order=list(s.index), palette=COULEURS,
                legend=False, ax=ax)
    for patch in ax.patches:                       # étiquettes de valeur
        w = patch.get_width()
        if w and w > 0:
            ax.text(w, patch.get_y() + patch.get_height() / 2, f"  {fmt(w, 2)} M",
                    va="center", color=FG, fontsize=9)
    ax.set_yticks(range(len(s)))
    ax.set_yticklabels(list(s.index))
    for lab in ax.get_yticklabels():
        if lab.get_text() == "Maroc":
            lab.set_fontweight("bold")
            lab.set_color(COULEURS["Maroc"])
    ax.set_xlim(0, s.max() * 1.22)
    ax.set_xlabel(f"Passagers transportés en {ref} (millions)")
    ax.set_ylabel("")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return fig


def fig_aires(p, sel, a0, a1) -> tuple[Figure, int]:
    """Aires empilées (millions). Seules les années complètes pour tous les pays sont tracées."""
    ordre = _ordre(sel)
    complet = (p.loc[a0:a1, ordre] / 1e6).dropna(how="any")
    ecartees = len(p.loc[a0:a1]) - len(complet)
    if complet.empty:
        return _message_vide("Aucune année complète pour tous les pays sélectionnés"), ecartees
    fig = Figure(figsize=(6.4, 4.4))
    ax = fig.subplots()
    ax.stackplot(complet.index, [complet[c] for c in ordre], labels=ordre,
                 colors=[COULEURS[c] for c in ordre], alpha=0.92)
    ax.set_xlabel("Année")
    ax.set_ylabel("Passagers cumulés (millions)")
    ax.set_xlim(complet.index.min(), complet.index.max())
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.17), fontsize=8.5)
    fig.tight_layout()
    return fig, ecartees


def fig_heatmap(p, sel, a0, a1) -> Figure:
    """Heatmap de la croissance annuelle (%), échelle saturée à ±40 % pour rester lisible."""
    g = croissance(p).loc[a0:a1, _ordre(sel)].T
    if g.empty or g.isna().all().all():
        return _message_vide("Croissance non calculable sur cette période")
    fig = Figure(figsize=(11, 1.0 + 0.55 * len(g)))
    ax = fig.subplots()
    cmap = sns.diverging_palette(12, 145, s=80, l=55, as_cmap=True)
    annoter = g.shape[1] <= 14
    sns.heatmap(g, cmap=cmap, center=0, vmin=-40, vmax=40, linewidths=0.4, linecolor=BG,
                annot=annoter, fmt=".0f", annot_kws={"size": 8},
                cbar_kws={"label": "Croissance annuelle (%)", "pad": 0.015}, ax=ax)
    annees = list(g.columns)
    pas = 1 if len(annees) <= 15 else 5
    pos = [i + 0.5 for i, a in enumerate(annees) if a % pas == 0]
    ax.set_xticks(pos)
    ax.set_xticklabels([a for a in annees if a % pas == 0], rotation=0)
    for lab in ax.get_yticklabels():
        lab.set_rotation(0)
        if lab.get_text() == "Maroc":
            lab.set_fontweight("bold")
            lab.set_color(COULEURS["Maroc"])
    ax.set_xlabel("Année")
    ax.set_ylabel("")
    ax.grid(False)
    fig.tight_layout()
    return fig


def fig_covid(p, sel) -> Figure:
    """Chute puis reprise : niveau annuel en % du niveau de 2019 (2019 = 100)."""
    if 2019 not in p.index or 2020 not in p.index:
        return _message_vide("Les années 2019 et 2020 sont nécessaires")
    ordre = _ordre(sel)
    annees = list(range(2020, int(p.index.max()) + 1))
    niveau = p.loc[annees, ordre].div(p.loc[2019, ordre]) * 100
    long = niveau.reset_index().melt(id_vars="Année", var_name="Pays", value_name="Niveau").dropna()
    if long.empty:
        return _message_vide("Données insuffisantes pour 2019–2020")
    fig = Figure(figsize=(6.4, 4.4))
    ax = fig.subplots()
    sns.barplot(data=long, x="Année", y="Niveau", hue="Pays", hue_order=ordre,
                palette=COULEURS, errorbar=None, ax=ax)
    ax.axhline(100, ls="--", lw=1.2, color=FG, alpha=0.7)
    ax.text(0.01, 100, "Niveau 2019 = 100", transform=ax.get_yaxis_transform(),
            ha="left", va="bottom", fontsize=8.5, color=FG)
    v = niveau.loc[2020, "Maroc"] if "Maroc" in ordre else np.nan
    if pd.notna(v):
        ax.text(0.01, 0.97, f"Chute de 2020 : Maroc {fmt(v - 100, 0, True)} %", transform=ax.transAxes,
                ha="left", va="top", fontsize=9, color=FG)
    ax.set_ylim(0, max(125, np.nanmax(niveau.to_numpy()) * 1.12))
    ax.set_xlabel("Année")
    ax.set_ylabel("Passagers (% du niveau 2019)")
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.17), fontsize=8.5)
    fig.tight_layout()
    return fig


def fig_barres3d(p, sel, annees: list[int]) -> Figure:
    """Barres 3D : pays x années clés (millions de passagers)."""
    ordre = _ordre(sel)[::-1]     # ordre inversé : le Maroc au premier plan, les grandes barres au fond
    xs, ys, zs, cols = [], [], [], []
    for i, c in enumerate(ordre):
        for j, a in enumerate(annees):
            v = val(p, a, c)
            if pd.notna(v):
                xs.append(i), ys.append(j), zs.append(v / 1e6), cols.append(COULEURS[c])
    if not zs:
        return _message_vide("Aucune donnée pour les années clés")
    fig = Figure(figsize=(6.6, 4.8))
    ax = fig.add_subplot(111, projection="3d")
    ax.bar3d(np.array(xs) - 0.32, np.array(ys) - 0.28, 0, 0.64, 0.56, zs, color=cols, shade=True)
    ax.set_xticks(range(len(ordre)))
    ax.set_xticklabels(ordre, rotation=-18, fontsize=8)
    ax.set_yticks(range(len(annees)))
    ax.set_yticklabels(annees, fontsize=8)
    ax.set_zlabel("Passagers (millions)", fontsize=9)
    ax.tick_params(axis="z", labelsize=8)
    for axe in (ax.xaxis, ax.yaxis, ax.zaxis):
        axe.set_pane_color((0.055, 0.094, 0.216, 0.0))
    ax.view_init(elev=30, azim=-38)      # vue de face : les grandes barres (France, Espagne) ne masquent pas les petites
    fig.subplots_adjust(left=0.0, right=1.0, bottom=0.02, top=1.0)   # tight_layout n'est pas fiable en 3D
    return fig


# ════════════════════════════════════════════════════════════════════════════
# 5. COMPOSANTS HTML : CSS, LOGO, ICÔNES ANIMÉES, CARTES
# ════════════════════════════════════════════════════════════════════════════
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');
:root{--rouge:#FF3D54;--txt:#E8EEFF;--muted:#93A3CC;--bord:rgba(255,255,255,.12);--pos:#4ADE80;--neg:#FF6B7D}
.stApp, .stApp :is(p,label,button,input,textarea,h1,h2,h3,h4,li,td,th,a,span[data-testid="stCaptionContainer"]){font-family:'Poppins',sans-serif}
.stApp{background:
  radial-gradient(1100px 560px at 8% -12%,rgba(255,61,84,.17),transparent 60%),
  radial-gradient(900px 520px at 100% 0,rgba(64,110,255,.15),transparent 55%),
  linear-gradient(180deg,#0A1128,#0B1533 60%,#08102A)}
[data-testid="stHeader"]{background:transparent}
#MainMenu,footer{visibility:hidden}
.block-container{max-width:1280px;padding-top:1.2rem}
[data-testid="stSidebar"]{background:rgba(10,17,40,.92);border-right:1px solid var(--bord)}

/* Verre + profondeur 3D */
.glass{background:linear-gradient(145deg,rgba(255,255,255,.085),rgba(255,255,255,.03));
  border:1px solid var(--bord);border-radius:18px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  box-shadow:0 18px 40px -18px rgba(0,0,0,.65),inset 0 1px 0 rgba(255,255,255,.12);
  transform:perspective(900px) rotateX(0) rotateY(0);transition:transform .35s ease,box-shadow .35s ease,border-color .35s ease}
.glass:hover{border-color:rgba(255,255,255,.2)}
.kpi:hover{transform:perspective(900px) rotateX(4deg) rotateY(-5deg) translateY(-4px);
  border-color:rgba(255,61,84,.5);box-shadow:0 30px 48px -18px rgba(0,0,0,.75),0 0 0 1px rgba(255,61,84,.15)}

/* En-tête */
.topbar{display:flex;align-items:center;gap:16px;padding:14px 22px;margin-bottom:14px}
.topbar .logo{width:58px;height:58px;flex:none;filter:drop-shadow(0 8px 14px rgba(255,61,84,.35));animation:float 5s ease-in-out infinite}
.brand{flex:1;min-width:0}
.brand h1{margin:0;font-size:1.55rem;font-weight:700;letter-spacing:-.01em;padding:0}
.brand p{margin:2px 0 0;color:var(--muted);font-size:.86rem}
.chip{padding:6px 14px;border-radius:999px;border:1px solid var(--bord);color:var(--txt);font-size:.82rem;background:rgba(255,255,255,.05)}

/* KPI */
.kpi-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:.3rem 0 1rem}
@media (max-width:1000px){.kpi-grid{grid-template-columns:repeat(2,1fr)}}
.kpi{display:flex;align-items:center;gap:14px;padding:16px 18px}
.kpi-ico{width:54px;height:54px;flex:none;display:grid;place-items:center;border-radius:14px;
  background:linear-gradient(145deg,rgba(255,61,84,.28),rgba(255,61,84,.06));border:1px solid rgba(255,61,84,.35)}
.kpi-body{display:flex;flex-direction:column;min-width:0}
.kpi-label{color:var(--muted);font-size:.8rem}
.kpi-value{font-size:1.6rem;font-weight:600;line-height:1.2;letter-spacing:-.01em;white-space:nowrap}
.kpi-detail{font-size:.78rem;color:var(--muted)}
.kpi-detail.pos{color:var(--pos)} .kpi-detail.neg{color:var(--neg)}

/* Analyses textuelles */
.insights{padding:18px 24px;margin-bottom:1rem}
.insights h3{margin:0 0 6px;font-size:1.02rem;font-weight:600}
.insights ul{margin:0;padding:0}
.insights li{list-style:none;position:relative;padding-left:22px;margin:9px 0;line-height:1.65;font-size:.93rem;max-width:80ch}
.insights li::before{content:"";position:absolute;left:2px;top:.62em;width:8px;height:8px;border-radius:2px;background:var(--rouge);transform:rotate(45deg)}
.insights b{color:#fff;font-weight:600}
.note{padding:12px 18px;margin:.4rem 0 1rem;color:var(--muted);font-size:.85rem;line-height:1.6}
.sec{margin:1.3rem 0 .35rem}
.sec h3{margin:0;font-size:1.05rem;font-weight:600;padding:0}
.sec p{margin:2px 0 0;color:var(--muted);font-size:.84rem}
div[data-testid="stImage"] img{border-radius:16px;border:1px solid var(--bord)}

/* Onglets, boutons, formulaires */
.stTabs [data-baseweb="tab-list"]{gap:6px;border-bottom:1px solid var(--bord)}
.stTabs [data-baseweb="tab"]{padding:10px 20px;border-radius:12px 12px 0 0;color:var(--muted);font-weight:500}
.stTabs [aria-selected="true"]{color:#fff;background:rgba(255,61,84,.12)}
.stTabs [data-baseweb="tab-highlight"]{background:var(--rouge)}
[data-testid^="stBaseButton-primary"]{background:linear-gradient(135deg,#FF5468,#E5233B);border:none;color:#fff;border-radius:12px;
  box-shadow:0 10px 22px -10px rgba(255,61,84,.8);transition:transform .2s ease,box-shadow .2s ease}
[data-testid^="stBaseButton-primary"]:hover{transform:translateY(-2px);box-shadow:0 16px 26px -10px rgba(255,61,84,.9)}
[data-testid^="stBaseButton-secondary"]{border-radius:12px}
[data-testid="stForm"]{background:rgba(255,255,255,.04);border:1px solid var(--bord);border-radius:18px;padding:1.1rem}
:focus-visible{outline:2px solid #fff;outline-offset:2px}

/* Icônes SVG animées (une seule fois au chargement, rejouées au survol) */
.ico{width:30px;height:30px;color:var(--rouge);overflow:visible}
.ico .st{fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.ico .fl{fill:currentColor}
.ico .draw{stroke-dasharray:40;stroke-dashoffset:0;animation:draw 1.6s ease-out 1}
.kpi:hover .ico .draw{animation:draw 1.2s ease-out 1}
.ico .bar{transform-box:fill-box;transform-origin:center bottom;animation:rise .9s ease-out 1}
.ico .bar:nth-child(2){animation-delay:.12s} .ico .bar:nth-child(3){animation-delay:.24s}
.ico .spin{transform-box:fill-box;transform-origin:center}
.kpi:hover .ico .spin{animation:spin 1.3s ease-in-out 1}
.ico .plane{animation:bob 3.2s ease-in-out infinite}
@keyframes draw{from{stroke-dashoffset:40}to{stroke-dashoffset:0}}
@keyframes rise{from{transform:scaleY(.15)}to{transform:scaleY(1)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-1.5px)}}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}

/* Connexion */
.login-head{text-align:center;padding:26px 22px 18px;margin-bottom:12px}
.login-head .logo{width:84px;height:84px;filter:drop-shadow(0 12px 20px rgba(255,61,84,.4));animation:float 5s ease-in-out infinite}
.login-head h1{margin:8px 0 2px;font-size:1.7rem;font-weight:700;padding:0}
.login-head p{margin:0;color:var(--muted);font-size:.9rem}

/* Mobile */
@media (max-width:768px){
  .block-container{padding:.8rem .7rem}
  .topbar{flex-wrap:wrap;padding:12px 14px} .brand h1{font-size:1.2rem} .brand p{font-size:.78rem}
  .kpi-grid{grid-template-columns:repeat(2,1fr);gap:10px} .kpi{flex-direction:column;align-items:flex-start;gap:8px;padding:12px}
  .kpi-value{font-size:1.25rem} .insights{padding:14px 16px}
}
@media (max-width:340px){.kpi-grid{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
"""

# Logo : cube isométrique en volume (faces bleu nuit) surmonté d'un avion sur fond rouge Maroc
LOGO = (
    '<svg class="logo" viewBox="0 0 64 64" role="img" aria-label="Logo AtlasAir">'
    '<defs>'
    '<linearGradient id="lgT" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FF7A89"/><stop offset="1" stop-color="#E5233B"/></linearGradient>'
    '<linearGradient id="lgL" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1B3272"/><stop offset="1" stop-color="#0A1440"/></linearGradient>'
    '<linearGradient id="lgR" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2A4696"/><stop offset="1" stop-color="#132257"/></linearGradient>'
    '</defs>'
    '<polygon points="8,19 32,32 32,58 8,45" fill="url(#lgL)"/>'
    '<polygon points="56,19 32,32 32,58 56,45" fill="url(#lgR)"/>'
    '<polygon points="32,6 56,19 32,32 8,19" fill="url(#lgT)"/>'
    '<polygon points="32,6 56,19 32,32 8,19" fill="none" stroke="rgba(255,255,255,.35)" stroke-width=".8"/>'
    '<g transform="translate(32 19) rotate(45) scale(.52) translate(-12 -12)">'
    '<path fill="#fff" d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z"/></g>'
    '</svg>'
)


def _svg(contenu: str) -> str:
    return f'<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">{contenu}</svg>'


ICONES = {
    "passagers": _svg('<path class="fl plane" d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z"/>'),
    "variation": _svg('<polyline class="st draw" points="3,17 9,11 13,15 21,6"/><polyline class="st" points="15,6 21,6 21,12"/>'),
    "rang": _svg('<rect class="fl bar" x="2.5" y="13" width="5.5" height="8" rx="1"/><rect class="fl bar" x="9.2" y="5" width="5.5" height="16" rx="1"/><rect class="fl bar" x="16" y="10" width="5.5" height="11" rx="1"/>'),
    "part": _svg('<circle class="st" cx="12" cy="12" r="8" stroke-opacity=".28" stroke-width="4"/><g class="spin"><circle class="st" cx="12" cy="12" r="8" stroke-width="4" stroke-dasharray="24 27" transform="rotate(-90 12 12)"/></g>'),
    "tcam": _svg('<path class="st" d="M3 3v18h18" stroke-opacity=".4"/><path class="st draw" d="M5 17C9 17 10 10 14 9s5-4 6-5"/><circle class="fl" cx="20" cy="4" r="1.6"/>'),
    "reprise": _svg('<g class="spin"><path class="st" d="M20 12a8 8 0 1 1-2.6-5.9"/><polyline class="st" points="20,3.5 20,8 15.5,8"/></g>'),
}


def carte_kpi(icone: str, libelle: str, valeur: str, detail: str, ton: str = "") -> str:
    """Carte KPI en verre (HTML sur une seule ligne pour éviter les blocs de code Markdown)."""
    return (f'<div class="glass kpi"><div class="kpi-ico">{ICONES[icone]}</div><div class="kpi-body">'
            f'<span class="kpi-label">{libelle}</span><span class="kpi-value">{valeur}</span>'
            f'<span class="kpi-detail {ton}">{detail}</span></div></div>')


def ton_signe(x) -> str:
    return "" if pd.isna(x) else ("pos" if x >= 0 else "neg")


def titre_section(titre: str, sous_titre: str = "") -> None:
    p = f"<p>{sous_titre}</p>" if sous_titre else ""
    st.markdown(f'<div class="sec"><h3>{titre}</h3>{p}</div>', unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# 6. CALLBACKS (exécutés AVANT le rerun : les KPI et graphiques voient les nouvelles données)
# ════════════════════════════════════════════════════════════════════════════
def _flash(niveau: str, texte: str) -> None:
    st.session_state["flash"] = (niveau, texte)


def cb_connexion() -> None:
    ss = st.session_state
    if ss["echecs"] >= MAX_ECHECS:
        return
    if verifier_identifiants(ss.get("l_user", ""), ss.get("l_pwd", "")):
        ss["auth"], ss["user"], ss["echecs"] = True, ss["l_user"].strip(), 0
        ss["l_pwd"] = ""
    else:
        ss["echecs"] += 1


def cb_deconnexion() -> None:
    st.session_state["auth"] = False
    st.session_state["user"] = ""


def cb_enregistrer() -> None:
    """Formulaire de saisie : validation, détection de doublon, ajout ou remplacement."""
    ss = st.session_state
    pays, annee, valeur = ss["s_pays"], ss["s_annee"], ss["s_val"]
    remplacer = ss.get("s_remplacer", False)

    if valeur is None:
        return _flash("error", "Saisissez un nombre de passagers.")
    if not (ANNEE_SAISIE_MIN <= annee <= ANNEE_SAISIE_MAX):
        return _flash("error", f"L'année doit être comprise entre {ANNEE_SAISIE_MIN} et {ANNEE_SAISIE_MAX}.")
    if valeur <= 0:
        return _flash("error", "Le nombre de passagers doit être strictement positif.")
    if valeur > PASSAGERS_MAX:
        return _flash("error", f"Valeur invraisemblable (plus de {fmt(PASSAGERS_MAX, 0)} passagers).")

    df = ss["df"]
    existe = (df["Pays"] == pays) & (df["Année"] == annee)
    if existe.any() and not remplacer:
        ancienne = df.loc[existe, "Passagers"].iloc[0]
        return _flash("warning", f"{pays} {annee} existe déjà ({fmt(ancienne, 0)} passagers). "
                                 "Cochez « Remplacer la valeur existante » puis enregistrez à nouveau.")
    nouvelle = pd.DataFrame([{"Pays": pays, "Année": int(annee), "Passagers": float(valeur), "Origine": "Saisie"}])
    df = pd.concat([df[~existe], nouvelle], ignore_index=True).sort_values(["Pays", "Année"]).reset_index(drop=True)
    ss["df"] = df
    msg = f"{pays} {annee} : {'valeur remplacée' if existe.any() else 'valeur ajoutée'} ({fmt(valeur, 0)} passagers)."
    _flash("success", msg)
    st.toast(msg)


def cb_importer() -> None:
    """Import d'un CSV : fusion (doublons remplacés) ou remplacement complet."""
    ss = st.session_state
    fichier = ss.get(f"upl_{ss['upl_ver']}")
    if fichier is None:
        return _flash("error", "Aucun fichier sélectionné.")
    try:
        nouveau, rap = normaliser(lire_csv(fichier), "Import")
    except Exception as e:
        return _flash("error", f"Import impossible : {e}")
    if nouveau.empty:
        return _flash("error", "Aucune ligne valide dans le fichier (pays reconnus, années et passagers positifs).")

    df = ss["df"]
    if ss["imp_mode"].startswith("Remplacer"):
        ss["df"] = nouveau
        detail = f"{len(nouveau)} lignes chargées (jeu de données remplacé)"
    else:
        cles = set(zip(df["Pays"], df["Année"]))
        remplacees = sum((p, a) in cles for p, a in zip(nouveau["Pays"], nouveau["Année"]))
        ss["df"] = (pd.concat([df, nouveau]).drop_duplicates(["Pays", "Année"], keep="last")
                    .sort_values(["Pays", "Année"]).reset_index(drop=True))
        detail = f"{len(nouveau) - remplacees} lignes ajoutées, {remplacees} remplacées"
    ecarts = []
    if rap["hors_perimetre"]:
        ecarts.append(f"{rap['hors_perimetre']} hors des 6 pays")
    if rap["invalides"]:
        ecarts.append(f"{rap['invalides']} invalides")
    if rap["doublons"]:
        ecarts.append(f"{rap['doublons']} doublons internes")
    suite = f" Écartées : {', '.join(ecarts)}." if ecarts else ""
    _flash("success", f"Import terminé : {detail}.{suite}")
    ss["upl_ver"] += 1        # vide le champ de téléversement


def cb_reinitialiser() -> None:
    ss = st.session_state
    ss["df"] = charger_base(str(DATA_PATH)).copy()
    ss["rst_ok"] = False
    ss["upl_ver"] += 1
    _flash("success", "Données réinitialisées : le jeu d'origine (OWID / OACI) est rechargé.")


# ════════════════════════════════════════════════════════════════════════════
# 7. PAGES
# ════════════════════════════════════════════════════════════════════════════
def init_etat() -> None:
    ss = st.session_state
    ss.setdefault("auth", False)
    ss.setdefault("user", "")
    ss.setdefault("echecs", 0)
    ss.setdefault("upl_ver", 0)
    if "df" not in ss:
        ss["df"] = charger_base(str(DATA_PATH)).copy()


def page_connexion() -> None:
    """Écran de connexion (comptes lus dans st.secrets)."""
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='collapsedControl']{display:none}</style>",
                unsafe_allow_html=True)
    _, centre, _ = st.columns([1, 1.15, 1])
    with centre:
        st.markdown(f'<div class="glass login-head">{LOGO}<h1>{APP_NAME}</h1>'
                    '<p>Trafic aérien du Maroc, comparé à cinq pays</p></div>', unsafe_allow_html=True)
        bloque = st.session_state["echecs"] >= MAX_ECHECS
        with st.form("form_connexion"):
            st.text_input("Identifiant", key="l_user", autocomplete="username")
            st.text_input("Mot de passe", type="password", key="l_pwd", autocomplete="current-password")
            st.form_submit_button("Se connecter", type="primary", on_click=cb_connexion, disabled=bloque)
        if bloque:
            st.error("Trop de tentatives échouées. Rechargez la page pour réessayer.")
        elif st.session_state["echecs"] > 0:
            st.error(f"Identifiant ou mot de passe incorrect ({st.session_state['echecs']}/{MAX_ECHECS}).")
        if charger_utilisateurs()[2]:
            st.info("Mode démonstration (aucun secret configuré) : identifiant **demo**, mot de passe **demo2026**.")


def barre_laterale(p: pd.DataFrame):
    """Filtres : pays comparés, période, année de référence. Retourne (sel, a0, a1, ref)."""
    with st.sidebar:
        mini = LOGO.replace('class="logo"', 'class="logo-mini"')
        st.markdown(f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:.6rem">'
                    f'<div style="width:38px">{mini}</div>'
                    f'<b style="font-size:1.05rem">{APP_NAME}</b></div>', unsafe_allow_html=True)
        st.markdown("**Filtres**")
        autres = [c for c in PAYS if c != "Maroc"]
        choix = st.multiselect("Pays comparés au Maroc", autres, default=autres, key="f_pays")
        st.caption("Le Maroc est toujours inclus.")
        amin, amax = int(p.index.min()), int(p.index.max())
        if amin < amax:
            a0, a1 = st.slider("Période", amin, amax, (amin, amax), key="f_periode")
        else:
            a0 = a1 = amin
            st.caption(f"Une seule année disponible : {amin}.")
        options = list(range(a1, a0 - 1, -1))
        idx = next((i for i, a in enumerate(options) if pd.notna(val(p, a, "Maroc"))), 0)
        ref = st.selectbox("Année de référence", options, index=idx, key="f_ref")
        st.divider()
        st.markdown(f'<span class="chip">{html.escape(st.session_state["user"])}</span>', unsafe_allow_html=True)
        st.button("Se déconnecter", on_click=cb_deconnexion)
    sel = [c for c in PAYS if c == "Maroc" or c in choix]
    return sel, a0, a1, ref


def onglet_dashboard(p, sel, a0, a1, ref) -> None:
    kpi = calculer_kpi(p, sel, a0, a1, ref)
    r = kpi["rang"]
    cartes = [
        carte_kpi("passagers", "Passagers transportés", fmt(kpi["passagers"] / 1e6, 2, suffixe=" M"), f"en {ref}"),
        carte_kpi("variation", "Variation annuelle", fmt(kpi["variation"], 1, True, " %"), f"par rapport à {ref - 1}",
                  ton_signe(kpi["variation"])),
        carte_kpi("rang", "Rang du Maroc", ordinal(r) if r else "n/d",
                  f"sur {len(sel)} pays" if r else "valeurs manquantes"),
        carte_kpi("part", "Part de marché", fmt(kpi["part"], 1, suffixe=" %"), f"du trafic des {len(sel)} pays"),
        carte_kpi("tcam", "TCAM", fmt(kpi["tcam"], 2, True, " %/an"), f"{a0}–{a1}", ton_signe(kpi["tcam"])),
        carte_kpi("reprise", "Reprise vs 2019", fmt(kpi["reprise"], 1, True, " %"),
                  "écart au niveau de 2019" if ref >= 2020 else "disponible dès 2020", ton_signe(kpi["reprise"])),
    ]
    st.markdown(f'<div class="kpi-grid">{"".join(cartes)}</div>', unsafe_allow_html=True)

    lignes = "".join(f"<li>{t}</li>" for t in generer_insights(p, sel, a0, a1, ref, kpi))
    st.markdown(f'<div class="glass insights"><h3>Ce que disent les chiffres</h3><ul>{lignes}</ul></div>',
                unsafe_allow_html=True)

    manq = manquants(p, sel, a0, a1)
    if manq:
        st.markdown(f'<div class="glass note">{len(manq)} valeur(s) manquante(s) dans la sélection : elles restent '
                    'vides (aucune interpolation) et les indicateurs concernés s\'affichent « n/d ». '
                    'Détail dans l\'onglet Données.</div>', unsafe_allow_html=True)

    titre_section(f"Comparaison des pays en {ref}", "Chaque indicateur est calculé uniquement sur les valeurs disponibles.")
    tab = tableau_comparatif(p, sel, a0, a1, ref)
    st.dataframe(tab.style.format(lambda v: fmt(v, 2)), height=40 + 36 * len(tab))


def onglet_analyses(p, sel, a0, a1, ref) -> None:
    titre_section("Évolution du trafic", f"Passagers transportés, {a0}–{a1}. Le Maroc est en trait épais.")
    log = st.toggle("Échelle logarithmique", value=True, key="g_log",
                    help="Rend lisibles à la fois les petits et les grands trafics.")
    st.pyplot(fig_courbes(p, sel, a0, a1, log))

    c1, c2 = st.columns(2)
    with c1:
        titre_section(f"Classement en {ref}", "Passagers transportés, en millions.")
        st.pyplot(fig_classement(p, sel, ref))
    with c2:
        titre_section("Poids de chaque pays", "Aires empilées : trafic cumulé du groupe.")
        fig, ecartees = fig_aires(p, sel, a0, a1)
        st.pyplot(fig)
        if ecartees:
            st.caption(f"{ecartees} année(s) écartée(s) car incomplètes pour au moins un pays.")

    titre_section("Rythme de croissance", "Croissance annuelle (%) ; l'échelle de couleurs est saturée à ±40 %.")
    st.pyplot(fig_heatmap(p, sel, a0, a1))

    c3, c4 = st.columns(2)
    with c3:
        titre_section("Chute et reprise après le COVID-19", "Trafic annuel en % du niveau de 2019.")
        st.pyplot(fig_covid(p, sel))
    with c4:
        titre_section("Trois années clés en volume", f"2010, 2019 et {ref} (barres 3D, millions).")
        st.pyplot(fig_barres3d(p, sel, sorted({2010, 2019, ref})))
    st.caption(SOURCE)


def onglet_donnees(p, sel, a0, a1) -> None:
    ss = st.session_state
    flash = ss.pop("flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])

    df = ss["df"]
    n_saisies = int((df["Origine"] != ORIGINE_BASE).sum())
    st.markdown(f'<div class="glass note">{len(df)} observations chargées, dont <b>{n_saisies}</b> ajoutée(s) '
                'par saisie ou import. Les modifications vivent dans votre session : exportez le CSV pour les conserver.</div>',
                unsafe_allow_html=True)

    g1, g2 = st.columns(2)
    with g1:
        titre_section("Saisir une valeur", "Ajoute une année ou corrige une valeur existante.")
        with st.form("form_saisie"):
            st.selectbox("Pays", PAYS, key="s_pays")
            st.number_input("Année", ANNEE_SAISIE_MIN, ANNEE_SAISIE_MAX, int(df["Année"].max()) + 1, 1, key="s_annee")
            st.number_input("Passagers transportés", min_value=0.0, value=None, step=1000.0, format="%.0f",
                            placeholder="ex. 9354197", key="s_val")
            st.checkbox("Remplacer la valeur existante si elle existe", key="s_remplacer")
            st.form_submit_button("Enregistrer la valeur", type="primary", on_click=cb_enregistrer)
    with g2:
        titre_section("Importer un fichier CSV", "Format OWID (Entity, Year, …) ou Pays, Année, Passagers.")
        st.file_uploader("Fichier CSV", type=["csv"], key=f"upl_{ss['upl_ver']}", label_visibility="collapsed")
        st.radio("Mode d'import", ["Fusionner (les doublons sont remplacés)", "Remplacer tout le jeu de données"],
                 key="imp_mode")
        st.button("Importer le fichier", type="primary", on_click=cb_importer,
                  disabled=ss.get(f"upl_{ss['upl_ver']}") is None)

    titre_section("Exporter et réinitialiser")
    e1, e2 = st.columns(2)
    with e1:
        csv = df.sort_values(["Pays", "Année"]).to_csv(index=False).encode("utf-8-sig")
        st.download_button("Exporter les données (CSV)", csv, "trafic_aerien_maroc.csv", "text/csv")
    with e2:
        st.checkbox("Je confirme vouloir revenir aux données d'origine", key="rst_ok")
        st.button("Réinitialiser les données", on_click=cb_reinitialiser, disabled=not ss.get("rst_ok", False))

    titre_section("Tableau des données", "Passagers par année et par pays ; « n/d » = valeur absente.")
    vue = p.loc[a0:a1, sel].sort_index(ascending=False)
    st.dataframe(vue.style.format(lambda v: fmt(v, 0)), height=360)

    manq = manquants(p, sel, a0, a1)
    with st.expander(f"Valeurs manquantes ({len(manq)})"):
        if manq:
            st.dataframe(pd.DataFrame(manq, columns=["Pays", "Année"]), height=220)
        else:
            st.write("Aucune valeur manquante pour la sélection courante.")
    with st.expander("À propos des données"):
        st.write("Passagers des compagnies aériennes immatriculées dans chaque pays, vols intérieurs et "
                 "internationaux confondus (chaque passager est compté une fois par numéro de vol). "
                 "Ce n'est donc pas le trafic des aéroports. Les données de la Banque mondiale s'arrêtent à 2023 ; "
                 "l'OACI peut estimer certaines valeurs manquantes. " + SOURCE + ".")


def application() -> None:
    """Application principale, visible après connexion."""
    p = tableau_annuel(st.session_state["df"])
    sel, a0, a1, ref = barre_laterale(p)
    st.markdown(f'<div class="glass topbar">{LOGO}<div class="brand"><h1>{APP_NAME}</h1>'
                '<p>Le trafic aérien du Maroc face à l\'Algérie, la Tunisie, l\'Égypte, la France et l\'Espagne</p></div></div>',
                unsafe_allow_html=True)
    t1, t2, t3 = st.tabs(["Tableau de bord", "Analyses", "Données"])
    with t1:
        onglet_dashboard(p, sel, a0, a1, ref)
    with t2:
        onglet_analyses(p, sel, a0, a1, ref)
    with t3:
        onglet_donnees(p, sel, a0, a1)


def main() -> None:
    st.set_page_config(page_title=APP_NAME, layout="wide", initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)
    if not DATA_PATH.exists():
        st.error(f"Fichier de données introuvable : {DATA_PATH}")
        st.stop()
    init_etat()
    if st.session_state["auth"]:
        application()
    else:
        page_connexion()


if __name__ == "__main__":
    main()
