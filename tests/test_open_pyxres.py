# -*- coding: utf-8 -*-
"""
Ouvrir un .pyxres ouvre l'editeur de ressources, sans rien taper.

CE QUI CHANGE
Jusqu'ici l'editeur ne se lancait qu'en tapant a la main dans la console :
    import pyxel.editor ; pyxel.editor.App("fichier.pyxres", "image")
Desormais, ouvrir un .pyxres par n'importe quel chemin de Spyder le fait pour nous.

POURQUOI CE N'EST PAS UN DETOURNEMENT
Spyder prevoit ce cas : Application.open_file_in_plugin parcourt les greffons, retient le
premier dont FILE_EXTENSIONS contient l'extension du fichier, appelle son
switch_to_plugin() puis son open_file(). Tout y converge - double-clic dans le panneau
Fichiers ou dans un projet, menu Fichier > Ouvrir, et fichier passe en ligne de commande
(donc depuis Dolphin). Le test reproduit cette selection avec la MEME regle que Spyder,
pour qu'un changement d'attribut de notre cote se voie ici.

CE QUE CE TEST NE COUVRE PAS
Le lancement reel de l'editeur dans un vrai noyau : c'est test_mouse_and_editor.py qui
s'en charge. Ici on verifie l'aiguillage et l'orchestration - quelle console, dans quel
ordre, et avec quelle commande.

Lancement :
    QT_QPA_PLATFORM=offscreen python tests/test_open_pyxres.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spyder_pyxel.bridge import reader  # noqa: E402
from spyder_pyxel.spyder.plugin_studio import (  # noqa: E402
    STUDIO_CONSOLE_NAME, PyxelStudio, editor_command)


# =============================================================================
# 1. La commande envoyee a la console
# =============================================================================

def test_la_commande_est_celle_qu_on_tapait_a_la_main():
    commande = editor_command("/home/x/jeu/ressources.pyxres")
    assert commande == (
        "import pyxel.editor; "
        "pyxel.editor.App('/home/x/jeu/ressources.pyxres', 'image')"), commande
    print(f"OK  commande : {commande}")


def test_les_chemins_biscornus_sont_cites_correctement():
    """Un chemin est une donnee, pas du code : il doit traverser repr(), pas un f-string.

    Sans cela, un dossier contenant une apostrophe - courant en francais - casserait la
    ligne envoyee a la console, et un chemin bien choisi y executerait n'importe quoi.
    """
    for chemin in ["/home/x/l'atelier/r.pyxres",
                   '/home/x/dossier "cite"/r.pyxres',
                   "/home/x/avec espace/r.pyxres",
                   "/home/x/retour\nligne.pyxres"]:
        commande = editor_command(chemin)
        # On execute la commande dans un espace de noms bidon, en remplacant l'import et
        # l'appel : si la citation est correcte, l'argument recu est exactement le chemin.
        recu = {}

        class FauxEditeur:
            @staticmethod
            def App(fichier, genre):
                recu["fichier"] = fichier

        module = type(sys)("pyxel")
        module.editor = FauxEditeur
        espace = {"__builtins__": __builtins__}
        sys.modules["pyxel"] = module
        sys.modules["pyxel.editor"] = FauxEditeur
        try:
            exec(commande, espace)
        finally:
            sys.modules.pop("pyxel", None)
            sys.modules.pop("pyxel.editor", None)
        assert recu.get("fichier") == chemin, (
            f"chemin deforme : {recu.get('fichier')!r} au lieu de {chemin!r}")
    print("OK  apostrophes, guillemets, espaces et sauts de ligne traverses intacts")


# =============================================================================
# 2. Spyder nous confierait bien le fichier
# =============================================================================

def test_spyder_aiguillerait_un_pyxres_vers_ce_greffon():
    """Reproduit la regle de selection d'Application.open_file_in_plugin.

    On la recopie plutot que de l'appeler : l'appeler demanderait un Spyder complet.
    La recopie a un cout - elle peut deriver - mais elle rend visible le contrat exact
    dont on depend, et c'est ce contrat qui doit casser bruyamment s'il change.
    """
    from spyder.api.plugins import SpyderDockablePlugin

    assert issubclass(PyxelStudio, SpyderDockablePlugin), (
        "open_file_in_plugin ne considere que les greffons dockables")
    for nom in (".pyxres",):
        assert nom in PyxelStudio.FILE_EXTENSIONS
    assert callable(getattr(PyxelStudio, "open_file", None)), (
        "FILE_EXTENSIONS sans open_file : Spyder appellerait une methode inexistante")

    # L'extension est comparee telle quelle a osp.splitext()[1], donc avec le point.
    for extension in PyxelStudio.FILE_EXTENSIONS:
        assert extension.startswith("."), (
            f"{extension!r} : Spyder compare a osp.splitext()[1], qui garde le point")
    print(f"OK  Spyder confierait un .pyxres a {PyxelStudio.NAME}")


def test_le_greffon_des_jeux_ne_revendique_aucune_extension():
    """Les deux greffons ne doivent pas se disputer le fichier.

    open_file_in_plugin retient le PREMIER greffon qui declare l'extension, dans l'ordre
    du registre - un ordre sur lequel on n'a aucune prise. Deux greffons revendiquant
    .pyxres donneraient donc un comportement dependant de l'ordre de chargement.
    """
    from spyder_pyxel.spyder.plugin import PyxelGame

    assert not getattr(PyxelGame, "FILE_EXTENSIONS", []), (
        "le panneau des jeux revendique une extension : il pourrait rafler les .pyxres")
    print("OK  le panneau des jeux ne revendique rien")


# =============================================================================
# 3. L'orchestration : quelle console, dans quel ordre
# =============================================================================

class FausseConsole:
    """Le shellwidget vu par le greffon : on n'a besoin que d'execute()."""

    def __init__(self, nom="console"):
        self.nom = nom
        self.executees = []

    def execute(self, code):
        self.executees.append(code)


class FauxPluginConsole:
    def __init__(self):
        self.creations = []

    def create_new_client(self, give_focus=True, given_name=None):
        self.creations.append({"give_focus": give_focus, "given_name": given_name})


class FauxPont:
    """Le pont reduit a ce que l'orchestration lui demande."""

    def __init__(self):
        from qtpy.QtCore import QObject, Signal

        class _S(QObject):
            sig_console_hooked = Signal(object)

        self._s = _S()
        self.sig_console_hooked = self._s.sig_console_hooked
        self._channels = {}
        self._hooked = set()
        self.occupees = set()
        self.titres = {}
        self.documents = {}

    def channels(self):
        return dict(self._channels)

    def set_title(self, shellwidget, title, document=None):
        self.titres[shellwidget] = title
        self.documents[shellwidget] = document

    def is_hooked(self, shellwidget):
        return shellwidget in self._hooked

    def is_busy_with_pyxel(self, shellwidget):
        return shellwidget in self.occupees


