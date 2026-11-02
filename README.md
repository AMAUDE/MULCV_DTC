# MULCV_DTC — Cartographie des lotissements de Marcory et Bingerville

Atlas cartographique des plans de lotissement convertis (DWG vers SHP avec le plugin QGIS Amaude), assemblés en WGS 84 / UTM 30N (EPSG:32630) : plateforme web, projet QGIS et script de mise à jour.

## Voir la plateforme en ligne

La page du dépôt GitHub n'affiche que la liste des fichiers : la carte s'ouvre avec GitHub Pages, à l'adresse
**https://amaude.github.io/MULCV_DTC/**

Activation (une seule fois, dans le dépôt) : **Settings → Pages → Build and deployment → Source : Deploy from a branch → Branch : `main`, dossier `/ (root)` → Save**. L'adresse est active après une à deux minutes.

## Contenu

| Dossier / fichier | Rôle |
|---|---|
| `LIVRABLES/PLATEFORME/` | Plateforme web autonome (carte, recherche, filtres, fiches, tableau, export CSV). Ouvrir `index.html`. |
| `LIVRABLES/PROJET_QGIS/` | Projet QGIS `ATLAS_LOTISSEMENTS.qgz`, limites communales, script `mettre_a_jour_plateforme.py` et son `.bat`. |
| `marcory_bingerville.gpkg` | Couche d'assemblage : `assemblage_01_dtc` (lots) et `limites_de_lotissement` (un polygone par plan : type, conformité, polygonale). |

La disposition des dossiers est celle du poste de travail : le projet QGIS et le script lisent `marcory_bingerville.gpkg` à la racine du dépôt (`../../`). Ne pas déplacer les dossiers les uns par rapport aux autres.

## Ce que la plateforme indique

- Type de plan : **Normale** ou **Régularisation**.
- **Conformité** du lotissement (oui / non) ; la limite d'un lotissement non conforme est tracée en tirets.
- **Chevauchements** entre lotissements (zones d'au moins 0,5 ha), avec le détail dans la fiche de chaque plan.
- Recherche par lotissement, localité, sous-préfecture ; filtres commune, type, conformité, chevauchement.

## Utiliser la plateforme

Ouvrir `LIVRABLES/PLATEFORME/index.html` dans Chrome, Edge ou Firefox. Le dossier est autonome (bibliothèque cartographique, polices et étiquettes dans `lib/`) et fonctionne sans connexion. Seuls les fonds de carte Plan et Satellite (Esri) demandent internet.

## Mettre à jour la plateforme

1. Modifier les couches de `marcory_bingerville.gpkg` dans QGIS (type, conforme, polygonale, limites, lots) et enregistrer.
2. Lancer `LIVRABLES/PROJET_QGIS/mettre_a_jour_plateforme.bat` (Python avec `geopandas`, `shapely`, `pyproj`).
3. Recharger `index.html` (Ctrl+F5).

Le script rattache les lots à leur plan, reconstitue les îlots, calcule les chevauchements et réécrit `LIVRABLES/PLATEFORME/data/` ainsi que `LIVRABLES/PROJET_QGIS/controle_plateforme.gpkg`. Détails : `LIVRABLES/PROJET_QGIS/LISEZMOI.txt`.

## Composants tiers

- [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) 4.7.1 (licence BSD 3 clauses), dans `LIVRABLES/PLATEFORME/lib/`.
- Polices Barlow, Barlow Semi Condensed et IBM Plex Mono (SIL Open Font License 1.1) ; glyphes « Open Sans Semibold » (Apache 2.0).
- Fonds de carte © Esri, HERE, Garmin, OpenStreetMap contributors ; imagerie © Esri, Maxar, Earthstar Geographics (chargés en ligne, non inclus).
