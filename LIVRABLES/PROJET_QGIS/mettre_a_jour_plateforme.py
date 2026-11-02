# -*- coding: utf-8 -*-
"""
Met a jour la plateforme (dossier ../PLATEFORME/data) a partir de la couche d'assemblage
marcory_bingerville.gpkg (couches assemblage_01_dtc = lots, limites_de_lotissement = plans).

Usage :  python mettre_a_jour_plateforme.py [--gpkg fichier.gpkg] [--out dossier_de_sortie]

Ce que le script calcule pour chaque lotissement
  - type (Normale / Regularisation), conformite (oui / non) et polygonale, lus dans la couche des limites ;
  - lots : rattaches a leur plan par le champ « lotissement » (controle spatial en cas de doute) ;
  - ilots : reconstitues en regroupant les lots qui portent le meme numero d'ilot ;
  - chevauchements entre lotissements : zones ou deux limites se recouvrent ou ou des lots de deux
    plans differents se superposent (lots identiques ou partiellement recouverts) ;
  - controle de zone, superficies, lots numerotes, emprise de zoom, date triable.
Il reecrit les fichiers .js lus par index.html et, si possible, la couche de controle
controle_plateforme.gpkg (ilots reconstitues, zones de chevauchement, synthese des plans) a ouvrir dans QGIS.
Bibliotheques : geopandas, shapely, pyproj.
"""
import sys, os, re, json, unicodedata, argparse, warnings
warnings.filterwarnings("ignore", "GeoSeries.notna", UserWarning)
from pathlib import Path

try:
    import numpy as np
    import geopandas as gpd
    import pyproj
    import shapely
    from shapely import make_valid, set_precision
    from shapely.geometry import mapping
    from shapely.ops import unary_union, transform
    from shapely.strtree import STRtree
except ImportError as e:
    sys.exit("Bibliotheque manquante (%s). Installer : pip install geopandas pyproj shapely" % e)

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--gpkg", help="GeoPackage d'assemblage (defaut : marcory_bingerville.gpkg a cote du script ou dans le dossier parent)")
ap.add_argument("--out", help="dossier de sortie des fichiers .js (defaut : ../PLATEFORME/data)")
ap.add_argument("legacy_out", nargs="?", help=argparse.SUPPRESS)
args = ap.parse_args()

CANDIDATES = [HERE / "marcory_bingerville.gpkg", HERE.parent.parent / "marcory_bingerville.gpkg"]
GPKG = Path(args.gpkg) if args.gpkg else next((c for c in CANDIDATES if c.exists()), None)
if GPKG is None or not GPKG.exists(): sys.exit("GeoPackage d'assemblage introuvable. Indiquer son chemin avec --gpkg.")
WEB = Path(args.out or args.legacy_out) if (args.out or args.legacy_out) else HERE.parent / "PLATEFORME" / "data"
CONTROLE = HERE / "controle_plateforme.gpkg"
COMMUNES_SRC = [(HERE / "communes.gpkg", "communes"), (HERE / "atlas_lotissements.gpkg", "communes"), (HERE / "ancien" / "atlas_lotissements.gpkg", "communes")]
# optionnel : couche des sous-prefectures, utilisee seulement si une sous-prefecture est laissee vide
SOUSPREF = Path(r"C:/Users/SITC/Documents/MULCV/DATA INPUT/NEW/DTC/reg_dep_sspref-CI/reg_dep_sspref/souspref509.shp")
WEB.mkdir(parents=True, exist_ok=True)

SEUIL_BAVURE_M2 = 100.0             # en dessous : simple bavure de tracé le long d'une limite commune, ignoré
SEUIL_CHEVAUCHEMENT_M2 = 5000.0     # zones plus petites (0,5 ha) : listées ici et dans la couche chevauchements_mineurs, non montrées sur la plateforme
SEUIL_LOT_M2 = 1.0                  # recouvrement minimal entre deux lots pour compter
FILIFORME_LOT = 0.4                 # surface / perimetre en dessous duquel un « lot » est un artefact de conversion
FERMETURE_ILOT_M = 1.0              # lacunes comblees entre les lots d'un meme ilot (m)