def faire_greffon(pont, plugin_console):
    """Un PyxelStudio utilisable sans MainWindow.

    On court-circuite __init__ (qui exigerait tout Spyder) mais on garde les VRAIES
    methodes : c'est bien le code d'orchestration du greffon qui est exerce.
    """
    import spyder_pyxel.spyder.plugin_studio as module
    from qtpy.QtCore import QObject

    greffon = PyxelStudio.__new__(PyxelStudio)
    # ⚠ Sans cet appel, l'objet C++ sous-jacent n'existe pas et connect() sur une methode
    # de ce greffon n'aboutit jamais - silencieusement. Le test echouait alors sur
    # "l'editeur n'a pas demarre", en accusant le produit d'un defaut du banc d'essai.
    QObject.__init__(greffon)
    greffon._studio_shellwidget = None
    greffon._pending = None
    greffon.get_plugin = lambda nom, error=False: plugin_console
    greffon.switch_to_plugin = lambda: None
    module.get_bridge = lambda: pont
    return greffon


def test_sans_console_dediee_on_en_cree_une_et_on_attend_le_crochet():
    """Le piege : lancer l'editeur avant que le crochet soit pose.

    Il ouvrirait alors sa PROPRE fenetre au lieu du panneau, et le panneau resterait
    vide - sans le moindre message, puisque rien n'a echoue.
    """
    pont, plugin_console = FauxPont(), FauxPluginConsole()
    greffon = faire_greffon(pont, plugin_console)

    greffon.open_file("/x/r.pyxres")

    assert len(plugin_console.creations) == 1, plugin_console.creations
    assert plugin_console.creations[0]["given_name"] == STUDIO_CONSOLE_NAME
    assert plugin_console.creations[0]["give_focus"] is False, (
        "la nouvelle console ne doit pas voler le focus : c'est le panneau qu'on regarde")
    print(f"OK  une console dediee {STUDIO_CONSOLE_NAME!r} est creee, sans voler le focus")

    console = FausseConsole()
    assert not console.executees, "l'editeur a demarre AVANT que le crochet soit pose"

    pont.sig_console_hooked.emit(console)
    assert console.executees == [editor_command("/x/r.pyxres")], console.executees
    print("OK  l'editeur ne demarre qu'une fois le crochet pose")
    assert greffon._studio_shellwidget is console
    assert greffon._pending is None


