# ============================================================
# Import de recettes via JSON-LD (schema.org/Recipe) — Google Colab
# Produit recettes_marmiton.json, compatible avec generateur-recettes.html
# ============================================================
!pip -q install requests beautifulsoup4 pandas

import json, re, time, random
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus

BASE = "https://www.marmiton.org"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept-Language": "fr-BE,fr;q=0.9",
}
session = requests.Session()
session.headers.update(HEADERS)


def get_soup(url: str) -> BeautifulSoup:
    r = session.get(url, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


# ---------- Utilitaires ----------
def nettoyer_nom(nom):
    nom = (nom or "").replace(" ", " ")
    return re.sub(r"\s*:\s*la meilleure recette\s*$", "", nom, flags=re.I).strip()


def iso_duration_to_min(d):
    """PT1H30M -> 90 ; None si absent."""
    if not d or not isinstance(d, str):
        return None
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", d)
    if not m:
        return None
    j, h, mi = (int(x) if x else 0 for x in m.groups())
    return j * 1440 + h * 60 + mi


def find_recipe_obj(data):
    """Cherche récursivement l'objet @type == Recipe (dict, liste ou @graph)."""
    if isinstance(data, list):
        for item in data:
            r = find_recipe_obj(item)
            if r:
                return r
    elif isinstance(data, dict):
        t = data.get("@type")
        if t == "Recipe" or (isinstance(t, list) and "Recipe" in t):
            return data
        if "@graph" in data:
            return find_recipe_obj(data["@graph"])
    return None


def flatten_instructions(instr):
    """recipeInstructions peut être str, liste de str, HowToStep ou HowToSection."""
    steps = []
    if isinstance(instr, str):
        steps = [s.strip() for s in re.split(r"\n+", instr) if s.strip()]
    elif isinstance(instr, list):
        for it in instr:
            if isinstance(it, str):
                steps.append(it.strip())
            elif isinstance(it, dict):
                if it.get("@type") == "HowToSection":
                    steps.extend(flatten_instructions(it.get("itemListElement", [])))
                else:
                    txt = it.get("text") or it.get("name")
                    if txt:
                        steps.append(txt.strip())
    return steps


def first_image(img):
    if isinstance(img, str):
        return img
    if isinstance(img, list) and img:
        return first_image(img[0])
    if isinstance(img, dict):
        return img.get("url")
    return None


# ---------- Extraction d'une recette ----------
def scrape_recipe(url: str):
    soup = get_soup(url)
    recipe = None
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        recipe = find_recipe_obj(data)
        if recipe:
            break

    if not recipe:
        print(f"⚠ Pas de JSON-LD Recipe : {url}")
        return None

    rating = recipe.get("aggregateRating") or {}
    yld = recipe.get("recipeYield")
    if isinstance(yld, list):
        yld = yld[0] if yld else None

    return {
        "url": url,
        "source": re.sub(r"^www\.", "", url.split("/")[2]),
        "nom": nettoyer_nom(recipe.get("name")),
        "categorie": recipe.get("recipeCategory"),
        "cuisine": recipe.get("recipeCuisine"),
        "portions": yld,
        "prep_min": iso_duration_to_min(recipe.get("prepTime")),
        "cuisson_min": iso_duration_to_min(recipe.get("cookTime")),
        "total_min": iso_duration_to_min(recipe.get("totalTime")),
        "note": rating.get("ratingValue"),
        "nb_avis": rating.get("ratingCount") or rating.get("reviewCount"),
        "ingredients": recipe.get("recipeIngredient", []),
        "etapes": flatten_instructions(recipe.get("recipeInstructions", [])),
        "mots_cles": recipe.get("keywords"),
        "image": first_image(recipe.get("image")),
    }


# ---------- Recherche Marmiton par mot-clé ----------
def search_recipes(query: str, max_results: int = 10):
    url = f"{BASE}/recettes/recherche.aspx?aqt={quote_plus(query)}"
    soup = get_soup(url)
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/recettes/recette_" in href:
            full = urljoin(BASE, href.split("?")[0])
            if full not in links:
                links.append(full)
        if len(links) >= max_results:
            break
    return links


def import_recipes(query: str, max_results: int = 10, pause=(1.5, 3.0)):
    urls = search_recipes(query, max_results)
    print(f"{len(urls)} recettes trouvées pour « {query} »")
    out = []
    for i, u in enumerate(urls, 1):
        try:
            r = scrape_recipe(u)
            if r:
                out.append(r)
                print(f"[{i}/{len(urls)}] ✓ {r['nom']}")
        except requests.RequestException as e:
            print(f"[{i}/{len(urls)}] ✗ {u} → {e}")
        time.sleep(random.uniform(*pause))   # politesse envers le serveur
    return out


def generer(recettes, avec=(), sans=(), max_min=None, n=3):
    """Propose n recettes contenant 'avec', excluant 'sans', sous max_min minutes."""
    def ok(r):
        txt = " ".join(r["ingredients"]).lower()
        if any(x.lower() not in txt for x in avec):
            return False
        if any(x.lower() in txt for x in sans):
            return False
        if max_min and (r["total_min"] or 9999) > max_min:
            return False
        return True
    candidats = [r for r in recettes if ok(r)]
    candidats.sort(key=lambda r: float(r["note"] or 0), reverse=True)
    return candidats[:n] if len(candidats) <= n else random.sample(candidats[:n * 3], n)


# ============================================================
# Utilisation
# ============================================================
recettes = import_recipes("blanquette", max_results=8)

with open("recettes_marmiton.json", "w", encoding="utf-8") as f:
    json.dump(recettes, f, ensure_ascii=False, indent=2)

df = pd.DataFrame(recettes)
if not df.empty:
    df["nb_ingredients"] = df["ingredients"].str.len()
    display(df[["nom", "note", "nb_avis", "portions", "total_min", "nb_ingredients"]])

for r in generer(recettes, avec=["veau"], sans=["crème"], max_min=180):
    print(f"{r['nom']} — {r['note']}/5 — {r['total_min']} min — {r['url']}")