MONTHS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
deacc = lambda s: "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")


def date_iso(s):
    m = re.match(r"^(?:DU\s+)?(\d{1,2})\s+([A-Za-z\u00C0-\u017F]+)\s+(\d{4})\.?$", str(s or "").strip(), re.I)
    mo = MONTHS.get(deacc(m.group(2)).lower()) if m else None
    return "%04d-%02d-%02d" % (int(m.group(3)), mo, int(m.group(1))) if mo else None


def clean(v):
    if v is None or (isinstance(v, float) and v != v): return None
    s = str(v).strip()
    return s if s and s.lower() not in ("nan", "none", "<na>") else None


def yesno(v):
    s = deacc(clean(v) or "").lower()
    return "oui" if s in ("oui", "o", "yes", "1", "true", "vrai") else ("non" if s in ("non", "n", "no", "0", "false", "faux") else None)


def polys(g):
    if g is None or g.is_empty: return None
    if not g.is_valid: g = make_valid(g)
    if g.geom_type in ("Polygon", "MultiPolygon"): return g
    parts = [p for p in getattr(g, "geoms", []) if p.geom_type in ("Polygon", "MultiPolygon")]
    return unary_union(parts) if parts else None


def read(layer, path=None):
    g = gpd.read_file(path or GPKG, layer=layer)
    if g.crs is None or g.crs.to_epsg() != 32630: g = g.to_crs(32630)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    g["geometry"] = [polys(x) for x in g.geometry]
    return g[g.geometry.notna()].reset_index(drop=True)


def fill_small_holes(g, max_area=100.0):
    if g.geom_type == "Polygon": return shapely.Polygon(g.exterior, [r for r in g.interiors if shapely.Polygon(r).area > max_area])
    return shapely.MultiPolygon([fill_small_holes(p, max_area) for p in g.geoms])


print("Lecture de", GPKG)
lots = read("assemblage_01_dtc"); lim = read("limites_de_lotissement")
# les plans : un seul polygone par plan_id (une ligne vide en double est ecartee), indices contigus 0..n-1
lim["_a"] = lim.geometry.area; lim = lim[lim._a > 1.0].sort_values(["plan_id", "_a"], ascending=[True, False]).drop_duplicates("plan_id").sort_values("plan_id").reset_index(drop=True)
plans = lim.drop(columns="_a")
NP = len(plans)
pos = {int(pid): i for i, pid in enumerate(plans.plan_id)}      # plan_id -> position (= id dans la plateforme)

# ------------------------------------------------------------------ rattachement des lots aux plans
lots["nom_asm"] = lots["lotissement"].map(lambda v: clean(v) or "")
pts = lots.copy(); pts["geometry"] = lots.geometry.representative_point()
sj = gpd.sjoin(pts[["nom_asm", "geometry"]], gpd.GeoDataFrame({"pos": range(NP)}, geometry=plans.geometry.values, crs=32630), how="left", predicate="within")
sj = sj[~sj.index.duplicated(keep="first")]
count = {}
for nm, p in zip(sj["nom_asm"], sj["pos"]):
    if p == p: count[(nm, int(p))] = count.get((nm, int(p)), 0) + 1
mapping_nom, used = {}, set()
for (c, nm, p) in sorted(((c, nm, p) for (nm, p), c in count.items()), reverse=True):      # affectation 1:1, les plus gros recouvrements d'abord
    if nm in mapping_nom or p in used: continue
    mapping_nom[nm] = p; used.add(p)
for nm in sorted(set(lots.nom_asm) - set(mapping_nom)):                  # noms restants : meilleur plan libre, sinon meilleur plan
    cand = sorted(((c, p) for (n2, p), c in count.items() if n2 == nm), reverse=True)
    free = [p for c, p in cand if p not in used]
    if cand: mapping_nom[nm] = (free or [cand[0][1]])[0]
