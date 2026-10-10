"""Génère tests/fixtures/fiches.pdf (4 fiches recettes synthétiques avec photo). Outil de développement :
pip install reportlab pillow ; python tests/fixtures/generer_pdf.py — le PDF produit est versionné.
Reproduit la mise en page d'une fiche : page photo, puis page de détail (durées, tableau 1p…6p, étapes)."""
import os
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

W, H = landscape(A4)


def mot(c, x, y, texte, taille=9, gras=False):
    police = "Helvetica-Bold" if gras else "Helvetica"
    c.setFont(police, taille); c.drawString(x, y, texte)
    return x + stringWidth(texte, police, taille)


def ligne_etiquette(c, x, y, segments):
    """segments : (texte, 'n' normal | 'e' exposant)."""
    for texte, genre in segments:
        if genre == "e":
            x = mot(c, x + 1, y + 3.5, texte, 5.5) + 2
        else:
            x = mot(c, x, y, texte, 9) + 3


def page_photo(c, titre):
    from PIL import Image
    degrade = Image.linear_gradient("L").resize((600, 400)).convert("RGB")      # image légère, sans hasard
    degrade.save("/tmp/photo_fixture.png")
    c.setFillColorRGB(0.8, 0.6, 0.3); c.rect(0, 0, W, H, fill=1, stroke=0)
    c.drawImage("/tmp/photo_fixture.png", 380, 60, width=420, height=280)
    c.setFillColorRGB(1, 1, 1); mot(c, 40, 60, titre, 30, True); c.showPage()


