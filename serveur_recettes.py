#!/usr/bin/env python3
"""
serveur_recettes.py — Serveur local du générateur de recettes (stdlib uniquement)

Lancement :
  python serveur_recettes.py                 → http://localhost:8765 (ce poste uniquement)
  python serveur_recettes.py --lan           → accessible depuis le Wi-Fi (téléphone, tablette…)
  python serveur_recettes.py --no-browser    → ne pas ouvrir le navigateur automatiquement
Port personnalisé : variable d'environnement RECETTES_PORT (défaut 8765)
Compatible Windows, Linux, macOS et Android (Termux).

Les recettes importées sont enregistrées dans recettes.json,
dans le même dossier que ce script (même format que le script Colab).
"""
import html, ipaddress, json, os, re, shutil, socket, subprocess, sys, threading, time, unicodedata, webbrowser, zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

PORT = int(os.environ.get("RECETTES_PORT", 8765))
LAN = "--lan" in sys.argv          # écoute sur le réseau local (accès depuis un autre appareil)
HOST = "0.0.0.0" if LAN else "127.0.0.1"
DIR = os.path.dirname(os.path.abspath(__file__))
NOMS_PAGE = ("generateur-recettes.html", "generateur_recettes.html")
BASE_FILE = os.path.join(DIR, "recettes.json")
DOSSIER_PDF = os.path.join(DIR, "eFarmz")                        # PDF de recettes déposés ici (source « eFarmz »)
ANCIEN_BASE_FILE = os.path.join(DIR, "recettes_marmiton.json")   # ancien nom, migré au lancement
BASE = "https://www.marmiton.org"
PAUSE = 1.5  # secondes minimum entre deux requêtes sortantes
# Le serveur s'identifie (au lieu d'imiter un navigateur) et applique les règles du robots.txt
# visant ce nom. Si un site refuse cet identifiant : RECETTES_USER_AGENT="Mozilla/5.0 …"
VERSION = "1.0.0"       # version de l'application (SemVer) ; voir CHANGELOG.md. Même valeur dans generateur-recettes.html
API_VERSION = 2          # 2 : l'import se fait en POST (X-Recettes) ; l'interface s'adapte aux serveurs plus anciens
ROBOTS_NOM = "RecettesPerso"
USER_AGENT = (os.environ.get("RECETTES_USER_AGENT", "").strip() or
              f"Mozilla/5.0 (compatible; {ROBOTS_NOM}/{VERSION}; +https://github.com/pmeyssonnier/generator-recipes)")
MAX_OCTETS = 5 * 1024 * 1024      # taille maximale d'une page téléchargée (après décompression)
ROBOTS_TTL = 3600                 # secondes de validité d'un robots.txt en mémoire
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "fr-BE,fr;q=0.9",
    "Accept-Encoding": "gzip",
}
LD_RE = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                   re.DOTALL | re.IGNORECASE)
SUFFIXE_RE = re.compile(r"\s*:\s*la meilleure recette\s*$", re.IGNORECASE)

# Sites autorisés pour l'import par URL (ajoute-en ici si besoin)
SITES = {
    "marmiton.org", "750g.com", "cuisineaz.com", "journaldesfemmes.fr", "ricardocuisine.com",
    "ptitchef.com", "cuisine-libre.org", "jamieoliver.com", "bbcgoodfood.com", "allrecipes.com",
    "chefkoch.de", "dagelijksekost.vrt.be", "24kitchen.nl", "24kitchen.be", "ah.nl", "njam.tv",
}

# Origines web autorisées à appeler l'API (en plus de la page servie par ce serveur).
# Ajouts possibles via RECETTES_ORIGINES="https://exemple.org,null"
# ("null" = page ouverte en file:// — non autorisé par défaut, car les iframes
#  sandboxées de n'importe quel site envoient aussi Origin: null).
ORIGINES = {"https://pmeyssonnier.github.io"}
ORIGINES |= {o.strip().rstrip("/") for o in os.environ.get("RECETTES_ORIGINES", "").split(",") if o.strip()}

# Noms d'hôte acceptés dans l'en-tête Host (protège du DNS rebinding : un site pirate dont le
# nom pointe vers 127.0.0.1 enverrait un Host inconnu). Les adresses IP locales sont acceptées
# (loopback ; + réseau privé avec --lan). Autres noms : RECETTES_HOTES="monpc.local,autre"
HOTES = {"localhost"}
HOTES |= {h.strip().lower() for h in os.environ.get("RECETTES_HOTES", "").split(",") if h.strip()}

_net_lock = threading.Lock()
_file_lock = threading.Lock()
_last = [0.0]
_cache = {}
MAX_CACHE = 200          # pages gardées en mémoire


