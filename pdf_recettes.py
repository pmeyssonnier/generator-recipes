"""Extraction de recettes depuis un PDF de « fiches recettes » (kit repas : eFarmz…).

Une page de détail par recette : durées, tableau de quantités « 1p … 6p », étapes numérotées ;
la photo est celle de la page (ou de la page photo qui la précède). Les pages sans tableau
(couverture, photo) ne sont pas des recettes.

Dépendance facultative : pdfplumber (pip install pdfplumber). Sans lui, le reste de l'application
fonctionne ; `disponible()` dit si l'extraction est possible.
Utilisé par serveur_recettes.py (source « eFarmz ») et réutilisable seul :
    python pdf_recettes.py fichier.pdf [personnes]
"""
import base64
import importlib.util
import io
import json
import re
import statistics
import sys
import unicodedata

PERSONNES = 2                           # quantités pour N personnes (colonne « Np » du tableau)
AVEC_IMAGES = True                      # joindre à chaque recette la photo trouvée dans le PDF
PHOTO_PAGE = "avant"                    # si la photo est sur sa propre page : "avant" ou "apres" la page de la recette
IMAGE_LARGEUR = 400                     # largeur de l'image en pixels (petite = base légère dans le navigateur)
IMAGE_QUALITE = 70                      # qualité JPEG (1-95)
MAX_PAGES = 400                         # un PDF plus long est refusé


class PdfIndisponible(Exception):
    """pdfplumber n'est pas installé."""


def disponible():
    return importlib.util.find_spec("pdfplumber") is not None


# ---------- Vocabulaire ----------
UNITES_POIDS = {"g", "kg", "ml", "cl", "dl", "l"}
UNITES_CUILLERE = {"càs": "c. à soupe", "cas": "c. à soupe", "càc": "c. à café", "cac": "c. à café"}
UNITES_NOMBRE = {"pc", "pcs", "pièce", "pièces", "piece", "pieces"}
UNITES_AUTRES = {"gousse": "gousse", "gousses": "gousse", "pincée": "pincée", "pincee": "pincée",
                 "botte": "botte", "branche": "branche", "tranche": "tranche", "sachet": "sachet"}
H_ASPIRES = ("haricot", "homard", "hareng", "hachis", "houmous", "hamburger", "hibiscus")
FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3}
RE_NOMBRE = re.compile(r"^(\d+(?:[.,]\d+)?|\d*[½¼¾⅓⅔]|\d+/\d+)$")
RE_DUREE = re.compile(r"^(?:(\d+)\s*h(?:\s*(\d+))?|(\d+)\s*(?:mn|min|minutes?))$", re.I)
CORRECTIONS = (("boeuf", "bœuf"), ("oeuf", "œuf"), ("coeur", "cœur"), ("soeur", "sœur"), ("noeud", "nœud"))


# ---------- Géométrie : mots, lignes ----------
def mots_de_la_page(page):
    from pdfplumber.utils import extract_words
    """Mots avec leur taille de police (arrondie) : les exposants (BE, (1)…) forment des mots à part."""
    chars = [dict(c, size=round(c["size"] * 2) / 2) for c in page.chars]
    mots = extract_words(chars, x_tolerance=2, y_tolerance=3, extra_attrs=["size"], keep_blank_chars=False)
    return [m for m in mots if m["text"].strip()]


def taille_dominante(mots, defaut=10):
    """Taille de police qui porte le plus de texte (le corps du texte, pas les titres ni les notes)."""
    poids = {}
    for m in mots:
        poids[m["size"]] = poids.get(m["size"], 0) + len(m["text"])
    return max(poids, key=poids.get) if poids else defaut


def est_puce(texte):
    """Puce de liste : • (ou son code interne « (cid:127) » selon la police) ou tout caractère isolé non alphanumérique."""
    return bool(re.fullmatch(r"\(cid:\d+\)|[•·▪◦‣\-–—*]", texte)) or (len(texte) == 1 and not texte.isalnum())