lots["pos_plan"] = lots.nom_asm.map(mapping_nom)
miss = lots.pos_plan.isna()
if miss.any():
    print("  ! %d lot(s) sans lotissement reconnu : rattaches au plan qui les contient" % int(miss.sum()))
    lots.loc[miss, "pos_plan"] = sj.loc[miss[miss].index, "pos"].values
lots = lots[lots.pos_plan.notna()].copy(); lots["pos_plan"] = lots.pos_plan.astype(int)
print("Rattachement des lots :")
for nm, p in sorted(mapping_nom.items(), key=lambda t: t[1]):
    tot = sum(c for (n2, _), c in count.items() if n2 == nm); share = 100 * count.get((nm, p), 0) / tot if tot else 0
    flag = "  ! a verifier" if share < 45 else ""
    print("  %-50s -> %2d %-34s %3.0f %%%s" % (nm.strip()[:50], p, plans.nom[p][:34], share, flag))
for p in range(NP):
    if p not in set(lots.pos_plan): print("  ! aucun lot pour le plan", plans.nom[p])

# ------------------------------------------------------------------ nettoyage des lots
lots["area_lot"] = [g.area for g in lots.geometry]
lots["art_lot"] = (lots.area_lot / lots.geometry.length) < FILIFORME_LOT
art_by = lots[lots.art_lot].groupby("pos_plan").size().to_dict()
raw_by = lots.groupby("pos_plan").size().to_dict()
lots = lots[~lots.art_lot].reset_index(drop=True)
print("Lots : %d (dont %d polygones filiformes ecartes)" % (len(lots), sum(art_by.values())))
lots["ilot_n"] = lots["ilot"].map(lambda v: re.sub(r"^ILOT_", "", clean(v) or "", flags=re.I) or None)
lots["num_lot"] = lots["nom_lot"].map(clean)

# ------------------------------------------------------------------ ilots reconstitues (lots d'un meme numero d'ilot)
ilot_rows = []
for (pp, il), grp in lots[lots.ilot_n.notna()].groupby(["pos_plan", "ilot_n"]):
    g = unary_union([x.buffer(FERMETURE_ILOT_M / 2) for x in grp.geometry]).buffer(-FERMETURE_ILOT_M / 2)
    g = polys(g)
    if g is None or g.area < 1: continue
    ilot_rows.append(dict(pos=int(pp), nom_ilot=il, n_lots=len(grp), geometry=fill_small_holes(g)))
ilots = gpd.GeoDataFrame(ilot_rows, geometry="geometry", crs=32630)
print("Ilots reconstitues :", len(ilots))

# ------------------------------------------------------------------ chevauchements : entre lotissements et entre lots d'un meme plan
geoms = list(lots.geometry); posl = lots.pos_plan.values
tree = STRtree(geoms)
ia, ib = tree.query(geoms, predicate="intersects")
sel = ia < ib; ia, ib = ia[sel], ib[sel]
inter = shapely.intersection(np.array(geoms, dtype=object)[ia], np.array(geoms, dtype=object)[ib])
iarea = shapely.area(inter)
ov_in_m2, ov_in_n = {}, {}
pair_pieces, pair_n, pair_same = {}, {}, {}
for a, b, g, ar in zip(ia, ib, inter, iarea):
    if ar <= SEUIL_LOT_M2: continue
    pa, pb = int(posl[a]), int(posl[b])
    if pa == pb:
        ov_in_m2[pa] = ov_in_m2.get(pa, 0.0) + ar; ov_in_n[pa] = ov_in_n.get(pa, 0) + 1; continue
    k = (min(pa, pb), max(pa, pb))
    pair_pieces.setdefault(k, []).append(g); pair_n[k] = pair_n.get(k, 0) + 1
    if abs(ar - geoms[a].area) < 0.02 * ar and abs(ar - geoms[b].area) < 0.02 * ar: pair_same[k] = pair_same.get(k, 0) + 1
fp_list = [polys(g) for g in plans.geometry]
for i in range(NP):                                                    # recouvrement des limites elles-memes
    for j in plans.sindex.query(fp_list[i], predicate="intersects"):
        j = int(j)
        if j <= i: continue
        x = fp_list[i].intersection(fp_list[j])
        if x.area > 1.0: pair_pieces.setdefault((i, j), []).append(x)