# ---------------- Page HTML ----------------
def trouver_page():
    """Accepte generateur-recettes.html, generateur_recettes.html, sinon le premier .html du dossier."""
    for nom in NOMS_PAGE:
        if os.path.exists(os.path.join(DIR, nom)):
            return nom
    autres = sorted(f for f in os.listdir(DIR) if f.lower().endswith((".html", ".htm")))
    return autres[0] if autres else None


# ---------------- Réseau ----------------
class AccesInterdit(Exception):
    """Le robots.txt du site interdit l'accès automatisé à cette page."""


class ReponseTropGrosse(ValueError):
    """La page téléchargée dépasse MAX_OCTETS."""


_robots = {}          # racine du site -> (RobotFileParser, expiration)
_robots_lock = threading.Lock()


def robots_autorise(url):
    """Respecte le robots.txt du site (règles visant RecettesPerso, sinon « * »).
    Conservé ROBOTS_TTL secondes. Un robots.txt injoignable ou en erreur 5xx interdit l'accès
    (RFC 9309), sans être mémorisé : la requête suivante réessaie."""
    p = urlparse(url)
    racine = f"{p.scheme}://{p.netloc}"
    with _robots_lock:
        entree = _robots.get(racine)
    if entree is None or entree[1] < time.time():
        rp = RobotFileParser()
        try:
            data, charset = telecharger(racine + "/robots.txt")
            rp.parse(data.decode(charset, errors="replace").splitlines())
        except HTTPError as e:
            if e.code in (401, 403):
                rp.disallow_all = True      # robots.txt protégé : on s'abstient
            elif e.code >= 500:
                raise AccesInterdit(f"Le robots.txt de {domaine(url)} est indisponible (HTTP {e.code}) : "
                                    "accès refusé par prudence, réessaie plus tard") from None
            else:
                rp.allow_all = True         # pas de robots.txt (404…) : aucune restriction
        except (AccesInterdit, ValueError):
            raise
        except OSError as e:                # URLError, délai dépassé…
            raise AccesInterdit(f"Le robots.txt de {domaine(url)} est injoignable ({type(e).__name__}) : "
                                "accès refusé par prudence, réessaie plus tard") from None
        entree = (rp, time.time() + ROBOTS_TTL)
        with _robots_lock:
            _robots[racine] = entree
    return entree[0].can_fetch(ROBOTS_NOM, url)


def lire_limite(r):
    """Corps de la réponse (décompressé si gzip) sans dépasser MAX_OCTETS, ni compressé ni décompressé."""
    data = r.read(MAX_OCTETS + 1)
    if len(data) > MAX_OCTETS:
        raise ReponseTropGrosse(f"Page trop volumineuse (plus de {MAX_OCTETS // 1024 // 1024} Mo)")
    if r.headers.get("Content-Encoding") == "gzip":
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = d.decompress(data, MAX_OCTETS + 1)
        if len(data) > MAX_OCTETS or d.unconsumed_tail:
            raise ReponseTropGrosse(f"Page trop volumineuse (plus de {MAX_OCTETS // 1024 // 1024} Mo décompressée)")
    return data


class _SansRedirection(HTTPRedirectHandler):
    """Les redirections sont suivies à la main (voir telecharger) pour être revalidées."""
    def redirect_request(self, *a, **k):
        return None


_opener = build_opener(_SansRedirection)
MAX_SAUTS = 5
REDIRECTIONS = (301, 302, 303, 307, 308)


def telecharger(url, timeout=20, _sauts=0):
    """Téléchargement brut (octets, charset), avec robots.txt et pause entre requêtes.
    Chaque redirection est revalidée (site autorisé, pas de retour en http, robots.txt)."""
    if not url.endswith("/robots.txt") and not robots_autorise(url):
        raise AccesInterdit(f"{domaine(url)} n'autorise pas l'accès automatisé à cette page (robots.txt)")
    cible = None
    with _net_lock:
        wait = PAUSE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            with _opener.open(Request(url, headers=HEADERS), timeout=timeout) as r:
                data = lire_limite(r)
                charset = r.headers.get_content_charset() or "utf-8"
        except HTTPError as e:
            if e.code not in REDIRECTIONS or not e.headers.get("Location"):
                raise
            cible = urljoin(url, e.headers["Location"])
        finally:
            _last[0] = time.time()
    if cible is None:
        return data, charset
    # (hors verrou : robots_autorise() retélécharge via ce même verrou)
    if _sauts >= MAX_SAUTS:
        raise AccesInterdit("Trop de redirections")
    if not url_autorisee(cible) or (url.startswith("https:") and not cible.startswith("https:")):
        raise AccesInterdit(f"Redirection refusée vers {cible[:120]}")
    return telecharger(cible, timeout, _sauts + 1)