def lignes(mots, tol=3.5):
    """Regroupe des mots en lignes (même hauteur), de haut en bas ; chaque ligne triée de gauche à droite."""
    out = []
    for m in sorted(mots, key=lambda m: (m["top"], m["x0"])):
        if out and abs(out[-1]["top"] - m["top"]) <= tol:
            out[-1]["mots"].append(m)
        else:
            out.append({"top": m["top"], "mots": [m]})
    for ln in out:
        ln["mots"].sort(key=lambda m: m["x0"])
        ln["texte"] = " ".join(m["text"] for m in ln["mots"])
        ln["bottom"] = max(m["bottom"] for m in ln["mots"])
    return out


def trouver_entete(mots):
    """Ligne « 1p 2p … 6p » : {nombre de personnes: abscisse du centre de la colonne}."""
    for ln in lignes([m for m in mots if re.fullmatch(r"\d+p", m["text"])]):
        if len(ln["mots"]) >= 2:
            return ({int(m["text"][:-1]): (m["x0"] + m["x1"]) / 2 for m in ln["mots"]},
                    ln["top"], ln["bottom"], max(m["x1"] for m in ln["mots"]))
    return None


# ---------- Nombres et ingrédients ----------
def valeur(qte):
    if qte in FRACTIONS:
        return FRACTIONS[qte]
    m = re.fullmatch(r"(\d+)([½¼¾⅓⅔])", qte)
    if m:
        return int(m.group(1)) + FRACTIONS[m.group(2)]
    m = re.fullmatch(r"(\d+)/(\d+)", qte)
    if m:
        return int(m.group(1)) / int(m.group(2))
    return float(qte.replace(",", "."))


def avec_de(nom):
    """« de patates » / « d'ail » (élision devant une voyelle ou un h muet)."""
    debut = unicodedata.normalize("NFD", nom[:1].lower())[0] if nom else ""
    voyelle = debut in "aeiouy" and not nom.lower().startswith(("yaourt",))
    muet = debut == "h" and not nom.lower().startswith(H_ASPIRES)
    return f"d'{nom}" if voyelle or muet else f"de {nom}"


def formater(qte, unite, nom, non_fourni):
    nom = nom.strip()
    nom_min = nom[:1].lower() + nom[1:] if nom and not nom[:2].isupper() else nom
    if not qte:
        texte = nom
    elif unite in UNITES_POIDS:
        texte = f"{qte} {unite} {avec_de(nom_min)}"
    elif unite in UNITES_CUILLERE:
        texte = f"{qte} {UNITES_CUILLERE[unite]} {avec_de(nom_min)}"
    elif unite in UNITES_AUTRES:
        mot = UNITES_AUTRES[unite]
        mot = mot + "s" if valeur(qte) > 1 and not mot.endswith("s") else mot
        texte = f"{qte} {mot} {avec_de(nom_min)}"
    elif unite in UNITES_NOMBRE or not unite:
        texte = f"{qte} {nom_min}"
    else:
        texte = f"{qte} {unite} {avec_de(nom_min)}"
    return texte + (" (non fourni)" if non_fourni else "")


def duree(texte):
    m = RE_DUREE.match(texte.strip())
    if not m:
        return None
    if m.group(3):
        return int(m.group(3))
    return int(m.group(1)) * 60 + int(m.group(2) or 0)


def ligature(txt):
    """boeuf → bœuf, oeufs → œufs (le PDF écrit « oe » sans la ligature)."""
    for a, b in CORRECTIONS:
        txt = txt.replace(a, b).replace(a.capitalize(), b.capitalize())
    return txt


def phrase(txt):
    """TITRE EN MAJUSCULES → « Titre en majuscules », avec œ."""
    txt = ligature(re.sub(r"\s+", " ", txt).strip().lower())
    return txt[:1].upper() + txt[1:]