def page_detail(c, titre_lignes, durees, ustensiles, conservation, colonnes, lignes_tab, notes, etapes, pied=True,
                bloc_qr=None, fin=True):
    c.setFillColorRGB(0.07, 0.3, 0.27); c.rect(10, 20, 340, H - 40, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    y = 540
    for d in durees:
        mot(c, 55, y, d, 10); y -= 25
    for u in ustensiles:
        mot(c, 55, y, u, 9); y -= 12
    y -= 8
    if conservation:
        mot(c, 55, y, conservation, 9)
    xs = {n: 185 + 29 * i for i, n in enumerate(colonnes)}
    for n, x in xs.items():
        mot(c, x - 6, 420, f"{n}p", 9, True)
    for segments_lignes, y0, valeurs, y_val in lignes_tab:
        for dy, segs in segments_lignes:
            ligne_etiquette(c, 25, y0 - dy, segs)
        for (n, x), v in zip(xs.items(), valeurs):
            mot(c, x - 5, y0 - y_val, v, 9)
    for i, n in enumerate(bloc_qr or []):                      # texte du code QR, sous le tableau
        mot(c, 95, 92 - 11 * i, n, 8)
    for i, n in enumerate(notes):
        mot(c, 25, 40 - 9 * i, n, 7)
    c.setFillColorRGB(0, 0, 0)
    y = 535
    for t in titre_lignes:
        mot(c, 375, y, t, 26, True); y -= 32
    y = 440
    for k, lignes_etape in enumerate(etapes, 1):
        x = mot(c, 375, y, f"{k}.", 10, True) + 3
        for j, t in enumerate(lignes_etape):
            mot(c, x if j == 0 else 375, y, t, 10); y -= 12
        y -= 8
    if pied:
        mot(c, 400, 40, "Tous les produits sont certifiés bio sauf indication contraire.", 7)
    if fin:
        c.showPage()


def recette_steak(c):
    page_photo(c, "STEAK DE BOEUF ET FRITES DE PATATES DOUCES")
    N = lambda t: (t, "n"); E = lambda t: (t, "e")
    tab = [
        ([(0, [N("•"), N("Patates")]), (12, [N("douces"), E("BE"), N("(g)")])], 395, ["250", "500", "750", "1000", "1250", "1500"], 6),
        ([(0, [N("•"), N("Ail"), E("BE"), N("(gousse)")])], 360, ["1/2", "1", "1½", "2", "2½", "3"], 0),
        ([(0, [N("•"), N("Tomates")]), (12, [N("grappe"), E("BE"), N("(pc)")])], 335, ["1", "2", "3", "4", "5", "6"], 12),
        ([(0, [N("•"), N("Laitue"), N("du"), N("jour")]), (12, [E("BE"), N("(pc)")])], 298, ["1/4", "1/2", "3/4", "1", "1¼", "1½"], 0),
        ([(0, [N("•"), N("Huile"), N("d'olive"), E("(1)"), N("(càs)")])], 255, ["2", "4", "6", "8", "10", "12"], 0),
        ([(0, [N("•"), N("Vinaigre"), E("(1)"), N("(càs)")])], 232, ["1", "2", "3", "4", "5", "6"], 0),
        ([(0, [N("•"), N("Beurre"), E("(1)")])], 209, [], 0),
        ([(0, [N("•"), N("Steak"), N("de")]), (12, [N("boeuf"), N("(pc)")])], 186, ["1", "2", "3", "4", "5", "6"], 0),
        ([(0, [N("•"), N("Sel"), N("et"), N("poivre"), E("(1)")])], 150, [], 0),
        ([(0, [N("•"), N("Sauce"), N("de"), N("votre")]), (12, [N("choix"), E("(1)"), N("(mayon-")]), (24, [N("naise,"), N("ketchup...)")])], 127, [], 0),
    ]
    etapes = [
        ["Préchauffez votre four à 220°C."],
        ["Épluchez et coupez les patates douces en frites de 1 cm.", "Disposez-les sur une plaque recouverte de papier cuisson.", "Versez un filet d'huile d'olive, salez et poivrez. Enfournez", "pendant 20 à 25 min."],
        ["Pendant ce temps, lavez et essorez la laitue. Préparez la vinai-", "grette avec l'huile d'olive, le vinaigre, du sel et du poivre. Réser-", "vez. Pressez ou hachez l'ail. Coupez les tomates en deux."],
        ["Au bout de 15 min de cuisson des patates douces, retournez-les", "et déposez les demi-tomates à côté des frites."],
        ["10 min avant la fin de cuisson des frites, faites chauffer une noix", "de beurre dans une poêle. Salez et poivrez."],
        ["Servez le steak accompagné des frites de patates douces."],
    ]
    page_detail(c, ["STEAK DE BOEUF ET", "FRITES DE PATATES DOUCES"], ["20 mn", "35 mn"],
                ["une poêle, une plaque de cuisson, du papier", "sulfurisé"], "à cuisiner dans les 3 jours",
                [1, 2, 3, 4, 5, 6], tab, ["(1) Non fourni dans la box."], etapes)


def recette_deux_colonnes(c):
    page_photo(c, "OEUFS COCOTTE")
    N = lambda t: (t, "n")
    tab = [
        ([(0, [N("•"), N("Oeufs"), N("(pc)")])], 395, ["2", "4"], 0),
        ([(0, [N("•"), N("Crème"), N("fraîche"), N("(cl)")])], 370, ["10", "20"], 0),
        ([(0, [N("•"), N("Huile"), N("(càc)")])], 345, ["1", "2"], 0),
    ]
    page_detail(c, ["OEUFS COCOTTE"], ["1 h 10"], ["un four"], "", [2, 4], tab, [],
                [["Préchauffez le four à 180°C."], ["Cassez les oeufs dans des ramequins."], ["Enfournez 10 min."]])


def recette_planche_decoupee(c):
    """Comme certains PDF eFarmz : la page est deux fois trop haute, seule sa moitié basse est visible (CropBox)
    et le contenu (texte, photo) est répété dans la moitié haute, cachée."""
    from PIL import Image
    Image.linear_gradient("L").resize((600, 400)).convert("RGB").save("/tmp/photo_fixture.png")
    N = lambda t: (t, "n")
    tab = [
        ([(0, [N("•"), N("Poisson"), N("(pc)")])], 395, ["2", "3", "4"], 0),
        ([(0, [N("•"), N("Sucre"), (("(1)"), "e"), N("(càc)")])], 360, [], 0),
        ([(0, [N("•"), N("Sel"), N("et"), N("poivre"), (("(1)"), "e")])], 335, [], 0),
    ]
    etapes = [["Préchauffez le four à 170°C."], ["Enfournez le poisson 10 min."]]
    for decalage in (0, H):                                   # d'abord la copie visible, puis la copie cachée
        c.setPageSize((W, 2 * H))
        c.saveState(); c.translate(0, decalage)
        c.setFillColorRGB(0.8, 0.6, 0.3); c.rect(0, 0, W, H, fill=1, stroke=0)
        c.drawImage("/tmp/photo_fixture.png", 30, 40, width=W - 60, height=H - 80)
        c.restoreState()
    c.setCropBox((0, 0, W, H)); c.showPage()
    c.setPageSize((W, 2 * H))
    for decalage in (0, H):
        c.saveState(); c.translate(0, decalage)
        page_detail(c, ["FILET DE POISSON"], ["15 mn", "30 mn"], ["une poêle"], "", [2, 3, 4], tab,
                    ["(1) Non fourni dans la box."], etapes, bloc_qr=["Envie d'en savoir plus", "sur ce poisson ?"], fin=False)
        c.restoreState()
    c.setCropBox((0, 0, W, H)); c.showPage()


def recette_anormale(c):
    page_photo(c, "SALADE")
    N = lambda t: (t, "n")
    tab = [([(0, [N("•"), N("Laitue"), N("(pc)")])], 395, ["1", "2", "3"], 0)]
    page_detail(c, ["SALADE VERTE"], ["10 mn"], [], "", [1, 2, 3], tab, [], [["Lavez la laitue."], ["Servez."]])


if __name__ == "__main__":
    c = canvas.Canvas(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fiches.pdf"), pagesize=landscape(A4))
    recette_steak(c); recette_deux_colonnes(c); recette_anormale(c); recette_planche_decoupee(c)
    c.save()
    print("fiches.pdf écrit")