def test_la_console_dediee_est_reutilisee_si_elle_est_libre():
    """Sinon on empilerait une console par fichier ouvert."""
    pont, plugin_console = FauxPont(), FauxPluginConsole()
    greffon = faire_greffon(pont, plugin_console)

    console = FausseConsole()
    greffon.open_file("/x/un.pyxres")
    pont.sig_console_hooked.emit(console)
    pont._channels[console] = object()
    pont._hooked.add(console)

    greffon.open_file("/x/deux.pyxres")
    assert len(plugin_console.creations) == 1, (
        f"une seconde console a ete creee : {plugin_console.creations}")
    assert console.executees == [editor_command("/x/un.pyxres"),
                                 editor_command("/x/deux.pyxres")], console.executees
    print("OK  la console dediee est reutilisee, pas empilee")


def test_une_console_occupee_par_un_programme_pyxel_n_est_pas_reutilisee():
    """⚠ Un noyau n'execute qu'UN programme Pyxel a la fois : pyxel.run() bloque.

    Envoyer l'editeur dans une console ou un jeu tourne ne ferait RIEN du tout - la ligne
    resterait en attente derriere la boucle du jeu, sans le moindre message. C'est le
    genre de panne qu'on met une heure a comprendre.
    """
    pont, plugin_console = FauxPont(), FauxPluginConsole()
    greffon = faire_greffon(pont, plugin_console)

    console = FausseConsole()
    greffon.open_file("/x/un.pyxres")
    pont.sig_console_hooked.emit(console)
    pont._channels[console] = object()
    pont._hooked.add(console)
    pont.occupees.add(console)          # l'editeur precedent tourne toujours

    greffon.open_file("/x/deux.pyxres")
    assert len(plugin_console.creations) == 2, (
        "la console occupee a ete reutilisee : la commande serait restee en attente "
        "derriere pyxel.run(), sans aucun message")
    assert console.executees == [editor_command("/x/un.pyxres")], console.executees
    print("OK  une console occupee par Pyxel n'est jamais reutilisee")


# =============================================================================
# 4. Deux fichiers ouverts en meme temps : un onglet chacun
# =============================================================================

