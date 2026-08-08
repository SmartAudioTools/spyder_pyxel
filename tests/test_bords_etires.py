# -*- coding: utf-8 -*-
"""
Les bandes laissees autour de l'image : fond de Spyder, ou pixels de bord etires ?

L'ecran Pyxel a des proportions fixes (240x180 pour l'editeur de ressources), le panneau
a celles que l'utilisateur lui donne : conserver les proportions laisse donc des bandes,
en haut et en bas ou sur les cotes selon la forme de l'onglet. Le panneau "Pyxel Studio"
les comble en etirant la colonne (ou la ligne) de bord de l'image, et colle l'image au
bord HAUT pour que toute la place restante passe en une seule bande, en bas. Les panneaux
de jeu font ni l'un ni l'autre : le decor d'un jeu s'etirerait en trainees, et un jeu se
regarde au milieu.

Ce test PEINT reellement le widget dans une image et RELIT ses pixels : c'est le seul
registre qui prouve ce qui est affiche. Une sonde qui interrogerait les attributs dirait
seulement ce qu'on a demande.

Lancement :
    QT_QPA_PLATFORM=offscreen python tests/test_bords_etires.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qtpy.QtGui import QImage  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

from spyder_pyxel.spyder.widgets.screen import (  # noqa: E402
    PyxelScreenWidget, letterbox_color,
)

LARGEUR, HAUTEUR = 240, 180      # la taille de l'editeur de ressources Pyxel
COULEUR_BORD = 3                 # index de palette du pourtour, dans l'image de test
COULEUR_CENTRE = 7               # index de palette du contenu
PALETTE = [0x000000] * 16
PALETTE[COULEUR_BORD] = 0x102030
PALETTE[COULEUR_CENTRE] = 0xC0FFEE


class ImageFactice:
    """Ce que le pont publie : des octets, une taille, une palette."""

    def __init__(self):
        pixels = bytearray([COULEUR_CENTRE] * (LARGEUR * HAUTEUR))
        # Un pourtour d'une seule couleur, comme celui de l'editeur de ressources.
        for x in range(LARGEUR):
            pixels[x] = COULEUR_BORD
            pixels[(HAUTEUR - 1) * LARGEUR + x] = COULEUR_BORD
        for y in range(HAUTEUR):
            pixels[y * LARGEUR] = COULEUR_BORD
            pixels[y * LARGEUR + LARGEUR - 1] = COULEUR_BORD
        self.pixels = bytes(pixels)
        self.width = LARGEUR
        self.height = HAUTEUR
        self.palette = PALETTE
        self.number = 1


def peindre(widget, largeur, hauteur):
    """Rend le widget dans une image et la retourne, prete a etre relue pixel par pixel."""
    widget.resize(largeur, hauteur)
    image = QImage(largeur, hauteur, QImage.Format_RGB32)
    widget.render(image)
    return image


def coin(image):
    return image.pixelColor(0, 0).rgb() & 0xFFFFFF


def test_sans_etirement_les_bandes_sont_au_fond_de_spyder():
    ecran = PyxelScreenWidget()
    ecran.set_frame(ImageFactice())

    # Panneau tres large : les bandes tombent a gauche et a droite.
    image = peindre(ecran, 600, 180)
    attendu = letterbox_color().rgb() & 0xFFFFFF
    assert coin(image) == attendu, (
        f"bande gauche en {coin(image):06x}, attendu le fond de Spyder {attendu:06x}")
    print("OK  sans etirement, les bandes restent au fond de Spyder")


def test_avec_etirement_les_bandes_prennent_la_couleur_du_bord():
    ecran = PyxelScreenWidget()
    ecran.set_edge_bleed(True)
    ecran.set_frame(ImageFactice())

    for largeur, hauteur, ou in ((600, 180, "sur les cotes"), (240, 500, "en haut")):
        image = peindre(ecran, largeur, hauteur)
        assert coin(image) == PALETTE[COULEUR_BORD], (
            f"bande {ou} en {coin(image):06x}, attendu la couleur de bord "
            f"{PALETTE[COULEUR_BORD]:06x}")

        # Les QUATRE coins, y compris ceux que l'arrondi d'un pixel peut laisser hors des
        # bandes : un coin reste au fond se verrait.
        for x, y in ((0, 0), (largeur - 1, 0), (0, hauteur - 1),
                     (largeur - 1, hauteur - 1)):
            couleur = image.pixelColor(x, y).rgb() & 0xFFFFFF
            assert couleur == PALETTE[COULEUR_BORD], (
                f"coin ({x}, {y}) en {couleur:06x} : il est reste au fond")
    print("OK  avec etirement, les bandes et les coins prennent la couleur du bord")


def test_l_image_elle_meme_ne_bouge_pas():
    """L'etirement comble les bandes ; il ne deplace ni ne deforme l'image.

    C'est la garantie qui compte : le meme rectangle qu'avant, donc les memes coordonnees
    de souris (`_widget_to_screen` s'appuie dessus) et aucune deformation.
    """
    sans = PyxelScreenWidget()
    sans.set_frame(ImageFactice())
    avec = PyxelScreenWidget()
    avec.set_edge_bleed(True)
    avec.set_frame(ImageFactice())

    for largeur, hauteur in ((600, 180), (240, 500), (317, 211)):
        sans.resize(largeur, hauteur)
        avec.resize(largeur, hauteur)
        assert sans._display_geometry() == avec._display_geometry(), (
            f"la geometrie de l'image change en {largeur}x{hauteur} : "
            f"{sans._display_geometry()} contre {avec._display_geometry()}")

    # Et le CENTRE reste bien le contenu, pas un bord etire.
    image = peindre(avec, 600, 180)
    centre = image.pixelColor(300, 90).rgb() & 0xFFFFFF
    assert centre == PALETTE[COULEUR_CENTRE], (
        f"le centre est en {centre:06x} : l'image n'est plus a sa place")
    print("OK  l'image garde exactement la meme geometrie, etirement ou pas")


def test_colle_en_haut_toute_la_place_passe_en_bas():
    """L'image touche le bord haut, et la seule bande est en bas."""
    ecran = PyxelScreenWidget()
    ecran.set_edge_bleed(True)
    ecran.set_align_top(True)
    ecran.set_frame(ImageFactice())

    ecran.resize(240, 500)
    gauche, haut, largeur, hauteur = ecran._display_geometry()
    assert haut == 0, f"l'image commence a {haut} px du haut au lieu de 0"
    # Toute la place restante est en bas, en UNE seule bande.
    assert 500 - hauteur > 0, "ce panneau ne laisse aucune bande : le cas n'est pas teste"

    image = peindre(ecran, 240, 500)
    # La premiere ligne est bien le HAUT de l'image, pas une bande...
    for x in (LARGEUR // 2, LARGEUR - 5):
        couleur = image.pixelColor(x, 0).rgb() & 0xFFFFFF
        assert couleur == PALETTE[COULEUR_BORD], (
            f"({x}, 0) en {couleur:06x} : l'image ne touche pas le bord haut")
    # ... et juste en dessous, le CONTENU commence deja.
    facteur = hauteur / HAUTEUR
    couleur = image.pixelColor(LARGEUR // 2, int(facteur * 3)).rgb() & 0xFFFFFF
    assert couleur == PALETTE[COULEUR_CENTRE], (
        f"le contenu n'a pas commence a {int(facteur * 3)} px du haut "
        f"(couleur {couleur:06x}) : il reste une bande en haut")
    # Et le bas est bien comble.
    couleur = image.pixelColor(LARGEUR // 2, 499).rgb() & 0xFFFFFF
    assert couleur == PALETTE[COULEUR_BORD], (
        f"la bande du bas est en {couleur:06x} : elle n'est pas comblee")
    print("OK  colle en haut, toute la place restante passe en bas")


def test_sans_alignement_l_image_reste_centree():
    """Le defaut ne change pas : un jeu se regarde au milieu."""
    ecran = PyxelScreenWidget()
    ecran.set_frame(ImageFactice())
    ecran.resize(240, 500)
    _, haut, _, hauteur = ecran._display_geometry()
    assert haut == (500 - hauteur) // 2, (
        f"l'image n'est plus centree verticalement : haut={haut}, "
        f"attendu {(500 - hauteur) // 2}")
    print("OK  sans alignement, l'image reste centree verticalement")


def test_le_contenu_est_rogne_aux_coins_arrondis():
    """Le contenu ne doit pas ressortir dans les coins, sous le cadre arrondi.

    Le cadre est un rectangle ARRONDI trace par-dessus, alors que l'image et les bandes
    etirees, elles, sont carrees : sans rognage, elles debordent dans les quatre coins et
    on les voit autour de l'arrondi (signale par l'utilisateur le 26/07/2026).
    """
    fond = letterbox_color().rgb() & 0xFFFFFF
    ecran = PyxelScreenWidget()
    ecran.set_edge_bleed(True)
    ecran.set_align_top(True)
    ecran.set_border_color("#455364", 4)
    ecran.set_frame(ImageFactice())

    image = peindre(ecran, 600, 400)
    for x, y in ((0, 0), (599, 0), (0, 399), (599, 399)):
        couleur = image.pixelColor(x, y).rgb() & 0xFFFFFF
        assert couleur == fond, (
            f"le coin ({x}, {y}) est en {couleur:06x} au lieu du fond {fond:06x} : "
            f"le contenu passe sous l'arrondi du cadre")

    # Le rognage ne doit RIEN retirer d'autre : au milieu de chaque bord, juste apres le
    # trait, on retrouve le contenu.
    for x, y in ((2, 200), (597, 200), (300, 2), (300, 397)):
        couleur = image.pixelColor(x, y).rgb() & 0xFFFFFF
        assert couleur != fond, (
            f"({x}, {y}) est reste au fond : le rognage mord sur le contenu")
    print("OK  le contenu s'arrete aux coins arrondis, et nulle part ailleurs")


def test_seul_le_panneau_des_ressources_etire():
    """Les jeux gardent les bandes : leur bord porte du decor."""
    from spyder_pyxel.spyder.widgets.panes import (
        PyxelGameWidget, PyxelStudioWidget,
    )
    assert PyxelStudioWidget.BORDS_ETIRES is True
    assert PyxelGameWidget.BORDS_ETIRES is False
    assert PyxelStudioWidget.ALIGNE_EN_HAUT is True
    assert PyxelGameWidget.ALIGNE_EN_HAUT is False
    print("OK  seul le panneau des ressources etire ses bords et colle en haut")


def main():
    app = QApplication.instance() or QApplication([])
    test_sans_etirement_les_bandes_sont_au_fond_de_spyder()
    test_avec_etirement_les_bandes_prennent_la_couleur_du_bord()
    test_l_image_elle_meme_ne_bouge_pas()
    test_colle_en_haut_toute_la_place_passe_en_bas()
    test_sans_alignement_l_image_reste_centree()
    test_le_contenu_est_rogne_aux_coins_arrondis()
    test_seul_le_panneau_des_ressources_etire()
    del app
    print("\nLES BANDES SONT COMBLEES DANS LE PANNEAU DES RESSOURCES, ET LA SEULEMENT")


if __name__ == "__main__":
    main()