zones = []
for (i, j), pieces in sorted(pair_pieces.items()):
    z = polys(unary_union([polys(p) for p in pieces if polys(p) is not None]))
    if z is None: continue
    z = polys(unary_union([g for g in (z.geoms if hasattr(z, "geoms") else [z]) if g.area >= 1.0]))
    if z is None or z.area < SEUIL_BAVURE_M2: continue
    b = z.bounds
    zones.append(dict(a=i, b=j, nom_a=plans.nom[i], nom_b=plans.nom[j], area_m2=z.area, n_lots=pair_n.get((i, j), 0), n_identiques=pair_same.get((i, j), 0),
                      pct_a=100 * z.area / fp_list[i].area, pct_b=100 * z.area / fp_list[j].area, geometry=z))
zones = gpd.GeoDataFrame(zones, geometry="geometry", crs=32630) if zones else gpd.GeoDataFrame({"a": [], "b": []}, geometry=[], crs=32630)
mineurs = zones[zones.area_m2 < SEUIL_CHEVAUCHEMENT_M2].copy() if len(zones) else zones.copy()
zones = zones[zones.area_m2 >= SEUIL_CHEVAUCHEMENT_M2].reset_index(drop=True) if len(zones) else zones
print("Chevauchements entre lotissements montrés : %d (zones d'au moins %.1f ha)" % (len(zones), SEUIL_CHEVAUCHEMENT_M2 / 1e4))
for z in zones.sort_values("area_m2", ascending=False).itertuples():
    print("  %-34s x %-34s %8.2f ha  (%d lots, dont %d identiques)" % (z.nom_a[:34], z.nom_b[:34], z.area_m2 / 1e4, z.n_lots, z.n_identiques))
if len(mineurs):
    print("Zones plus petites, non montrées (couche chevauchements_mineurs) : %d" % len(mineurs))
    for z in mineurs.sort_values("area_m2", ascending=False).itertuples():
        print("  %-34s x %-34s %8.2f ha" % (z.nom_a[:34], z.nom_b[:34], z.area_m2 / 1e4))

# ------------------------------------------------------------------ communes
COMM = None
for path, layer in COMMUNES_SRC:
    if path.exists():
        try: COMM = {r.commune: r.geometry for r in read(layer, path).itertuples()}; break
        except Exception: pass
if COMM is None: sys.exit("Couche des communes introuvable (communes.gpkg).")
tr = pyproj.Transformer.from_crs(32630, 4326, always_xy=True)
to_ll = lambda g: transform(tr.transform, g)
sp = None
if SOUSPREF.exists():
    try: sp = gpd.read_file(SOUSPREF)
    except Exception: sp = None