# ---------- Une page de détail → une recette ----------
def lire_page(page, numero, fichier, personnes):
    mots = mots_de_la_page(page)
    entete = trouver_entete(mots)
    if not entete:
        return None
    colonnes, haut_entete, bas_entete, x_max = entete
    alertes = []
    xs = sorted(colonnes.values())
    ecart = statistics.median(b - a for a, b in zip(xs, xs[1:])) if len(xs) > 1 else 40
    # frontière entre le panneau de gauche (durées, tableau) et la colonne de droite (titre, étapes) :
    # le grand rectangle de fond s'il existe, sinon le bord de la dernière colonne du tableau
    fonds = [r for r in page.rects if r["width"] > page.width * 0.25 and r["height"] > page.height * 0.5
             and r["x0"] < page.width * 0.1]
    frontiere = max(r["x1"] for r in fonds) if fonds else x_max + ecart / 2
    gauche = [m for m in mots if m["x0"] < frontiere]
    droite = [m for m in mots if m["x0"] >= frontiere]

    # --- colonne de gauche, au-dessus du tableau : durées, ustensiles, conservation
    duree_min, ustensiles, conservation = [], [], ""
    for ln in lignes([m for m in gauche if m["top"] < haut_entete - 1]):
        d = duree(ln["texte"])
        if d is not None:
            duree_min.append(d)
        elif re.search(r"cuisiner|conserv|dans les \d+ jours|consommer", ln["texte"], re.I):
            conservation = ln["texte"]
        else:
            ustensiles.append(ln["texte"])
    prep, cuisson = (duree_min + [None, None])[:2]
    if prep is None or cuisson is None:
        alertes.append(f"durées lues : {duree_min or 'aucune'} (attendu : préparation puis cuisson)")

    # --- notes de bas de tableau : « (1) Non fourni dans la box. »
    notes = {}
    bas_tableau = max([m["bottom"] for m in gauche], default=0) + 1
    for ln in lignes([m for m in gauche if m["top"] > bas_entete]):
        m = re.match(r"^\((\d+)\)\s*(.+)$", ln["texte"])
        if m:
            notes[m.group(1)] = m.group(2)
            bas_tableau = min(bas_tableau, ln["top"] - 1)

    # --- tableau : un bloc par puce « • », les quantités sont dans la colonne choisie
    zone = [m for m in gauche if bas_entete < m["top"] < bas_tableau]
    lignes_tableau = lignes(zone)
    puces = [ln for ln in lignes_tableau if est_puce(ln["mots"][0]["text"])]
    if len(puces) < 2 and len(lignes_tableau) > 1:                 # pas de puce lisible : on découpe aux grands écarts
        pas = [b["top"] - a["top"] for a, b in zip(lignes_tableau, lignes_tableau[1:])]
        petit = min(pas)
        puces = [lignes_tableau[0]] + [b for a, b in zip(lignes_tableau, lignes_tableau[1:]) if b["top"] - a["top"] > petit * 1.35]
    if personnes not in colonnes:
        proche = min(colonnes, key=lambda n: abs(n - personnes))
        alertes.append(f"pas de colonne {personnes}p : colonne {proche}p utilisée")
        personnes = proche
    x_col = colonnes[personnes]
    x_premiere = min(colonnes.values())
    taille_texte = taille_dominante(zone)
    ingredients = []
    for i, puce in enumerate(puces):
        haut = puce["top"] - 4
        bas = puces[i + 1]["top"] - 4 if i + 1 < len(puces) else bas_tableau
        bloc = [m for m in zone if haut <= m["top"] < bas]
        etiquette = [m for m in bloc if (m["x0"] + m["x1"]) / 2 < x_premiere - ecart / 2]
        nombres = [m for m in bloc if (m["x0"] + m["x1"]) / 2 >= x_premiere - ecart / 2 and RE_NOMBRE.match(m["text"])]
        qte = next((m["text"] for m in sorted(nombres, key=lambda m: m["top"]) if abs((m["x0"] + m["x1"]) / 2 - x_col) < ecart / 2), "")
        # exposants (BE, (1)…) : petits caractères ; le renvoi (n) indique une note
        non_fourni, morceaux = False, []
        for m in sorted(etiquette, key=lambda m: (round(m["top"] / 3), m["x0"])):
            t = m["text"].strip()
            if not t or est_puce(t) or t == "BE":                  # BE : origine belge (exposant)
                continue
            renvoi = re.fullmatch(r"\((\d+)\)", t)
            petit = m["size"] < taille_texte * 0.85
            if renvoi and (petit or t in {f"({k})" for k in notes}):
                non_fourni = non_fourni or bool(re.search(r"non fourni", notes.get(renvoi.group(1), ""), re.I))
            elif petit:
                continue                                      # BE (origine belge), etc.
            else:
                morceaux.append(t)
        texte = " ".join(morceaux)
        unite = ""
        m = re.search(r"\(([^()]{1,10})\)\s*$", texte)
        if m and qte:
            unite = m.group(1).strip().lower()
            texte = texte[:m.start()].strip()
        texte = re.sub(r"(\w)- (\w)", r"\1\2", texte)             # coupure de mot en fin de ligne
        if not texte:
            alertes.append(f"ligne du tableau sans libellé (y={puce['top']:.0f})")
            continue
        if not qte and any(RE_NOMBRE.match(m["text"]) for m in nombres):
            alertes.append(f"« {texte} » : pas de quantité dans la colonne {personnes}p")
        ingredients.append(ligature(formater(qte, unite, texte, non_fourni)))
    if not ingredients:
        alertes.append("aucun ingrédient lu dans le tableau")

    # --- colonne de droite : titre (grande police) puis étapes numérotées
    corps = taille_dominante([m for m in droite if m["top"] < page.height * 0.9])     # sans le pied de page
    titre = phrase(" ".join(ln["texte"] for ln in lignes([m for m in droite if m["size"] >= corps * 1.4])))
    texte_etapes = [m for m in droite if corps * 0.9 <= m["size"] <= corps * 1.15]     # exclut le pied de page
    etapes, courant, num_attendu = [], None, 1
    for ln in lignes(texte_etapes):
        premier = ln["mots"][0]["text"]
        suite = " ".join(m["text"] for m in ln["mots"])
        if re.fullmatch(r"\d+\.", premier):
            if int(premier[:-1]) != num_attendu:
                alertes.append(f"numérotation : « {premier} » après l'étape {num_attendu - 1}")
            num_attendu = int(premier[:-1]) + 1
            courant = [" ".join(m["text"] for m in ln["mots"][1:])]
            etapes.append(courant)
        elif courant is not None:
            courant.append(suite)
    def recoller(lignes_etape):
        out = ""
        for t in lignes_etape:
            out = (out[:-1] + t) if out.endswith("-") and t[:1].islower() else (out + " " + t if out else t)
        return re.sub(r"\s+", " ", out).strip()
    etapes = [ligature(recoller(e)) for e in etapes if recoller(e)]
    if not etapes:
        alertes.append("aucune étape lue")
    if not titre:
        titre = f"Recette page {numero}"
        alertes.append("titre introuvable")

    return {"nom": titre, "source": f"{fichier} p.{numero}", "portions": f"{personnes} personnes",
            "prep_min": prep, "cuisson_min": cuisson,
            "ustensiles": " ".join(ustensiles) or None, "conservation": conservation or None,
            "ingredients": ingredients, "etapes": etapes}, alertes