def fetch(url):
    if url in _cache:
        return _cache[url]
    data, charset = telecharger(url)
    txt = data.decode(charset, errors="replace")
    if len(_cache) >= MAX_CACHE:
        _cache.pop(next(iter(_cache)))        # plus ancienne entrée
    _cache[url] = txt
    return txt


def domaine(url):
    return urlparse(url).netloc.lower().split(":")[0]


def url_autorisee(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    h = domaine(url)
    return any(h == d or h.endswith("." + d) for d in SITES)


def source_de(url):
    h = domaine(url)
    return next((d for d in SITES if h == d or h.endswith("." + d)), h)


# ---------------- Parsing (identique au script Colab) ----------------
def sans_accents(texte):
    """Minuscules sans accents : « Crème » → « creme », « Œufs » → « oeufs » (filtres)."""
    texte = str(texte or "").lower().replace("œ", "oe").replace("æ", "ae")
    return unicodedata.normalize("NFD", texte).encode("ascii", "ignore").decode().strip()


def nettoyer_nom(nom):
    """Retire le suffixe SEO « : la meilleure recette » ajouté par Marmiton."""
    nom = html.unescape(nom or "").replace(" ", " ")
    return SUFFIXE_RE.sub("", nom).strip()


def iso_duration_to_min(d):
    if not d or not isinstance(d, str):
        return None
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:\d+(?:[.,]\d+)?S)?)?", d.strip().upper())
    if not m:
        return None
    j, h, mi = (int(x) if x else 0 for x in m.groups())
    return (j * 1440 + h * 60 + mi) or None      # PT0S, PT45S… : durée inconnue, pas « 0 minute »


def find_recipe_obj(data):
    if isinstance(data, list):
        for it in data:
            r = find_recipe_obj(it)
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
                        steps.append(html.unescape(txt.strip()))
    return steps


def first_image(img):
    if isinstance(img, str):
        return img
    if isinstance(img, list) and img:
        return first_image(img[0])
    if isinstance(img, dict):
        return img.get("url")
    return None


def scrape_recipe(url):
    page = fetch(url)
    recipe = None
    for block in LD_RE.findall(page):
        block = block.strip()
        for candidate in (block, html.unescape(block)):
            try:
                recipe = find_recipe_obj(json.loads(candidate))
                break
            except json.JSONDecodeError:
                continue
        if recipe:
            break
    if not recipe:
        raise ValueError("Pas de données Recipe (JSON-LD) sur cette page")

    rating = recipe.get("aggregateRating") or {}
    yld = recipe.get("recipeYield")
    if isinstance(yld, list):
        yld = yld[0] if yld else None
    return {
        "url": url,
        "source": source_de(url),
        "nom": nettoyer_nom(recipe.get("name")),
        "categorie": recipe.get("recipeCategory"),
        "cuisine": recipe.get("recipeCuisine"),
        "portions": yld,
        "prep_min": iso_duration_to_min(recipe.get("prepTime")),
        "cuisson_min": iso_duration_to_min(recipe.get("cookTime")),
        "total_min": iso_duration_to_min(recipe.get("totalTime")),
        "note": rating.get("ratingValue"),
        "nb_avis": rating.get("ratingCount") or rating.get("reviewCount"),
        "ingredients": [html.unescape(i) for i in recipe.get("recipeIngredient", [])],
        "etapes": flatten_instructions(recipe.get("recipeInstructions", [])),
        "mots_cles": recipe.get("keywords"),
        "image": first_image(recipe.get("image")),
    }


def titre_depuis_slug(url):
    m = re.search(r"recette_(.+?)_\d+\.aspx", url)
    s = m.group(1).replace("-", " ") if m else url
    return s[:1].upper() + s[1:]


def slugifier(texte):
    """« Poulet au curry » → « poulet-au-curry » (sans accents)."""
    t = unicodedata.normalize("NFD", texte).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def extraire_liens(page, base, motif, titre, n):
    """Liens de recettes uniques trouvés dans une page de résultats."""
    out, seen = [], set()
    for m in re.finditer(motif, page):
        full = urljoin(base, m.group(1))
        if full not in seen:
            seen.add(full)
            out.append({"url": full, "titre": titre(full)})
        if len(out) >= n:
            break
    return out


# ---------------- Sources de recherche ----------------
def recherche_marmiton(q, n=10):
    page = fetch(f"{BASE}/recettes/recherche.aspx?aqt={quote_plus(q)}")
    return extraire_liens(page, BASE, r'href="([^"]*?/recettes/recette_[^"?#]+?\.aspx)',
                          titre_depuis_slug, n)