# ------------------------------------------------------------------ plans
out_plans = []
for idx, r in plans.iterrows():
    L = lots[lots.pos_plan == idx]; I = ilots[ilots.pos == idx]
    allg = list(L.geometry) + [r.geometry]
    bb = unary_union(allg).bounds
    georef = bool(bb[0] > 100000 and bb[2] < 900000 and bb[1] > 300000 and bb[3] < 1300000)
    fp = fp_list[idx]
    cm = COMM.get(r.commune)
    inc = round(100 * fp.intersection(cm).area / fp.area, 1) if (georef and cm is not None and fp is not None and fp.area) else 0.0
    status = "Non géoréférencé" if not georef else ("Dans la zone" if inc >= 95 else ("Partiellement dans la zone" if inc >= 50 else "Hors zone"))
    sps = clean(r.get("sousprefecture"))
    if not sps and georef and sp is not None:
        f4 = to_ll(fp); best = 0
        for k in sp.sindex.query(f4, predicate="intersects"):
            a = sp.geometry.iloc[k].intersection(f4).area
            if a > best: best, sps = a, sp.nmspref.iloc[k]
    d = clean(r.get("date"))
    chev = []
    for z in zones.itertuples():
        if idx not in (z.a, z.b): continue
        other = z.b if idx == z.a else z.a; bz = to_ll(z.geometry).bounds
        chev.append(dict(id=int(other), ha=round(z.area_m2 / 1e4, 2), m2=round(z.area_m2), pct=round(z.pct_a if idx == z.a else z.pct_b, 1), n=int(z.n_lots), same=int(z.n_identiques),
                         bbox=[round(v, 6) for v in bz]))
    chev.sort(key=lambda c: -c["ha"])
    num = int(L.num_lot.notna().sum())
    p = dict(id=idx, commune=r.commune, nom=clean(r.nom) or "(sans nom)", localite=clean(r.get("localite")) or "", section=clean(r.get("section")),
             sousprefecture=sps or "—", departement=None, region=None, type=clean(r.get("type")) or "—", type_detail=clean(r.get("type_detail")),
             conforme=yesno(r.get("conforme")), polygonale=yesno(r.get("polygonale")),
             date=d, date_iso=date_iso(d), dresse=None, numero=clean(r.get("numero")), echelle=clean(r.get("echelle")), crs=clean(r.get("crs")) or "Non indiqué", crs_raw=None,
             sup_decl=None if r.get("sup_decl") != r.get("sup_decl") else r.get("sup_decl"), sup_excel=clean(r.get("sup_excel")), source=clean(r.get("source")) or "", fichier=clean(r.get("fichier")) or "",
             n_lots=len(L), n_ilots=len(I), n_lots_raw=int(raw_by.get(idx, 0)), n_lots_art=int(art_by.get(idx, 0)), n_ilots_art=0, n_lots_num=num,
             area_lots_ha=round(float(L.area_lot.sum()) / 1e4, 2), area_limite_ha=round(fp.area / 1e4, 2), limite_source=clean(r.get("limite_source")) or "plan", georef=georef,
             crs_assumed=bool(int(r.crs_assumed)) if r.get("crs_assumed") == r.get("crs_assumed") and r.get("crs_assumed") is not None else False, in_commune_pct=inc, statut_zone=status,
             overlap_lots_m2=round(ov_in_m2.get(idx, 0.0), 1), overlap_lots_n=ov_in_n.get(idx, 0), invalid=0,
             chevauche=chev, chev_n=len(chev), chev_ha=round(sum(c["ha"] for c in chev), 2))
    if p["type"] not in ("Régularisation", "Normale"): print("  ! type de plan inattendu pour %s : %s" % (p["nom"], p["type"]))
    if p["conforme"] is None: print("  ! conformité non renseignée pour %s" % p["nom"])
    if georef:
        b = to_ll(fp).bounds; p["bbox"] = [round(b[0], 6), round(b[1], 6), round(b[2], 6), round(b[3], 6)]
    out_plans.append(p)


def rnd(c): return round(c, 6) if isinstance(c, float) else [rnd(x) for x in c]


def feat(geom, props):
    if geom.geom_type == "MultiPolygon" and len(geom.geoms) == 1: geom = geom.geoms[0]
    g = mapping(set_precision(to_ll(set_precision(geom, 0.01)), 1e-6))
    return {"type": "Feature", "properties": props, "geometry": {"type": g["type"], "coordinates": rnd(g["coordinates"])}}


