# -*- coding: utf-8 -*-
"""
Le cadre de focus du panneau "Pyxel" (le jeu) : au ras de l'image, coins arrondis.

Demande de l'utilisateur le 12/11/2026 : « ce qui fait bizarre c'est les bandes noires
au-dessus et en dessous du jeu quand on met un cadre ». Le cadre ne doit donc pas entourer
le panneau (bandes comprises) mais l'IMAGE du jeu, avec quatre coins arrondis ; rogner
quelques pixels aux coins de l'image est accepte.

Ce test construit le panneau comme Spyder, lui donne une image plus LARGE que haute dans
un panneau plus HAUT qu'elle (donc des bandes en haut et en bas), le PEINT par grab() et
relit les pixels.

Lancement :
    QT_QPA_PLATFORM=offscreen python tests/test_cadre_jeu.py
Variable facultative CADRE_JEU_CAPTURE=<prefixe> : enregistre <prefixe>_repos.png et
<prefixe>_focus.png, les rendus relus.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qtpy.QtGui import QColor  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

LARGEUR, HAUTEUR = 160, 90       # image plus large que haute
CONTENU = 0xC0FFEE


class ImageFactice:
    """Ce que le pont publie : des octets, une taille, une palette."""

    def __init__(self):
        self.pixels = bytes([1] * (LARGEUR * HAUTEUR))
        self.width = LARGEUR
        self.height = HAUTEUR
        self.palette = [0x000000, CONTENU] + [0] * 14
        self.number = 1


def rgb(image, x, y):
    return image.pixelColor(x, y).rgb() & 0xFFFFFF


def hexa(couleur):
    return QColor(couleur).rgb() & 0xFFFFFF


def peindre(panneau, ecran):
    QApplication.processEvents()
    return ecran.grab().toImage()


def verifier(panneau, ecran, attendu, capture=None):
    from spyder_pyxel.spyder.widgets.screen import letterbox_color

    image = peindre(panneau, ecran)
    if capture:
        image.save(capture)
    fond = letterbox_color().rgb() & 0xFFFFFF
    gauche, haut, largeur, hauteur = ecran._display_geometry()
    droite, bas = gauche + largeur - 1, haut + hauteur - 1
    assert haut > 10 and image.height() - (haut + hauteur) > 10, (
        f"pas de bandes en haut et en bas (image en y={haut}, h={hauteur}, panneau "
        f"{image.width()}x{image.height()}) : le cas n'est pas teste")
    milieu_x, milieu_y = gauche + largeur // 2, haut + hauteur // 2

    # 1. Le trait est AU RAS DE L'IMAGE, sur ses quatre cotes.
    for x, y, ou in ((milieu_x, haut, "haut"), (milieu_x, bas, "bas"),
                     (gauche, milieu_y, "gauche"), (droite, milieu_y, "droite")):
        assert rgb(image, x, y) == attendu, (
            f"bord {ou} de l'image ({x}, {y}) en {rgb(image, x, y):06x}, "
            f"attendu le trait {attendu:06x}")

    # 1 bis. Trait de 2 px (12/11/2026, « se voit a peine car l'image est claire »).
    for x, y, ou in ((milieu_x, haut + 1, "haut"), (milieu_x, bas - 1, "bas"),
                     (gauche + 1, milieu_y, "gauche"), (droite - 1, milieu_y, "droite")):
        assert rgb(image, x, y) == attendu, f"trait {ou} pas sur 2 px"
    assert rgb(image, milieu_x, haut + 2) == CONTENU, "trait trop large"

    # 2. Rien dans les bandes : ni au bord du panneau, ni juste au-dessus de l'image.
    for x, y, ou in ((milieu_x, 0, "bord haut du panneau"),
                     (milieu_x, image.height() - 1, "bord bas du panneau"),
                     (milieu_x, haut - 1, "juste au-dessus de l'image"),
                     (milieu_x, bas + 1, "juste au-dessous de l'image")):
        assert rgb(image, x, y) == fond, (
            f"{ou} ({x}, {y}) en {rgb(image, x, y):06x}, attendu la bande {fond:06x}")

    # 3. Coins ARRONDIS : le pixel du coin de l'image est rogne (fond), le contenu
    #    commence juste a l'interieur.
    for x, y in ((gauche, haut), (droite, haut), (gauche, bas), (droite, bas)):
        assert rgb(image, x, y) == fond, (
            f"coin ({x}, {y}) en {rgb(image, x, y):06x} : coin carre, pas arrondi")
    assert rgb(image, milieu_x, milieu_y) == CONTENU, "le contenu de l'image a disparu"
    assert rgb(image, gauche + 8, haut + 8) == CONTENU, "rognage trop large dans le coin"


def main():
    from spyder.utils.palette import SpyderPalette

    from spyder_pyxel.spyder.plugin import PyxelGame
    from spyder_pyxel.spyder.plugin_studio import PyxelStudio
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_widgets_build import build

    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    panneau = build(PyxelGame)
    panneau.resize(320, 600)
    panneau.show()
    ecran = panneau.screen
    ecran.set_frame(ImageFactice())

    prefixe = os.environ.get("CADRE_JEU_CAPTURE")
    verifier(panneau, ecran, hexa(SpyderPalette.COLOR_BACKGROUND_4),
             prefixe and prefixe + "_repos.png")
    print("OK  au repos : trait gris au ras de l'image, bandes vides, coins arrondis")

    panneau._apply_tabs_stylesheet(focus=True)
    verifier(panneau, ecran, hexa(SpyderPalette.COLOR_ACCENT_3),
             prefixe and prefixe + "_focus.png")
    print("OK  au focus : trait bleu au ras de l'image")

    # Un ecran cree apres coup (_screen_for, deuxieme programme) prend l'etat courant.
    tard = panneau._new_screen()
    panneau._tabs.addTab(tard, "deuxieme")      # ce que fait _screen_for
    assert tard.border_hugs_image and \
        hexa(tard._border_color) == hexa(SpyderPalette.COLOR_ACCENT_3), \
        "un ecran cree apres coup n'a pas le cadre courant"
    panneau._apply_tabs_stylesheet(focus=False)
    assert hexa(tard._border_color) == hexa(SpyderPalette.COLOR_BACKGROUND_4)
    print("OK  un ecran cree apres coup suit le cadre du panneau")

    # Pyxel Studio garde son cadre AUTOUR du panneau.
    studio = build(PyxelStudio)
    assert not studio.screen.border_hugs_image, "Pyxel Studio a perdu son cadre de panneau"
    print("OK  Pyxel Studio garde son cadre autour du panneau")


if __name__ == "__main__":
    main()