def recherche_ptitchef(q, n=10):
    """PtitChef n'a pas de recherche libre accessible : on lit la page thématique
    /recettes/recettes-de-<terme> (ex. lasagnes, quiche, tiramisu)."""
    base = "https://www.ptitchef.com"
    try:
        page = fetch(f"{base}/recettes/recettes-de-{slugifier(q)}")
    except HTTPError as e:
        if e.code == 404:
            return []                       # pas de page thématique pour ce terme
        raise

    def titre(url):
        m = re.search(r"/recettes/[^/]+/(.+?)-fid-\d+", url)
        s = m.group(1).replace("-", " ") if m else url
        return s[:1].upper() + s[1:]

    return extraire_liens(page, base,
                          r'href="((?:https://www\.ptitchef\.com)?/recettes/[a-z0-9-]+/[a-z0-9-]+-fid-\d+)"',
                          titre, n)


# ---------------- Pages de sélection (liste de recettes) ----------------
# Format des URL de recettes par site, pour extraire les recettes d'une page
# qui en liste plusieurs (chronique Ricardo, page thématique PtitChef, catégorie…).
MOTIFS_RECETTE = {
    "marmiton.org": r"/recettes/recette_[^\"?#]+?\.aspx",
    "ptitchef.com": r"/recettes/[a-z0-9-]+/[a-z0-9-]+-fid-\d+",
    "ricardocuisine.com": r"/(?:en/)?(?:recettes|recipes)/\d+-[a-z0-9-]+",
    "cuisineaz.com": r"/recettes/[a-z0-9-]+-\d+\.aspx",
    "jamieoliver.com": r"/recipes/[a-z0-9-]+/[a-z0-9-]+/",
    "750g.com": r"/[a-z0-9-]+-r\d+\.htm",
}


def titre_generique(url):
    """Titre lisible tiré de l'URL : « 6972-dinde-farcie » → « Dinde farcie »."""
    segments = [x for x in urlparse(url).path.split("/") if x]
    s = segments[-1] if segments else url
    s = re.sub(r"\.(aspx|htm|html)$", "", s)
    s = re.sub(r"^recette_", "", s)
    s = re.sub(r"(?:-fid)?-\d+$|_\d+$|-r\d+$", "", s)
    s = re.sub(r"^\d+-", "", s)
    s = s.replace("-", " ").replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def lister_page(url, n=100):
    """Recettes listées sur une page de sélection d'un site de la liste SITES."""
    src = source_de(url)
    motif = MOTIFS_RECETTE.get(src)
    if not motif:
        raise ValueError(f"Lecture des pages de sélection non prise en charge pour {src}")
    page = fetch(url)
    p = urlparse(url)
    rx = r'href="((?:https?://(?:www\.)?' + re.escape(src) + r')?' + motif + r')"'
    res = extraire_liens(page, f"{p.scheme}://{p.netloc}", rx, titre_generique, n)
    return [r for r in res if r["url"].rstrip("/") != url.rstrip("/")]


# Pour ajouter une source : une fonction chercher(q, n) -> [{"url", "titre"}] et une entrée ici
# (et son domaine dans SITES pour l'import).
SOURCES = {
    "marmiton": {"nom": "Marmiton", "chercher": recherche_marmiton,
                 "aide": "Recherche libre (ex. blanquette, curry de légumes)"},
    "ptitchef": {"nom": "PtitChef", "chercher": recherche_ptitchef,
                 "aide": "Pages thématiques : un plat ou un ingrédient (ex. lasagnes, quiche, tiramisu)"},
    "efarmz": {"nom": "eFarmz (PDF)", "chercher": lambda q, n: lister_pdf(q, n), "dossier": True,
               "aide": "PDF déposés dans le dossier eFarmz/ à côté du serveur (filtre facultatif)"},
}


# ---------------- Source « eFarmz » : PDF déposés dans le dossier eFarmz/ ----------------
PREFIXE_PDF = "efarmz:"            # identifiant d'une recette de PDF : efarmz:fichier.pdf#page
MAX_PDF_OCTETS = 200 * 1024 * 1024
MAX_PDF_FICHIERS = 200
_cache_pdf = {}                    # (fichier, taille, date, personnes) -> (recettes, rapport)
_verrou_pdf = threading.Lock()


class PdfIndisponible(Exception):
    """Extraction PDF impossible : pdfplumber (ou pdf_recettes.py) manque."""


MSG_PDF_INDISPONIBLE = "Extraction PDF indisponible : installe pdfplumber (pip install pdfplumber)"


