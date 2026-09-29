# AtlasAir Analytics

Tableau de bord Streamlit du trafic aérien du Maroc, comparé à l'Algérie, la Tunisie, l'Égypte,
la France et l'Espagne (1970–2023). Source : OACI via Banque mondiale, traité par Our World in Data.

## Arborescence

```
atlasair/
├── app.py                        # application (login, KPI, graphiques, saisie / import / export)
├── requirements.txt              # dépendances
├── README.md
├── .gitignore                    # exclut .streamlit/secrets.toml
├── data/
│   └── dataset.csv               # 6 pays, 1970-2023 (colonnes OWID : Entity, Code, Year, passagers)
└── .streamlit/
    ├── config.toml               # thème bleu nuit + rouge
    └── secrets.toml.example      # modèle des comptes (à copier, jamais à versionner)
```

## Lancer en local

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # puis renseigner les hash
streamlit run app.py
```
Sans `secrets.toml`, l'application démarre en mode démo : **demo / demo2026**.

## Créer un compte (hash SHA-256)

```bash
python -c "import hashlib; print(hashlib.sha256(('MON_SEL'+'MonMotDePasse').encode()).hexdigest())"
```
Collez le résultat dans `[users]` ; `MON_SEL` doit être identique à `[auth] salt`.

## Déployer sur Streamlit Community Cloud

1. **GitHub** : créez un dépôt, puis poussez le dossier (`app.py`, `requirements.txt`, `data/`, `.streamlit/config.toml`,
   `.gitignore`). Vérifiez que `secrets.toml` n'est pas commité.
2. **share.streamlit.io** : *Create app* → choisissez le dépôt, la branche et `app.py` comme fichier principal.
3. **Secrets** : *Advanced settings* (ou *Settings > Secrets* après coup) → collez le contenu de `secrets.toml.example`
   avec vos vrais hash, puis *Deploy*.
4. Désormais, chaque `git push` redéploie l'application.

## À savoir

- Saisies et imports vivent dans la **session** du navigateur (le disque de Streamlit Cloud est éphémère) :
  utilisez « Exporter les données (CSV) » pour les conserver, puis réimportez-les.
- Aucune valeur manquante n'est interpolée : elle reste vide, apparaît en « n/d » et est listée dans l'onglet Données.
- Les données comptent les passagers des compagnies **immatriculées** dans chaque pays, pas ceux des aéroports.
