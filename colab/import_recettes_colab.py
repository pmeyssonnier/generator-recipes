# ============================================================
# Import de recettes — Google Colab
# Réutilise le code de serveur_recettes.py (même extraction JSON-LD, mêmes
# sources, mêmes règles : robots.txt, pause entre requêtes, sites autorisés).
# Produit recettes.json, compatible avec generateur-recettes.html.
# ============================================================
import os
import random
import unicodedata
import urllib.request

URL_MODULE = "https://raw.githubusercontent.com/pmeyssonnier/generator-recipes/main/serveur_recettes.py"
if not os.path.exists("serveur_recettes.py"):          # déjà présent : version locale utilisée
    urllib.request.urlretrieve(URL_MODULE, "serveur_recettes.py")

import serveur_recettes as srv  # noqa: E402  (le dossier courant contient le module)

# La base (recettes.json) est lue et écrite dans le dossier du module (= dossier courant du notebook).
scrape_recipe = srv.scrape_recipe          # url -> dict recette (lève ValueError si pas de JSON-LD Recipe)


def _norm(s):
    """Minuscules sans accents : « Crème » → « creme »."""
    return unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().lower()


def _note(r):
    """Note en nombre, même écrite « 4,5 » ; 0 si absente."""
    try:
        return float(str(r.get("note") or 0).replace(",", "."))
    except ValueError:
        return 0.0


# ---------- Recherche et import ----------
def search_recipes(query: str, max_results: int = 10, source: str = "marmiton"):
    """URL des recettes trouvées. Sources : voir SOURCES (marmiton, ptitchef…)."""
    return [x["url"] for x in srv.search_recipes(query, max_results, source)]


def _importer(urls, sauvegarder=True):
    out = []
    for i, u in enumerate(urls, 1):
        try:
            r = scrape_recipe(u)
        except (srv.AccesInterdit, ValueError, OSError) as e:   # OSError : HTTPError, URLError, délai
            print(f"[{i}/{len(urls)}] ✗ {u} → {type(e).__name__} : {e}")
            continue
        out.append(r)
        if sauvegarder:
            srv.ajouter_base(r)          # fusionne dans recettes.json (par URL), comme le serveur
        print(f"[{i}/{len(urls)}] ✓ {r['nom']}")
    return out


def import_recipes(query: str, max_results: int = 10, source: str = "marmiton"):
    """Recherche puis importe. Les recettes sont ajoutées à recettes.json et renvoyées."""
    urls = search_recipes(query, max_results, source)
    print(f"{len(urls)} recettes trouvées pour « {query} » ({source})")
    return _importer(urls)


def import_url(url: str):
    """Importe une recette à partir de son URL (site de la liste SITES)."""
    if not srv.url_autorisee(url):
        raise ValueError(f"Site non autorisé : {srv.domaine(url)} (voir SITES dans serveur_recettes.py)")
    return _importer([url])


def import_page(url: str, max_results: int = 100):
    """Importe les recettes listées sur une page de sélection
    (chronique Ricardo, page thématique, catégorie…)."""
    if not srv.url_autorisee(url):
        raise ValueError(f"Site non autorisé : {srv.domaine(url)} (voir SITES dans serveur_recettes.py)")
    urls = [x["url"] for x in srv.lister_page(url, max_results)]
    print(f"{len(urls)} recettes listées sur {url}")
    return _importer(urls)


def charger_base():
    """Toutes les recettes de recettes.json."""
    return srv.lire_base()


def generer(recettes, avec=(), sans=(), max_min=None, n=3):
    """Propose n recettes contenant 'avec', excluant 'sans', sous max_min minutes.
    Comparaison sans accents ni majuscules, comme dans l'interface."""
    def ok(r):
        txt = _norm(" ".join(r.get("ingredients") or []))
        if any(_norm(x) not in txt for x in avec):
            return False
        if any(_norm(x) in txt for x in sans):
            return False
        if max_min and (r.get("total_min") or 9999) > max_min:
            return False
        return True
    candidats = [r for r in recettes if ok(r)]
    candidats.sort(key=_note, reverse=True)
    return candidats[:n] if len(candidats) <= n else random.sample(candidats[:n * 3], n)


# ============================================================
# Utilisation
# ============================================================
if __name__ == "__main__":
    import pandas as pd             # préinstallé sur Colab ; inutile pour les fonctions ci-dessus

    print("Sources de recherche :", ", ".join(srv.SOURCES))
    recettes = import_recipes("blanquette", max_results=8)       # source="ptitchef" pour PtitChef
    # import_url("https://www.marmiton.org/recettes/recette_....aspx")
    # import_page("https://www.ricardocuisine.com/...")           # page qui liste plusieurs recettes

    df = pd.DataFrame(recettes)
    if not df.empty:
        df["nb_ingredients"] = df["ingredients"].str.len()
        colonnes = ["nom", "note", "nb_avis", "portions", "total_min", "nb_ingredients"]
        try:
            display(df[colonnes])          # noqa: F821  (fourni par Colab / Jupyter)
        except NameError:
            print(df[colonnes])

    for r in generer(charger_base(), avec=["veau"], sans=["crème"], max_min=180):
        print(f"{r['nom']} — {r['note']}/5 — {r['total_min']} min — {r['url']}")