def _module_pdf():
    """Le module d'extraction, ou PdfIndisponible (il est facultatif : le serveur marche sans)."""
    try:
        import pdf_recettes
    except ImportError:
        raise PdfIndisponible(MSG_PDF_INDISPONIBLE) from None
    if not pdf_recettes.disponible():
        raise PdfIndisponible(MSG_PDF_INDISPONIBLE)
    return pdf_recettes


def fichiers_pdf():
    """Noms des PDF du dossier eFarmz/ (créé s'il manque), triés. Les liens et sous-dossiers sont ignorés."""
    os.makedirs(DOSSIER_PDF, exist_ok=True)
    noms = [n for n in sorted(os.listdir(DOSSIER_PDF), key=str.lower)
            if n.lower().endswith(".pdf") and os.path.isfile(os.path.join(DOSSIER_PDF, n))
            and not os.path.islink(os.path.join(DOSSIER_PDF, n))]
    return noms[:MAX_PDF_FICHIERS]


def lire_pdf(nom, personnes=2):
    """(recettes, rapport) d'un PDF du dossier eFarmz/ ; résultat gardé en mémoire tant que le fichier ne change pas."""
    if nom not in fichiers_pdf():                     # uniquement un nom présent dans le dossier : pas de chemin
        raise ValueError(f"PDF introuvable dans le dossier {os.path.basename(DOSSIER_PDF)}/ : {nom[:80]}")
    chemin = os.path.join(DOSSIER_PDF, nom)
    st = os.stat(chemin)
    if st.st_size > MAX_PDF_OCTETS:
        raise ValueError(f"{nom} : fichier trop gros ({st.st_size // 2**20} Mo, maximum {MAX_PDF_OCTETS // 2**20} Mo)")
    cle = (nom, st.st_size, st.st_mtime_ns, personnes)
    with _verrou_pdf:                                 # une extraction à la fois (CPU, mémoire)
        if cle not in _cache_pdf:
            if len(_cache_pdf) >= 5:
                _cache_pdf.clear()
            pdf = _module_pdf()
            try:
                _cache_pdf[cle] = pdf.convertir(chemin, personnes)
            except pdf.PdfIndisponible as e:
                raise PdfIndisponible(str(e)) from None
        return _cache_pdf[cle]


def recette_pdf(nom, numero, recette):
    """Recette du PDF au format de la base : source « eFarmz · fichier p.N », pas d'URL."""
    r = {k: v for k, v in recette.items() if k != "image_page"}
    r["url"] = ""
    r["source"] = f"eFarmz · {nom} p.{numero}"
    r["categorie"] = r.get("categorie") or "eFarmz"
    return r


def lister_pdf(q="", n=200, personnes=2):
    """Recettes extraites des PDF du dossier, pour l'aperçu : titre, détail, alertes, miniature, texte.
    Un PDF illisible donne une ligne sans url (« erreur »). q filtre sur le titre ou le nom du fichier."""
    _module_pdf()
    noms = fichiers_pdf()
    if not noms:
        return [{"url": "", "titre": f"Aucun PDF dans le dossier {os.path.basename(DOSSIER_PDF)}/ "
                                      "(à côté de serveur_recettes.py) : dépose tes fiches puis relance",
                 "erreur": True}]
    mot, res = sans_accents(q), []
    for nom in noms:
        try:
            recettes, rapport = lire_pdf(nom, personnes)
        except (ValueError, PdfIndisponible) as e:
            res.append({"url": "", "titre": f"{nom} : {e}", "erreur": True})
            continue
        res.append({"url": "", "titre": f"{nom} : {len(recettes)} recette(s) lue(s)", "info": True})
        for numero, rec, alertes in rapport:
            if mot and mot not in sans_accents(rec["nom"] + " " + nom):
                continue
            res.append({"url": f"{PREFIXE_PDF}{nom}#{numero}", "titre": rec["nom"], "fichier": nom, "page": numero,
                        "detail": f"{len(rec['ingredients'])} ingrédients, {len(rec['etapes'])} étapes"
                                  + (f", photo p.{rec['image_page']}" if rec.get("image") else ", sans photo"),
                        "alertes": alertes, "image": rec.get("image", ""),
                        "ingredients": rec["ingredients"], "etapes": rec["etapes"]})
            if sum(1 for x in res if x["url"]) >= n:
                return res
    return res


def importer_pdf(ident, personnes=2):
    """Recette désignée par « efarmz:fichier.pdf#page » (ne touche pas la base : l'appelant l'ajoute)."""
    nom, _, page = ident[len(PREFIXE_PDF):].rpartition("#")
    if not nom or not page.isdigit():
        raise ValueError("Identifiant de recette PDF invalide")
    _module_pdf()
    recettes, rapport = lire_pdf(nom, personnes)
    for numero, rec, _alertes in rapport:
        if numero == int(page):
            return recette_pdf(nom, numero, rec)
    raise ValueError(f"Pas de recette à la page {page} de {nom}")