def js(name, var, obj):
    s = "window.%s=%s;" % (var, json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    (WEB / name).write_text(s, encoding="utf-8"); print("  %-24s %5.2f Mo" % (name, len(s.encode("utf-8")) / 1e6))


FC = lambda f: {"type": "FeatureCollection", "features": f}
print("Ecriture dans", WEB)
for com in ("MARCORY", "BINGERVILLE"):
    ids = [p["id"] for p in out_plans if p["commune"] == com and p["georef"]]
    lf = [feat(r.geometry, {"p": int(r.pos_plan), "n": r.num_lot, "i": r.ilot_n}) for r in lots.itertuples() if r.pos_plan in ids]
    nf = [feat(r.geometry, {"p": int(r.pos), "n": r.nom_ilot}) for r in ilots.itertuples() if r.pos in ids]
    lm = [feat(fp_list[i], {"p": i, "name": out_plans[i]["nom"], "c": out_plans[i]["conforme"]}) for i in ids]
    print("%s : %d lots, %d îlots, %d limites" % (com.title(), len(lf), len(nf), len(lm)))
    js("lots_%s.js" % com.lower(), "LOTS_" + com, FC(lf)); js("ilots_%s.js" % com.lower(), "ILOTS_" + com, FC(nf)); js("limites_%s.js" % com.lower(), "LIMITES_" + com, FC(lm))
js("communes.js", "COMMUNES", FC([feat(g, {"name": c}) for c, g in COMM.items()]))
js("chevauchements.js", "CHEVAUCHEMENTS", FC([feat(z.geometry, {"a": int(z.a), "b": int(z.b), "ha": round(z.area_m2 / 1e4, 2), "label": "%s × %s" % (z.nom_a, z.nom_b)}) for z in zones.itertuples()]))


def label_point(z):                      # une seule etiquette par zone, posee dans sa plus grande partie
    return max(list(z.geoms) if hasattr(z, "geoms") else [z], key=lambda g: g.area).representative_point()


js("chevauchements_etiquettes.js", "CHEVAUCHEMENTS_PTS", FC([feat(label_point(z.geometry), {"a": int(z.a), "b": int(z.b), "na": z.nom_a, "nb": z.nom_b}) for z in zones.itertuples()]))
js("plans.js", "PLANS", out_plans)

# ------------------------------------------------------------------ couche de controle pour QGIS (facultative)
try:
    syn = plans.copy()
    for k in ("type", "conforme", "polygonale"): syn[k] = [out_plans[i][k] for i in range(NP)]
    syn["n_lots"] = [p["n_lots"] for p in out_plans]; syn["n_ilots"] = [p["n_ilots"] for p in out_plans]
    syn["area_ha"] = [p["area_limite_ha"] for p in out_plans]
    syn["chevauche"] = ["; ".join("%s (%.2f ha)" % (out_plans[c["id"]]["nom"], c["ha"]) for c in p["chevauche"]) for p in out_plans]
    syn["geometry"] = fp_list
    gpd.GeoDataFrame(syn, geometry="geometry", crs=32630).to_file(CONTROLE, layer="plans_synthese", driver="GPKG")
    il = ilots.copy(); il["plan_id"] = [int(plans.plan_id[p]) for p in il.pos]; il["nom_plan"] = [plans.nom[p] for p in il.pos]; il["surface_m2"] = il.geometry.area.round(1)
    il.drop(columns="pos").to_file(CONTROLE, layer="ilots_reconstitues", driver="GPKG")
    zz = zones.copy()
    if len(zz): zz["area_ha"] = (zz.area_m2 / 1e4).round(3); zz["plan_a"] = [int(plans.plan_id[i]) for i in zz.a]; zz["plan_b"] = [int(plans.plan_id[i]) for i in zz.b]
    zz.drop(columns=["a", "b"], errors="ignore").to_file(CONTROLE, layer="chevauchements", driver="GPKG")
    mm = mineurs.copy()
    if len(mm): mm["area_ha"] = (mm.area_m2 / 1e4).round(3); mm["plan_a"] = [int(plans.plan_id[i]) for i in mm.a]; mm["plan_b"] = [int(plans.plan_id[i]) for i in mm.b]
    try: mm.drop(columns=["a", "b"], errors="ignore").to_file(CONTROLE, layer="chevauchements_mineurs", driver="GPKG")
    except Exception: pass                                    # couche vide : rien a ecrire
    print("  couche de controle :", CONTROLE.name)
except Exception as e:
    print("  (couche de controle non écrite : %s)" % e)

ng = sum(1 for p in out_plans if not p["georef"])
print("Terminé : %d plans (%d non géoréférencé%s), %d non conforme(s), %d plan(s) en chevauchement. Recharger index.html dans le navigateur (Ctrl+F5)." % (
    len(out_plans), ng, "s" if ng > 1 else "", sum(1 for p in out_plans if p["conforme"] == "non"), sum(1 for p in out_plans if p["chev_n"])))