# ---------- Image d'illustration ----------
def image_de_page(page, largeur=IMAGE_LARGEUR, qualite=IMAGE_QUALITE):
    """Plus grande image de la page (au moins 8 % de sa surface), rendue en JPEG « data: » ; None s'il n'y en a pas."""
    surface = page.width * page.height
    aire = lambda im: (im["x1"] - im["x0"]) * (im["bottom"] - im["top"])
    candidates = [im for im in page.images if aire(im) >= 0.08 * surface]
    if not candidates:
        return None
    im = max(candidates, key=aire)
    zone = (max(im["x0"], 0), max(im["top"], 0), min(im["x1"], page.width), min(im["bottom"], page.height))
    if zone[2] - zone[0] < 10 or zone[3] - zone[1] < 10:
        return None
    dpi = max(36, min(300, largeur / ((zone[2] - zone[0]) / 72)))
    rendu = page.crop(zone).to_image(resolution=dpi).original.convert("RGB")
    tampon = io.BytesIO()
    rendu.save(tampon, "JPEG", quality=qualite, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")


# ---------- Programme ----------
def convertir(chemin, personnes=PERSONNES, avec_images=None):
    """(recettes, rapport) d'un PDF. rapport : [(numéro de page, recette, [alertes])].
    Lève PdfIndisponible (pdfplumber absent) ou ValueError (PDF illisible, trop long, sans texte)."""
    try:
        import pdfplumber
    except ImportError:
        raise PdfIndisponible("Extraction PDF indisponible : installe pdfplumber (pip install pdfplumber)") from None
    avec_images = AVEC_IMAGES if avec_images is None else avec_images
    recettes, rapport = [], []
    try:
        pdf = pdfplumber.open(chemin)
    except Exception as e:
        raise ValueError(f"PDF illisible ({type(e).__name__})") from None
    with pdf:
        pages = list(pdf.pages)
        if len(pages) > MAX_PAGES:
            raise ValueError(f"PDF trop long ({len(pages)} pages, maximum {MAX_PAGES})")
        if sum(len(p.extract_text() or "") for p in pages) < 20 * len(pages):
            raise ValueError("PDF sans texte (scan ou images seules) : l'OCR n'est pas pris en charge")
        fichier = re.split(r"[\\/]", chemin)[-1]
        lues = [lire_page(page, numero, fichier, personnes) for numero, page in enumerate(pages, 1)]
        for i, resultat in enumerate(lues):
            if resultat is None:
                continue                                       # page photo / couverture : pas une recette
            recette, alertes = resultat
            if avec_images:
                voisine = i - 1 if PHOTO_PAGE == "avant" else i + 1
                ordre = [i] + ([voisine] if 0 <= voisine < len(pages) and lues[voisine] is None else [])
                for j in ordre:                                # la page de la recette, puis sa page photo
                    try:
                        image = image_de_page(pages[j])
                    except Exception as e:                     # image illisible : la recette reste importée
                        image = None
                        alertes.append(f"image p.{j + 1} illisible ({type(e).__name__})")
                    if image:
                        recette["image"] = image
                        recette["image_page"] = j + 1
                        break
                else:
                    alertes.append("aucune image trouvée")
            recettes.append(recette)
            rapport.append((i + 1, recette, alertes))
    return recettes, rapport


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage : python pdf_recettes.py fichier.pdf [personnes]")
    try:
        recettes, rapport = convertir(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else PERSONNES)
    except (PdfIndisponible, ValueError) as e:
        sys.exit(f"✗ {e}")
    for numero, r, alertes in rapport:
        print(f"{'⚠' if alertes else '✓'} p.{numero:<3} {r['nom']} — {len(r['ingredients'])} ingrédients, "
              f"{len(r['etapes'])} étapes" + (f", image p.{r['image_page']}" if r.get("image") else ""))
        for a in alertes:
            print(f"        → {a}")
    sortie = re.sub(r"\.pdf$", "", sys.argv[1], flags=re.I) + ".json"
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump(recettes, f, ensure_ascii=False, indent=2)
    print(f"\n💾 {sortie} écrit ({len(recettes)} recettes).")