def search_recipes(q, n=10, source="marmiton"):
    if source not in SOURCES:
        raise ValueError(f"Source inconnue : {source}")
    return SOURCES[source]["chercher"](q, n)


# ---------------- Base JSON partagée avec Colab ----------------
def migrer_base(ancien=None, nouveau=None):
    """Renomme l'ancienne base recettes_marmiton.json en recettes.json (aucune donnée perdue).
    Renvoie un message à afficher, ou None s'il n'y a rien à faire."""
    ancien, nouveau = ancien or ANCIEN_BASE_FILE, nouveau or BASE_FILE
    if not os.path.exists(ancien):
        return None
    if os.path.exists(nouveau):
        return (f"⚠ {os.path.basename(ancien)} et {os.path.basename(nouveau)} existent tous les deux : "
                f"seul {os.path.basename(nouveau)} est utilisé (fusionne ou supprime l'ancien à la main)")
    os.replace(ancien, nouveau)
    return f"Base renommée : {os.path.basename(ancien)} → {os.path.basename(nouveau)}"


class BaseCorrompue(Exception):
    """recettes.json existe mais n'est pas une base de recettes lisible."""


def lire_base_brute():
    """Recettes de recettes.json ([] si le fichier n'existe pas).
    Lève BaseCorrompue si le fichier est illisible ou n'a pas le bon format ; toute autre erreur
    d'accès (droits…) se propage telle quelle. Jamais d'écriture ici."""
    try:
        with open(BASE_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise BaseCorrompue(f"JSON invalide ({e})") from e
    liste = d.get("recettes") if isinstance(d, dict) else d
    if not isinstance(liste, list) or not all(isinstance(r, dict) for r in liste):
        raise BaseCorrompue("format inattendu (liste de recettes attendue)")
    return liste


_base_signalee = set()


def lire_base():
    """Pour l'affichage : [] si la base est corrompue (le fichier n'est pas touché, signalé une fois)."""
    try:
        return lire_base_brute()
    except BaseCorrompue as e:
        try:
            marque = os.stat(BASE_FILE).st_mtime_ns
        except OSError:
            marque = None
        if marque not in _base_signalee:
            _base_signalee.add(marque)
            print(f"   ⚠ {os.path.basename(BASE_FILE)} est illisible : {e}. "
                  "Il sera conservé tel quel avant la prochaine écriture.")
        return []


def mettre_de_cote_base(cause):
    """Renomme la base corrompue en recettes.json.corrompu-AAAAMMJJ-HHMMSS (récupérable à la main)."""
    horodatage = time.strftime("%Y%m%d-%H%M%S")
    cible, n = f"{BASE_FILE}.corrompu-{horodatage}", 1
    while os.path.exists(cible):
        n += 1
        cible = f"{BASE_FILE}.corrompu-{horodatage}-{n}"
    os.replace(BASE_FILE, cible)
    print(f"   ⚠ {os.path.basename(BASE_FILE)} était illisible ({cause}) : conservé dans "
          f"{os.path.basename(cible)}, nouvelle base créée.")
    return cible


def ajouter_base(rec):
    with _file_lock:
        try:
            existantes = lire_base_brute()
        except BaseCorrompue as e:
            mettre_de_cote_base(e)               # jamais d'écrasement du contenu récupérable
            existantes = []
        base = {}
        for r in existantes:
            r["nom"] = nettoyer_nom(r.get("nom"))      # nettoie aussi les anciens imports
            base[r.get("url") or r.get("nom")] = r
        base[rec.get("url") or rec["nom"]] = rec      # sans URL (recette de PDF) : le nom
        tmp = BASE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(base.values()), f, ensure_ascii=False, indent=2)
        os.replace(tmp, BASE_FILE)


# ---------------- HTTP ----------------
class ParametreInvalide(ValueError):
    """Paramètre de requête mal formé (→ HTTP 400)."""


def entier(valeur, defaut, mini, maxi):
    if valeur in (None, ""):
        return defaut
    try:
        return max(mini, min(int(valeur), maxi))
    except ValueError:
        raise ParametreInvalide(f"Paramètre n invalide : {valeur[:20]!r}") from None


def hote_ok(host):
    """Valide l'en-tête Host (anti DNS rebinding) : localhost, adresse IP locale, ou RECETTES_HOTES."""
    h = (host or "").strip().lower()
    h = h[1:h.index("]")] if h.startswith("[") and "]" in h else h.rsplit(":", 1)[0] if h.count(":") == 1 else h
    if h in HOTES:
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False                     # tout autre nom de domaine : refusé
    return ip.is_loopback or (LAN and ip.is_private)


