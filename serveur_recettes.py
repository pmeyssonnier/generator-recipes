#!/usr/bin/env python3
"""
serveur_recettes.py — Serveur local du générateur de recettes (stdlib uniquement)

Lancement :
  python serveur_recettes.py                 → http://localhost:8765 (ce poste uniquement)
  python serveur_recettes.py --lan           → accessible depuis le Wi-Fi (téléphone, tablette…)
  python serveur_recettes.py --no-browser    → ne pas ouvrir le navigateur automatiquement
Port personnalisé : variable d'environnement RECETTES_PORT (défaut 8765)
Compatible Windows, Linux, macOS et Android (Termux).

Les recettes importées sont enregistrées dans recettes_marmiton.json,
dans le même dossier que ce script (même format que le script Colab).
"""
import gzip, html, json, os, re, shutil, socket, subprocess, sys, threading, time, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

PORT = int(os.environ.get("RECETTES_PORT", 8765))
LAN = "--lan" in sys.argv          # écoute sur le réseau local (accès depuis un autre appareil)
HOST = "0.0.0.0" if LAN else "127.0.0.1"
DIR = os.path.dirname(os.path.abspath(__file__))
NOMS_PAGE = ("generateur-recettes.html", "generateur_recettes.html")
BASE_FILE = os.path.join(DIR, "recettes_marmiton.json")
BASE = "https://www.marmiton.org"
PAUSE = 1.5  # secondes minimum entre deux requêtes sortantes
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
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

_net_lock = threading.Lock()
_file_lock = threading.Lock()
_last = [0.0]
_cache = {}


# ---------------- Page HTML ----------------
def trouver_page():
    """Accepte generateur-recettes.html, generateur_recettes.html, sinon le premier .html du dossier."""
    for nom in NOMS_PAGE:
        if os.path.exists(os.path.join(DIR, nom)):
            return nom
    autres = sorted(f for f in os.listdir(DIR) if f.lower().endswith((".html", ".htm")))
    return autres[0] if autres else None


# ---------------- Réseau ----------------
def fetch(url):
    if url in _cache:
        return _cache[url]
    with _net_lock:
        wait = PAUSE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=20) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                charset = r.headers.get_content_charset() or "utf-8"
        finally:
            _last[0] = time.time()
    txt = data.decode(charset, errors="replace")
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
def nettoyer_nom(nom):
    """Retire le suffixe SEO « : la meilleure recette » ajouté par Marmiton."""
    nom = html.unescape(nom or "").replace(" ", " ")
    return SUFFIXE_RE.sub("", nom).strip()


def iso_duration_to_min(d):
    if not d or not isinstance(d, str):
        return None
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", d)
    if not m:
        return None
    j, h, mi = (int(x) if x else 0 for x in m.groups())
    return j * 1440 + h * 60 + mi


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


def search_recipes(q, n=10):
    """Recherche Marmiton (seule source de recherche pour l'instant)."""
    page = fetch(f"{BASE}/recettes/recherche.aspx?aqt={quote_plus(q)}")
    out, seen = [], set()
    for m in re.finditer(r'href="([^"]*?/recettes/recette_[^"?#]+?\.aspx)', page):
        full = urljoin(BASE, m.group(1))
        if full not in seen:
            seen.add(full)
            out.append({"url": full, "titre": titre_depuis_slug(full)})
        if len(out) >= n:
            break
    return out


# ---------------- Base JSON partagée avec Colab ----------------
def lire_base():
    try:
        with open(BASE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else d.get("recettes", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def ajouter_base(rec):
    with _file_lock:
        base = {}
        for r in lire_base():
            r["nom"] = nettoyer_nom(r.get("nom"))      # nettoie aussi les anciens imports
            base[r.get("url") or r.get("nom")] = r
        base[rec["url"]] = rec
        tmp = BASE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(base.values()), f, ensure_ascii=False, indent=2)
        os.replace(tmp, BASE_FILE)


# ---------------- HTTP ----------------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DIR, **k)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")  # utile si la page est ouverte en file://
        self.send_header("Access-Control-Allow-Private-Network", "true")  # page GitHub → localhost
        super().end_headers()

    def do_OPTIONS(self):
        """Pré-vol CORS envoyé par le navigateur quand la page vient de GitHub Pages."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
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

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            page = trouver_page()
            if not page:
                fichiers = "\n".join(sorted(os.listdir(DIR))) or "(dossier vide)"
                return self.send_html(
                    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<h2>Page du générateur introuvable</h2>"
                    f"<p>Dossier du serveur : <code>{html.escape(DIR)}</code></p>"
                    f"<p>Contenu :</p><pre>{html.escape(fichiers)}</pre>"
                    "<p>Place <b>generateur-recettes.html</b> dans ce dossier puis recharge.</p>", 404)
            self.path = "/" + page
            return super().do_GET()
        if not u.path.startswith("/api/"):
            return super().do_GET()

        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/ping":
                return self.send_json({"ok": True, "base": len(lire_base()), "fichier": BASE_FILE})
            if u.path == "/api/base":
                base = lire_base()
                for r in base:
                    r["nom"] = nettoyer_nom(r.get("nom"))
                return self.send_json(base)
            if u.path == "/api/search":
                q = qs.get("q", "").strip()
                if not q:
                    return self.send_json({"erreur": "Paramètre q manquant"}, 400)
                n = max(1, min(int(qs.get("n", 10)), 50))
                return self.send_json(search_recipes(q, n))
            if u.path == "/api/recipe":
                url = qs.get("url", "").strip()
                if not url_autorisee(url):
                    return self.send_json({"erreur": f"Site non autorisé : {domaine(url)} "
                                                     "(ajoute-le dans SITES de serveur_recettes.py)"}, 400)
                rec = scrape_recipe(url)
                ajouter_base(rec)
                return self.send_json(rec)
            return self.send_json({"erreur": "Route inconnue"}, 404)
        except HTTPError as e:
            self.send_json({"erreur": f"Le site a répondu HTTP {e.code}"}, 502)
        except URLError as e:
            self.send_json({"erreur": f"Réseau : {e.reason}"}, 502)
        except Exception as e:
            self.send_json({"erreur": str(e)}, 500)


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
    page = trouver_page()
    if not page:
        print(f"⚠ Aucune page HTML trouvée dans {DIR}")
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        sys.exit(f"✗ Impossible d'ouvrir le port {PORT} : {e}\n"
                 f"  (serveur déjà lancé ? sinon : RECETTES_PORT=8766 python {os.path.basename(__file__)})")

    url = f"http://localhost:{PORT}/"
    print(f"🍲 Générateur de recettes → {url}")
    if page:
        print(f"   Page : {page}")
    if LAN:
        print(f"   Réseau local     → http://{ip_locale()}:{PORT}/")
        print("   ⚠ Accessible à tout appareil du même Wi-Fi")
    print(f"   Base : {BASE_FILE} ({len(lire_base())} recettes)")
    print("   Ctrl+C pour arrêter")
    ouvrir_navigateur(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        srv.server_close()