def test_deux_editeurs_ont_chacun_leur_onglet():
    """Le defaut signale par l'utilisateur le 21/07/2026 : "il s'ouvre dans la meme
    fenetre et ca clignote".

    Deux editeurs ouverts sur deux fichiers publient TOUS DEUX avec KIND_EDITOR. Tant que
    le panneau ne recevait que (marqueur, image), il les peignait sur le meme ecran :
    l'affichage alternait entre les deux fichiers a chaque image. C'est le CANAL, et lui
    seul, qui identifie un programme.
    """
    from qtpy.QtWidgets import QApplication

    from spyder_pyxel.bridge import protocol as proto
    from spyder_pyxel.spyder import bridge_manager
    from spyder_pyxel.spyder.plugin_studio import PyxelStudio as _P
    from test_widgets_build import build

    app = QApplication.instance() or QApplication([])
    bridge_manager._bridge = None
    bridge = bridge_manager.get_bridge()
    widget = build(_P)

    class FauxCanal:
        """Un canal reduit aux entrees : le panneau lui en envoie des qu'il perd le
        focus (relachement general), y compris pendant show()/hide()."""

        def send_key(self, code, pressed):
            pass

        def send_mouse(self, x, y):
            pass

        def send_wheel(self, dx, dy):
            pass

        def send_text(self, text):
            pass

        def send_release_all(self):
            pass

    canal_a, canal_b = FauxCanal(), FauxCanal()
    bridge._titles[canal_a] = "heros.pyxres"
    bridge._titles[canal_b] = "decor.pyxres"

    def image(numero, couleur):
        return reader.Frame(4, 4, bytes([couleur]) * 16, [0] * 16, numero)

    bridge.sig_frame.emit(proto.KIND_EDITOR, image(1, 3), canal_a)
    app.processEvents()
    bridge.sig_frame.emit(proto.KIND_EDITOR, image(1, 9), canal_b)
    app.processEvents()

    assert widget._tabs.count() == 2, (
        f"{widget._tabs.count()} onglet(s) pour deux editeurs : ils se partagent le meme "
        "ecran, donc l'affichage clignote entre les deux fichiers")
    intitules = [widget._tabs.tabText(i) for i in range(widget._tabs.count())]
    assert intitules == ["heros.pyxres", "decor.pyxres"], intitules
    print(f"OK  deux editeurs -> deux onglets {intitules}")

    ecran_a = widget._screens[canal_a]
    ecran_b = widget._screens[canal_b]
    assert ecran_a is not ecran_b, "les deux onglets partagent le meme ecran"

    # Chaque ecran garde SON image : c'est ce que le clignotement violait.
    for numero, (ecran, couleur) in enumerate(((ecran_a, 3), (ecran_b, 9))):
        assert ecran._pixels[0] == couleur, (
            f"ecran {numero} : couleur {ecran._pixels[0]} au lieu de {couleur} - "
            "une image destinee a l'autre onglet y a ete peinte")
    print("OK  chaque onglet garde son image (plus d'alternance)")

    # Une entree tapee dans un onglet doit repartir vers SON canal, pas vers "le dernier
    # qui a publie" - sinon on piloterait le mauvais editeur.
    assert widget._channel_of(ecran_a) is canal_a
    assert widget._channel_of(ecran_b) is canal_b
    print("OK  les entrees de chaque onglet repartent vers son propre canal")

    # -- L'ONGLET CHOISI DOIT TENIR. Defaut signale par l'utilisateur le 21/07/2026,
    #    juste apres la mise en place des onglets : "spyder revient immediatement sur
    #    l'onglet du dernier fichier quand on clique sur un autre".
    #    Chaque programme a SON compteur d'images, et deux programmes publient en
    #    s'entrelacant. Compare au compteur du voisin, un numero repart "en arriere" a
    #    presque chaque image : avec un compteur unique pour tout le panneau, celui-ci
    #    croyait voir un nouveau programme en permanence et ramenait l'onglet de force.
    widget._tabs.setCurrentWidget(ecran_a)
    app.processEvents()
    assert widget._tabs.currentWidget() is ecran_a

    # Les deux continuent de publier, avec des compteurs qui n'ont aucun rapport entre eux
    # - c'est justement le cas qui declenchait le defaut.
    for tour in range(6):
        bridge.sig_frame.emit(proto.KIND_EDITOR, image(100 + tour, 3), canal_a)
        bridge.sig_frame.emit(proto.KIND_EDITOR, image(2 + tour, 9), canal_b)
        app.processEvents()
        assert widget._tabs.currentWidget() is ecran_a, (
            f"l'onglet a saute vers l'autre fichier au tour {tour + 1} : impossible de "
            "rester sur le fichier qu'on regarde")
    print("OK  l'onglet choisi tient malgre les deux editeurs qui publient")

    # -- LE CADRE DOIT ETRE DESSINE. Verifie en PEIGNANT le widget et en relisant la
    #    couleur de ses pixels de bordure, et non en inspectant une feuille de style :
    #    j'ai livre une regression (rev. 299) que seule une lecture de pixels pouvait
    #    attraper. J'avais recopie la feuille du panneau Historique en croyant y gagner un
    #    cadre ; elle le FAIT DISPARAITRE, une feuille posee sur un widget ecrasant la
    #    feuille globale de Spyder, et son "QTabWidget::pane { border: 1px }" n'ayant ni
    #    style ni couleur - Qt ne dessine alors rien. Mesure d'alors :
    #        sans feuille sur le widget : #455364 (COLOR_BACKGROUND_4) - cadre visible
    #        avec la feuille recopiee   : #19232d (le fond) - aucun cadre
    from qtpy.QtGui import QColor
    from spyder.utils.palette import SpyderPalette
    from spyder.utils.stylesheet import APP_STYLESHEET
    from spyder.widgets.tabs import BaseTabs

    assert isinstance(widget._tabs, BaseTabs), (
        f"{type(widget._tabs).__name__} : on veut la classe d'onglets de Spyder")

    app.setStyleSheet(str(APP_STYLESHEET))     # comme dans un vrai Spyder
    widget.resize(320, 200)
    widget.show()
    # Clavier HORS du panneau : le cadre doit etre gris ici. Son etat est rendu explicite,
    # sinon ce controle depend de ce que l'arrivee des images a laisse - une premiere image
    # donne le clavier au jeu (cf. _grab_keyboard_for_game).
    widget._tabs.currentWidget().clearFocus()
    app.processEvents()
    onglets = widget._tabs
    rendu = onglets.grab().toImage()
    largeur, hauteur = onglets.width(), onglets.height()
    haut_cadre = onglets.tabBar().height()
    bordure = SpyderPalette.COLOR_BACKGROUND_4.lower()

    def ton(x, y):
        return rendu.pixelColor(x, y).name().lower()

    # LES QUATRE COTES, au milieu de chacun - loin des coins, qui sont ARRONDIS.
    # Le theme global seul dessinait les cotes mais PAS la ligne du haut.
    cotes = {
        "bord haut": ton(largeur // 2, haut_cadre),
        "bord bas": ton(largeur // 2, hauteur - 1),
        "bord gauche": ton(0, (haut_cadre + hauteur) // 2),
        "bord droit": ton(largeur - 1, (haut_cadre + hauteur) // 2),
    }
    fautifs = {nom: vu for nom, vu in cotes.items() if vu != bordure}
    assert not fautifs, (
        f"cadre incomplet, attendu {bordure} sur les quatre cotes : {fautifs}. La bordure "
        "doit etre definie ENTIEREMENT (largeur, style ET couleur) : un 'border: 1px' "
        "sans style ne dessine rien, et le theme global seul oublie la ligne du haut.")

    # LES QUATRE COINS SONT ARRONDIS, comme tous les autres cadres de Spyder. On ne peut
    # donc pas tester le pixel d'angle exact - il est HORS de l'arc, donc au fond, et c'est
    # normal. On verifie que l'ARC est bien dessine : des pixels de bordure dans la zone du
    # coin. Sans bordure complete il n'y en aurait aucun, ce qui etait le defaut d'origine
    # ("les coins manquent de pixels") - il venait de la bordure, pas de l'arrondi.
    # ⚠ Compter les pixels EXACTEMENT a la couleur de bordure ne suffit pas : un arc est
    # ANTIALIASE, donc fait de teintes intermediaires. Un tel comptage m'a fait conclure a
    # tort que Qt ne dessinait pas d'arc du tout. On compte donc les pixels PLUS PROCHES
    # de la bordure que du fond.
    ton_bordure = QColor(SpyderPalette.COLOR_BACKGROUND_4)
    ton_fond = QColor(SpyderPalette.COLOR_BACKGROUND_1)

    def pixels_de_bordure(x0, y0, dx, dy):
        total = 0
        for i in range(6):
            for j in range(6):
                pixel = rendu.pixelColor(x0 + dx * i, y0 + dy * j)
                vers_bordure = sum(abs(a - b) for a, b in zip(
                    pixel.getRgb()[:3], ton_bordure.getRgb()[:3]))
                vers_fond = sum(abs(a - b) for a, b in zip(
                    pixel.getRgb()[:3], ton_fond.getRgb()[:3]))
                if vers_bordure < vers_fond:
                    total += 1
        return total

    arcs = {
        "coin haut-gauche": pixels_de_bordure(0, haut_cadre, 1, 1),
        "coin haut-droit": pixels_de_bordure(largeur - 1, haut_cadre, -1, 1),
        "coin bas-gauche": pixels_de_bordure(0, hauteur - 1, 1, -1),
        "coin bas-droit": pixels_de_bordure(largeur - 1, hauteur - 1, -1, -1),
    }
    # Seuil a 7 : l'arc complet en donne 9 a 10 ; recouvert par la page il en reste 4,
    # aux seules extremites. C'est ce que "il manque des bouts" designait.
    creves = {nom: n for nom, n in arcs.items() if n < 7}
    assert not creves, (
        f"arc de coin ronge : {creves} pixels de bordure sur une zone de 6x6, 9 a 10 "
        "attendus. Qt place la page d'onglet sans tenir compte du RAYON : un enfant "
        "opaque peint alors par-dessus l'arc. C'est le 'padding' de QTabWidget::pane qui "
        "l'en empeche - ne pas le retirer.")
    print(f"OK  cadre complet : quatre cotes a {bordure}, quatre coins arrondis "
          f"({min(arcs.values())} a {max(arcs.values())} pixels d'arc)")

    # -- LE LISERE D'ACCENTUATION SOUS L'ONGLET ACTIF, celui de qdarkstyle :
    #       QTabBar::tab:top:selected { border-bottom: 3px solid #259AE9; }
    #    Il fonctionne SANS RIEN FAIRE, la feuille globale de Spyder s'en charge. Ce test
    #    est la pour qu'une feuille posee sur les onglets ne le tue pas un jour sans qu'on
    #    s'en apercoive.
    #
    #    ⚠ MESURER SUR LA BARRE D'ONGLETS, PAS SUR LE WIDGET D'ONGLETS : tabRect() est en
    #    coordonnees de la BARRE, qui est decalee a l'interieur du QTabWidget. Sonder
    #    l'image du widget avec ces coordonnees m'a fait conclure DEUX FOIS que le lisere
    #    n'existait pas, et documenter un probleme qui n'en etait pas un.
    barre = widget._tabs.tabBar()
    rendu_barre = barre.grab().toImage()

    def bas_de_l_onglet(index):
        r = barre.tabRect(index)
        return [rendu_barre.pixelColor(r.center().x(), y).name().lower()
                for y in range(r.bottom() - 2, r.bottom() + 1)]

    accent = "#259ae9"
    actif = bas_de_l_onglet(widget._tabs.currentIndex())
    autre = bas_de_l_onglet(1 - widget._tabs.currentIndex())
    assert actif == [accent] * 3, (
        f"pas de lisere sous l'onglet actif : {actif}, attendu trois pixels {accent}. "
        "Une feuille de style posee sur les onglets a sans doute ecrase la regle "
        "QTabBar::tab:top:selected de la feuille globale.")
    assert accent not in autre, (
        f"l'onglet INACTIF porte le lisere ({autre}) : on ne distingue plus lequel est "
        "actif")
    print(f"OK  lisere {accent} sous l'onglet actif, et lui seul")

    # -- LE CADRE PASSE AU BLEU VIF QUAND LE PANNEAU A LE CLAVIER.
    #    Convention de Spyder, posee EN CODE et non dans une feuille de style - on la
    #    retrouve telle quelle dans spyder/widgets/emptymessage.py et browser.py :
    #        border_color = COLOR_ACCENT_3 si focus, sinon COLOR_BACKGROUND_4
    #    C'est pour cela qu'aucune recherche de ":focus" dans les feuilles ne la trouve.
    bleu_vif = SpyderPalette.COLOR_ACCENT_3.lower()

    def ton_du_cadre():
        image = onglets.grab().toImage()
        return image.pixelColor(
            0, (onglets.tabBar().height() + onglets.height()) // 2).name().lower()

    ecran_courant = widget._tabs.currentWidget()
    ecran_courant.setFocus()
    app.processEvents()
    assert ton_du_cadre() == bleu_vif, (
        f"cadre {ton_du_cadre()} alors que le panneau a le clavier, attendu {bleu_vif}. "
        "Spyder pose cette couleur EN CODE a chaque changement de focus, pas par une "
        "feuille de style.")
    print(f"OK  cadre {bleu_vif} quand le panneau a le clavier")

    # Passer d'un onglet a l'autre NE DOIT PAS eteindre le cadre : cela produit un
    # focus-out suivi d'un focus-in, et le cadre clignoterait a chaque changement.
    widget._tabs.setCurrentWidget(ecran_a)
    ecran_a.setFocus()
    app.processEvents()
    assert ton_du_cadre() == bleu_vif, (
        f"cadre {ton_du_cadre()} apres un changement d'onglet : il clignote")
    print("OK  changer d'onglet n'eteint pas le cadre")

    # Le clavier quitte le panneau : le cadre redevient gris.
    ecran_a.clearFocus()
    app.processEvents()
    assert ton_du_cadre() == bordure, (
        f"cadre {ton_du_cadre()} alors que le clavier est parti, attendu {bordure}")
    print(f"OK  cadre {bordure} quand le clavier quitte le panneau")
    widget.hide()

    # -- Le CHEMIN COMPLET du fichier de l'onglet courant doit aller dans le titre de la
    #    fenetre, comme Spyder le fait pour les fichiers de son editeur (demande
    #    utilisateur, 21/07/2026). L'onglet, lui, ne porte que le nom court.
    class FausseFenetre:
        def __init__(self):
            self.base_title = "Spyder"
            self.titre = None

        def setWindowTitle(self, titre):
            self.titre = titre

    class FauxGreffon:
        def __init__(self, fenetre):
            self.main = fenetre

    fenetre = FausseFenetre()
    widget._plugin = FauxGreffon(fenetre)
    bridge._documents[canal_a] = "/jeux/monkey/heros.pyxres"
    bridge._documents[canal_b] = "/jeux/monkey/decor.pyxres"

    widget._tabs.setCurrentWidget(ecran_b)
    app.processEvents()
    assert fenetre.titre == "Spyder - /jeux/monkey/decor.pyxres", fenetre.titre
    widget._tabs.setCurrentWidget(ecran_a)
    app.processEvents()
    assert fenetre.titre == "Spyder - /jeux/monkey/heros.pyxres", fenetre.titre
    print(f"OK  titre de la fenetre suit l'onglet : {fenetre.titre!r}")

    # Revenir dans le panneau (clic dans l'ecran) doit AUSSI reactualiser le titre : le
    # defaut signale le 21/07/2026 etait qu'on revenait sur Pyxel Studio sans que le titre
    # ne suive. PluginMainWidget.focusInEvent ne se declenche que si le PANNEAU prend le
    # focus, jamais un de ses enfants - or c'est toujours un enfant, l'ecran du jeu.
    fenetre.titre = None
    ecran_b.sig_focus_in.emit()
    app.processEvents()
    assert fenetre.titre == "Spyder - /jeux/monkey/heros.pyxres", (
        f"titre {fenetre.titre!r} : revenir dans le panneau n'a pas reactualise le titre")
    widget._tabs.setCurrentWidget(ecran_b)
    fenetre.titre = None
    ecran_b.sig_focus_in.emit()
    app.processEvents()
    assert fenetre.titre == "Spyder - /jeux/monkey/decor.pyxres", fenetre.titre
    print("OK  revenir dans le panneau reactualise le titre")

    # Et le panneau doit se declarer actif, comme les autres docks.
    actif = []
    widget.sig_focus_status_changed.connect(actif.append)
    ecran_b.sig_focus_in.emit()
    app.processEvents()
    assert actif == [True], (
        "le panneau ne signale pas qu'il a le focus : Spyder ne l'affichera pas comme "
        "actif, puisque c'est un ENFANT qui a pris le clavier")
    print("OK  le panneau se declare actif quand on clique dans son ecran")

    # Le panneau des JEUX ne doit PAS toucher au titre : un jeu n'a pas de fichier
    # (il est lance par F5, le greffon ne sait pas d'ou).
    from spyder_pyxel.spyder.widgets.panes import PyxelGameWidget, PyxelStudioWidget
    assert PyxelStudioWidget.SETS_WINDOW_TITLE
    assert not PyxelGameWidget.SETS_WINDOW_TITLE
    print("OK  le panneau des jeux ne touche pas au titre")

    # Fermeture de l'un : son onglet disparait, l'autre reste.
    bridge.sig_publisher_gone.emit(proto.KIND_EDITOR, canal_a)
    app.processEvents()
    assert widget._tabs.count() == 1, widget._tabs.count()
    assert canal_b in widget._screens and canal_a not in widget._screens
    print("OK  fermer un editeur retire son onglet et laisse l'autre")

    # Fermeture du dernier : on garde un onglet d'accueil, sinon plus rien ne s'affiche.
    bridge.sig_publisher_gone.emit(proto.KIND_EDITOR, canal_b)
    app.processEvents()
    assert widget._tabs.count() == 1, (
        "plus aucun onglet : le message d'invite n'a nulle part ou s'afficher")
    assert not widget._screens
    print("OK  le dernier onglet redevient l'accueil")

    # -- FERMER UN ONGLET DOIT FERMER LE FICHIER, et l'editeur ne doit pas le
    #    RESSUSCITER a l'image suivante. Defaut signale par l'utilisateur le 26/07/2026 :
    #    « je ne parviens pas a fermer un fichier pyxres ». L'editeur tourne dans sa
    #    console et continue de publier ; _on_frame rappelait _screen_for, qui recreait
    #    aussitot l'onglet. Ce controle ECHOUE sans le correctif.
    # DEUX editeurs : on veut fermer un onglet parmi d'autres, pas le dernier — fermer le
    # dernier a un comportement a part (il redevient l'accueil), deja teste plus haut.
    canal_c, canal_d = FauxCanal(), FauxCanal()
    bridge._titles[canal_c] = "sprite.pyxres"
    bridge._titles[canal_d] = "tuiles.pyxres"
    bridge.sig_frame.emit(proto.KIND_EDITOR, image(1, 5), canal_c)
    app.processEvents()
    bridge.sig_frame.emit(proto.KIND_EDITOR, image(1, 6), canal_d)
    app.processEvents()
    avant = widget._tabs.count()
    assert avant == 2, f"{avant} onglets, deux attendus avant la fermeture"

    demandes = []
    widget.sig_fermer_editeur.connect(demandes.append)
    widget._fermer_onglet(widget._tabs.indexOf(widget._screens[canal_c]))
    app.processEvents()

    assert demandes == [canal_c], (
        f"arret demande pour {demandes}, attendu [canal_c] : sans cette demande, "
        "l'editeur continue de tourner dans sa console et rien n'est vraiment ferme")
    assert widget._tabs.count() == avant - 1, "l'onglet ferme est encore la"

    # L'editeur n'a pas encore vu la demande et publie trois images de plus.
    for numero in range(2, 5):
        bridge.sig_frame.emit(proto.KIND_EDITOR, image(numero, 5), canal_c)
        app.processEvents()
    assert widget._tabs.count() == avant - 1, (
        "l'onglet ferme est revenu tout seul : les images d'un canal ferme doivent etre "
        "ignorees")

    # ET UN NOUVEL EDITEUR SUR LE MEME CANAL DOIT ROUVRIR UN ONGLET, tant que le canal est
    # encore marque ferme. La console dediee est REUTILISEE : fermer un onglet puis creer
    # un fichier relance un editeur dans la meme console, donc sur le meme canal. Si le
    # marquage survivait, le nouvel editeur n'aurait jamais d'onglet — et la classe de base
    # plantait en prime sur un ecran None (« 'NoneType' object has no attribute
    # 'set_frame' », signale par l'utilisateur le 26/07/2026). Le numero d'image tranche :
    # un programme neuf repart de 1.
    bridge._titles[canal_c] = "nouveau.pyxres"
    bridge.sig_frame.emit(proto.KIND_EDITOR, image(1, 7), canal_c)
    app.processEvents()
    assert widget._tabs.count() == avant, (
        "un editeur NEUF sur un canal ferme n'a pas rouvert son onglet : le marquage "
        "survit au programme qu'il visait")
    print("OK  un nouvel editeur sur le meme canal rouvre bien son onglet")

    # On le referme pour que la suite du test retrouve son compte.
    widget._fermer_onglet(widget._tabs.indexOf(widget._screens[canal_c]))
    app.processEvents()

    # Quand l'editeur s'arrete pour de bon, le canal est oublie : rouvrir le meme fichier
    # doit refonctionner.
    bridge.sig_publisher_gone.emit(proto.KIND_EDITOR, canal_c)
    app.processEvents()
    bridge.sig_frame.emit(proto.KIND_EDITOR, image(9, 5), canal_c)
    app.processEvents()
    assert widget._tabs.count() == avant, (
        "rouvrir le fichier apres l'arret de l'editeur ne recree pas son onglet : le "
        "canal est reste dans la liste des fermes")
    print("OK  fermer un onglet ferme l'editeur, et l'onglet ne revient pas")


    widget.deleteLater()


def main():
    test_la_commande_est_celle_qu_on_tapait_a_la_main()
    test_les_chemins_biscornus_sont_cites_correctement()
    test_spyder_aiguillerait_un_pyxres_vers_ce_greffon()
    test_le_greffon_des_jeux_ne_revendique_aucune_extension()
    print()
    test_sans_console_dediee_on_en_cree_une_et_on_attend_le_crochet()
    test_la_console_dediee_est_reutilisee_si_elle_est_libre()
    test_une_console_occupee_par_un_programme_pyxel_n_est_pas_reutilisee()
    print()
    test_deux_editeurs_ont_chacun_leur_onglet()
    print("\nOUVRIR UN .PYXRES LANCE L'EDITEUR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