class Handler(BaseHTTPRequestHandler):
    server_version = "Recettes"
    sys_version = ""

    # ---- Contrôle d'origine ----
    def origine_ok(self, origin):
        """Origine autorisée : liste ORIGINES, ou la page servie par ce serveur lui-même."""
        if origin in ORIGINES:
            return True
        host = self.headers.get("Host", "")      # déjà validé par hote_ok() dans do_GET
        return bool(host) and origin in (f"http://{host}", f"https://{host}")

    def refus_origine(self, ecriture=False):
        """None si la requête API est acceptable, sinon le motif du refus.
        Une requête qui modifie la base (POST) doit en plus porter l'en-tête X-Recettes : un site
        tiers ne peut pas l'envoyer sans pré-vol CORS, que seul une origine autorisée obtient."""
        if ecriture and not self.headers.get("X-Recettes"):
            return "En-tête X-Recettes manquant"
        origin = self.headers.get("Origin")
        if origin:
            return None if self.origine_ok(origin) else f"Origine non autorisée : {origin}"
        # Pas d'en-tête Origin mais requête venant d'un autre site (<img>, <link>…)
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            return "Requête inter-sites non autorisée"
        return None  # même origine, navigation directe, curl…

    def end_headers(self):
        origin = self.headers.get("Origin")
        if origin and self.origine_ok(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")  # page GitHub → localhost
            self.send_header("Vary", "Origin")
        super().end_headers()

    def do_OPTIONS(self):
        """Pré-vol CORS (page GitHub Pages → localhost) : accepté seulement pour une origine autorisée."""
        origin = self.headers.get("Origin")
        if not (hote_ok(self.headers.get("Host")) and origin and self.origine_ok(origin)):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):
            print("  ", self.client_address[0], fmt % args)

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, texte, code=200):
        body = texte.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_json({"erreur": "Méthode non prise en charge"}, 405)

    def do_GET(self):
        if not hote_ok(self.headers.get("Host")):
            print("   ⛔", self.client_address[0], "Host refusé :", self.headers.get("Host"))
            return self.send_json({"erreur": "Hôte non autorisé"}, 403)
        u = urlparse(self.path)
        # Seule la page du générateur est servie (ni .git, ni code source, ni base JSON)
        if u.path in ("/", "/index.html") or u.path.lstrip("/") in NOMS_PAGE:
            page = trouver_page()
            if not page:
                local = self.client_address[0] in ("127.0.0.1", "::1")      # détails réservés au poste lui-même
                fichiers = "\n".join(sorted(os.listdir(DIR))) or "(dossier vide)" if local else ""
                details = (f"<p>Dossier du serveur : <code>{html.escape(DIR)}</code></p>"
                           f"<p>Contenu :</p><pre>{html.escape(fichiers)}</pre>") if local else ""
                return self.send_html(
                    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<h2>Page du générateur introuvable</h2>" + details +
                    "<p>Place <b>generateur-recettes.html</b> dans le dossier du serveur puis recharge.</p>", 404)
            with open(os.path.join(DIR, page), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)
            return
        if not u.path.startswith("/api/"):
            return self.send_json({"erreur": "Introuvable"}, 404)

        self.api("GET", u)

    def do_POST(self):
        if not hote_ok(self.headers.get("Host")):
            print("   ⛔", self.client_address[0], "Host refusé :", self.headers.get("Host"))
            return self.send_json({"erreur": "Hôte non autorisé"}, 403)
        u = urlparse(self.path)
        if not u.path.startswith("/api/"):
            return self.send_json({"erreur": "Introuvable"}, 404)
        try:                                   # corps ignoré (les paramètres sont dans l'URL) mais lu
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if 0 < n <= 1_000_000:
            self.rfile.read(n)
        self.api("POST", u)

    ROUTES_GET = {"/api/ping", "/api/base", "/api/sources", "/api/search", "/api/liste"}
    ROUTES_POST = {"/api/recipe"}              # seule route qui écrit dans la base

    def api(self, methode, u):
        refus = self.refus_origine(ecriture=(methode == "POST"))
        if refus:
            print("   ⛔", self.client_address[0], refus)
            return self.send_json({"erreur": refus}, 403)
        autre = self.ROUTES_POST if methode == "GET" else self.ROUTES_GET
        if u.path in autre:
            return self.send_json({"erreur": f"Méthode {methode} non prise en charge ici "
                                             f"(utilise {'POST' if methode == 'GET' else 'GET'})"}, 405)

        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/ping":
                return self.send_json({"ok": True, "version": VERSION, "api": API_VERSION, "base": len(lire_base()),
                                       "fichier": os.path.basename(BASE_FILE)})
            if u.path == "/api/base":
                base = lire_base()
                for r in base:
                    r["nom"] = nettoyer_nom(r.get("nom"))
                return self.send_json(base)
            if u.path == "/api/sources":
                return self.send_json([{"id": k, "nom": v["nom"], "aide": v["aide"], "dossier": bool(v.get("dossier"))}
                                       for k, v in SOURCES.items()])
            if u.path == "/api/search":
                q = qs.get("q", "").strip()
                source = qs.get("source", "marmiton")
                if source not in SOURCES:
                    return self.send_json({"erreur": f"Source inconnue : {source}"}, 400)
                if SOURCES[source].get("dossier"):             # PDF d'un dossier : pas de recherche en ligne, filtre facultatif
                    return self.send_json(lister_pdf(q, entier(qs.get("n"), 200, 1, 500),
                                                     entier(qs.get("p"), 2, 1, 12)))
                if not q:
                    return self.send_json({"erreur": "Paramètre q manquant"}, 400)
                n = entier(qs.get("n"), 10, 1, 50)
                return self.send_json(search_recipes(q, n, source))
            if u.path == "/api/liste":
                url = qs.get("url", "").strip()
                if not url_autorisee(url):
                    return self.send_json({"erreur": f"Site non autorisé : {domaine(url)} "
                                                     "(ajoute-le dans SITES de serveur_recettes.py)"}, 400)
                n = entier(qs.get("n"), 100, 1, 200)
                return self.send_json(lister_page(url, n))
            if u.path == "/api/recipe":
                url = qs.get("url", "").strip()
                if url.startswith(PREFIXE_PDF):
                    rec = importer_pdf(url, entier(qs.get("p"), 2, 1, 12))
                    ajouter_base(rec)
                    return self.send_json(rec)
                if not url_autorisee(url):
                    return self.send_json({"erreur": f"Site non autorisé : {domaine(url)} "
                                                     "(ajoute-le dans SITES de serveur_recettes.py)"}, 400)
                rec = scrape_recipe(url)
                ajouter_base(rec)
                return self.send_json(rec)
            return self.send_json({"erreur": "Route inconnue"}, 404)
        except ParametreInvalide as e:
            self.send_json({"erreur": str(e)}, 400)
        except AccesInterdit as e:
            self.send_json({"erreur": str(e)}, 403)
        except PdfIndisponible as e:
            self.send_json({"erreur": str(e)}, 503)
        except ReponseTropGrosse as e:
            self.send_json({"erreur": str(e)}, 502)
        except HTTPError as e:
            self.send_json({"erreur": f"Le site a répondu HTTP {e.code}"}, 502)
        except URLError as e:
            self.send_json({"erreur": f"Réseau : {e.reason}"}, 502)
        except TimeoutError:
            self.send_json({"erreur": "Le site met trop de temps à répondre"}, 504)
        except ValueError as e:                  # messages écrits par ce serveur (ex. « Pas de données Recipe »)
            self.send_json({"erreur": str(e)}, 500)
        except Exception as e:                   # le détail (chemins, système…) reste dans la fenêtre du serveur
            print(f"   ⚠ Erreur interne sur {u.path} : {type(e).__name__} : {e}")
            self.send_json({"erreur": "Erreur interne du serveur (détails dans sa fenêtre)"}, 500)


# ---------------- Lancement ----------------
def ip_locale():
    """IP du poste sur le Wi-Fi (aucune donnée n'est envoyée)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "?"


def ouvrir_navigateur(url):
    if "--no-browser" in sys.argv:
        return
    try:
        if shutil.which("termux-open-url"):          # Android / Termux
            subprocess.Popen(["termux-open-url", url])
        else:
            webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"serveur_recettes {VERSION}")
        sys.exit(0)
    page = trouver_page()
    if not page:
        print(f"⚠ Aucune page HTML trouvée dans {DIR}")
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        sys.exit(f"✗ Impossible d'ouvrir le port {PORT} : {e}\n"
                 f"  (serveur déjà lancé ? sinon : RECETTES_PORT=8766 python {os.path.basename(__file__)})")

    url = f"http://localhost:{PORT}/"
    print(f"🍲 Générateur de recettes {VERSION} → {url}")
    if page:
        print(f"   Page : {page}")
    if LAN:
        print(f"   Réseau local     → http://{ip_locale()}:{PORT}/")
        print("   ⚠ Accessible à tout appareil du même Wi-Fi")
    migration = migrer_base()
    if migration:
        print("  ", migration)
    print(f"   Base : {BASE_FILE} ({len(lire_base())} recettes)")
    print("   Ctrl+C pour arrêter")
    ouvrir_navigateur(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        srv.server_close()
