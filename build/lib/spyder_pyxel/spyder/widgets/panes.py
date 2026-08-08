# -*- coding: utf-8 -*-
"""
Les deux panneaux Pyxel : de purs afficheurs, sans aucun bouton.

Tout se lance depuis la console (F5 pour un jeu). Les boutons de la version precedente -
executer, arreter, relancer, afficher la sortie - ne faisaient que reimplementer, en
double et en moins bien, ce que la console fait deja nativement ; ils n'existaient que
parce que le panneau possedait un processus que Spyder ne connaissait pas. Des que le jeu
tourne dans le noyau, ils perdent tous leur raison d'etre.

Le seul confort reellement perdu au passage est "relancer a chaque enregistrement", qui
demande maintenant deux gestes (Ctrl+S puis F5) au lieu d'un.
"""

import qtawesome as qta

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import QApplication, QVBoxLayout

from spyder.api.widgets.main_widget import PluginMainWidget
from spyder.utils.icon_manager import ima
from spyder.utils.palette import SpyderPalette
from spyder.widgets.tabs import BaseTabs, Tabs

from spyder_pyxel.bridge import protocol
from spyder_pyxel.spyder.bridge_manager import get_bridge
from spyder_pyxel.spyder.translations import _
from spyder_pyxel.spyder.widgets.screen import PyxelScreenWidget


class PyxelPaneWidget(PluginMainWidget):
    """Affiche les images portant son marqueur, et renvoie les entrees au bon noyau."""

    KIND = protocol.KIND_GAME
    PLACEHOLDER_TEXT = ""

    # Nombre d'images que le jeu doit produire APRES un arret du debogueur avant que le
    # panneau ne reprenne le clavier. C'est la seule facon de distinguer, sans deviner,
    # un `c` (le jeu repart pour de bon) d'un `n` sur un point d'arret atteint a chaque
    # image (une image, puis nouvel arret). A 30 images par seconde, cinq images font
    # 0,17 s : imperceptible quand on relance le jeu, jamais atteint quand on avance pas
    # a pas.
    FRAMES_BEFORE_REGRAB = 5

    # Barre d'onglets affichee meme quand il n'y a qu'un seul programme.
    # Vrai pour l'editeur de ressources : on y travaille sur des FICHIERS, et voir le nom
    # de celui qu'on edite vaut la bande de hauteur. Faux pour les jeux : un jeu veut tous
    # ses pixels, et un seul jeu n'a aucune ambiguite a lever. Des qu'il y en a deux, la
    # barre apparait dans les deux cas - c'est justement quand il faut les distinguer.
    ALWAYS_SHOW_TABS = False

    #: Nom d'onglet quand personne n'en a fourni (jeu lance par F5, par exemple).
    DEFAULT_TAB_TITLE = ""

    #: Classe d'onglets. `BaseTabs` pour les jeux ; `Tabs` pour l'editeur de ressources,
    #: qui veut l'aspect exact des autres panneaux — c'est la classe que
    #: PluginMainWidget._setup() reconnait (findChildren(Tabs)), et c'est d'elle que
    #: depend la hauteur des onglets donnee par la feuille globale : 44 px comme la
    #: console IPython, contre 29 avec BaseTabs (mesure du 26/07/2026).
    CLASSE_ONGLETS = BaseTabs

    #: Combler les bandes en etirant les pixels de bord de l'image, plutot que de les
    #: laisser au fond de Spyder (cf. PyxelScreenWidget.set_edge_bleed) ? Vrai pour
    #: l'editeur de ressources, dont le pourtour est d'une seule couleur : l'editeur
    #: remplit alors l'onglet quelle que soit sa forme. Faux pour les jeux, dont le bord
    #: porte du decor - il s'etirerait en trainees.
    BORDS_ETIRES = False

    #: Coller l'image au bord HAUT plutot que la centrer verticalement (cf.
    #: PyxelScreenWidget.set_align_top) ? Vrai pour l'editeur de ressources, dont la barre
    #: d'outils reste ainsi contre le haut du cadre quelle que soit la hauteur du panneau.
    #: Faux pour les jeux : un jeu se regarde au milieu.
    ALIGNE_EN_HAUT = False

    #: Ce panneau porte-t-il le chemin de son fichier dans le titre de la fenetre ?
    #: Vrai pour l'editeur de ressources, qui travaille sur des FICHIERS ; faux pour les
    #: jeux, qui n'en ont pas (un jeu est lance par F5, le greffon ne sait pas d'ou).
    SETS_WINDOW_TITLE = False

    def __init__(self, name=None, plugin=None, parent=None):
        super().__init__(name, plugin, parent)

        # Un ecran par programme en cours, dans un onglet portant son nom.
        #
        # ⚠ POURQUOI DES ONGLETS, ET NON UN SEUL ECRAN : plusieurs programmes du meme genre
        # peuvent tourner en meme temps, un par console. Deux editeurs ouverts sur deux
        # fichiers publient tous deux avec KIND_EDITOR ; peints sur un ecran unique, ils
        # font CLIGNOTER l'affichage entre les deux fichiers (constate par l'utilisateur le
        # 21/07/2026). C'est le CANAL qui identifie un programme, d'ou un ecran par canal.
        # BaseTabs, la classe d'onglets de Spyder : menu contextuel, widgets de coin et
        # comportements maison, plutot qu'un QTabWidget nu.
        #
        # PAS DE CADRE : demande explicite de l'utilisateur (31/07/2026), qui remplace le
        # cadre gris/bleu jadis pose ici (cf. l'historique de cette methode dans le depot
        # Mercurial pour le detail de sa mise en place, le 21/07/2026). _apply_tabs_stylesheet
        # ne fait plus que desactiver la bordure du theme global ; elle ne depend donc plus
        # du focus, mais garde son parametre pour ne pas changer la signature.
        self._tabs = self.CLASSE_ONGLETS(self)
        self._apply_tabs_stylesheet(focus=False)
        self._tabs.setMovable(True)
        self._tabs.currentChanged.connect(self._update_window_title)
        self._tabs.tabBar().setVisible(self.ALWAYS_SHOW_TABS)
        self._screens = {}           # canal -> PyxelScreenWidget

        # Ecran d'accueil, sans canal : porte le message d'invite tant que rien ne tourne.
        self.screen = self._new_screen()
        self.screen.set_placeholder(self.PLACEHOLDER_TEXT)
        self._tabs.addTab(self.screen, "")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)
        #: Garde une reference : c'est par la marge haute de CE layout qu'on reserve la
        #: bande de la barre d'onglets quand elle est masquee (QTabWidget ignore ses
        #: propres contentsMargins pour la geometrie de sa page).
        self._layout = layout
        self.setLayout(layout)

        self._bridge = get_bridge()
        self._bridge.sig_frame.connect(self._on_frame)
        self._bridge.sig_publisher_gone.connect(self._on_publisher_gone)
        self._bridge.sig_debug_waiting.connect(self._on_debug_waiting)
        self._subscribed = False
        # Numero de la derniere image vue, PAR CANAL : sert a reconnaitre un NOUVEAU
        # programme (son compteur repart de 1) pour lui donner le clavier et son onglet,
        # une seule fois.
        #
        # ⚠ PAR CANAL, et non un compteur unique pour tout le panneau. Chaque programme a
        # son propre compteur, et deux programmes publient en s'entrelacant : compare a
        # celui du voisin, un numero repart "en arriere" a presque chaque image. Le
        # panneau croyait donc voir un nouveau programme en permanence et ramenait
        # l'onglet de force - impossible de rester sur un autre fichier (constate par
        # l'utilisateur le 21/07/2026, juste apres la mise en place des onglets).
        self._last_frame_numbers = {}    # canal -> numero de la derniere image
        # Le panneau detenait le clavier quand le debogueur s'est arrete : il faudra le
        # lui rendre, mais seulement quand le jeu sera VRAIMENT reparti (cf.
        # _on_debug_waiting et FRAMES_BEFORE_REGRAB).
        self._keyboard_owed = False
        self._frames_since_resume = 0
        # Ou le clavier a ete pose en s'arretant : sert a reconnaitre, a la reprise, que
        # l'utilisateur l'a depuis deplace ailleurs lui-meme.
        self._console_control = None


    # --- API PluginMainWidget -----------------------------------------------

    def setup(self):
        # Aucun bouton : le panneau n'est qu'un afficheur. `setup` reste obligatoire
        # (PluginMainWidget leve NotImplementedError sinon).
        #
        # La barre d'outils du panneau est masquee : vide de toute action, elle ne ferait
        # que voler une bande de hauteur au jeu, ce qui va contre la demande "aucune
        # marge". On la masque au lieu de la supprimer : Spyder la construit de toute
        # facon, et une barre masquee reste inoffensive.
        toolbar = self.get_main_toolbar()
        if toolbar is not None:
            toolbar.setVisible(False)

    def update_actions(self):
        pass

    def render_toolbars(self):
        # Masque aussi la barre du COIN, celle qui porte le bouton "hamburger" (demande
        # utilisateur, 21/07/2026). Spyder ajoute ce bouton a TOUS les panneaux et y met
        # d'office quatre actions de dock (Deplacer, Detacher, Rattacher, Fermer, cf.
        # PluginMainWidget._setup). Les panneaux qui ont de vrais reglages y accrochent les
        # leurs au-dessus ; ici il n'y en a aucun, le menu se reduit donc a ces quatre
        # entrees et le bouton n'apprend rien.
        #
        # ⚠ POURQUOI ICI ET PAS DANS setup() : masquer le bouton dans setup() NE TIENT PAS.
        # Spyder appelle setup() puis, plus tard, render_toolbars() (le plugin le fait a la
        # fin de son __init__), et render() ajoute le bouton a la barre par
        # QToolBar.addWidget() - qui reparente le widget et le REMONTRE. Le masquage fait
        # avant etait donc systematiquement annule (constate en direct : bouton toujours la
        # apres redemarrage). On masque la barre elle-meme, apres son rendu.
        #
        # Et pourquoi la barre plutot que le seul bouton : une barre vide garderait ses
        # marges, donc une bande de hauteur - exactement ce que le masquage de la barre
        # d'outils principale, juste au-dessus, cherche a eviter.
        #
        # Au passage, cela explique aussi pourquoi le bouton apparaissait a GAUCHE sur ces
        # deux panneaux alors qu'il est a droite partout ailleurs : les deux barres se
        # partagent une QHBoxLayout ou la principale prend stretch=10000 et repousse celle du
        # coin a droite (PluginMainWidget._setup). Une QLayout ignorant les widgets masques,
        # masquer la barre principale supprimait cette poussee et la barre du coin retombait
        # a gauche.
        #
        # A savoir avant de revenir dessus : ce menu etait le SEUL point d'entree de
        # "Detacher" pour ce panneau. "Fermer" reste dans Affichage > Panneaux, et "Deplacer"
        # ne servait deja a rien avec "panes_locked = True" dans la configuration deployee.
        # Tout est masque, rien n'est supprime : rendre la barre visible suffit a retrouver
        # le bouton et son menu.
        super().render_toolbars()
        self._corner_toolbar.setVisible(False)

    # --- Images ---------------------------------------------------------------

    def _new_screen(self):
        """Un ecran neuf, cable sur les entrees. Les signaux portent l'ecran emetteur,
        pour que l'entree reparte vers LE canal de cet onglet et pas un autre."""
        screen = PyxelScreenWidget(self)
        screen.set_integer_scaling(self.get_conf("integer_scaling", default=False))
        screen.set_edge_bleed(self.BORDS_ETIRES)
        screen.set_align_top(self.ALIGNE_EN_HAUT)
        screen.sig_key.connect(
            lambda code, pressed, w=screen: self._send(w, "send_key", code, pressed))
        screen.sig_mouse.connect(
            lambda x, y, w=screen: self._send(w, "send_mouse", x, y))
        screen.sig_wheel.connect(
            lambda dx, dy, w=screen: self._send(w, "send_wheel", dx, dy))
        screen.sig_text.connect(
            lambda text, w=screen: self._send(w, "send_text", text))
        screen.sig_release_all.connect(
            lambda w=screen: self._send(w, "send_release_all"))
        screen.sig_focus_in.connect(self._on_screen_focused)
        screen.sig_focus_out.connect(self._on_screen_focus_lost)
        return screen

    def _on_screen_focused(self):
        """On vient de revenir dans ce panneau : se comporter comme les autres docks.

        PluginMainWidget.focusInEvent ne se declenche que si le PANNEAU prend le focus,
        jamais un de ses enfants - or c'est toujours un enfant ici, l'ecran du jeu. Le
        panneau ne "voyait" donc pas qu'on y revenait : ni son etat de panneau actif, ni
        le titre de la fenetre n'etaient mis a jour (signale par l'utilisateur le
        21/07/2026).
        """
        self._apply_tabs_stylesheet(focus=True)
        self._update_window_title()
        self.sig_focus_status_changed.emit(True)
        try:
            self.on_focus_in()
        except Exception:
            # Confort d'interface : jamais au prix d'une exception pendant un clic.
            pass

    def _screen_for(self, channel):
        """L'ecran de ce canal, cree au besoin avec son onglet."""
        screen = self._screens.get(channel)
        if screen is not None:
            return screen

        title = self._bridge.title(channel) or self.DEFAULT_TAB_TITLE
        if not self._screens:
            # Premier programme : on reprend l'onglet d'accueil plutot que d'en ajouter un
            # a cote, sinon le message d'invite resterait la en permanence.
            screen = self.screen
            self._tabs.setTabText(self._tabs.indexOf(screen), title)
        else:
            screen = self._new_screen()
            self._tabs.addTab(screen, title)
        self._screens[channel] = screen
        self._update_tab_bar()
        return screen

    def _update_window_title(self, *_args):
        """Porte le chemin du fichier de l'onglet courant dans le titre de la fenetre.

        Meme comportement, et meme format, que pour les fichiers ouverts dans l'editeur de
        Spyder (Commun/scripts_installation/spyder_patch/patch_spyder_window_title.py) : "Spyder - <chemin>".

        Ce correctif-la se rebranche sur sig_editor_focus_changed, donc reprend la main des
        qu'on revient dans l'editeur de texte. Les deux ne se battent pas : le dernier a
        avoir la main gagne, ce qui est exactement ce qu'on attend.
        """
        if not self.SETS_WINDOW_TITLE:
            return
        channel = self._channel_of(self._tabs.currentWidget())
        document = self._bridge.document(channel) if channel is not None else None
        if not document:
            return
        try:
            # Le greffon, et non self.window() : un panneau detache a sa propre fenetre,
            # et c'est bien le titre de la fenetre PRINCIPALE qu'on veut changer.
            main = self._plugin.main
        except AttributeError:
            return
        if main is None:
            return
        main.base_title = f"Spyder - {document}"
        main.setWindowTitle(main.base_title)

    def _apply_tabs_stylesheet(self, focus):
        """Retrait pur et simple du cadre (demande de l'utilisateur, 31/07/2026).

        Sans cette regle, le theme global de Spyder dessine quand meme un cadre autour de
        la page d'onglets (cf. QTabWidget#pyxel_studio_tabs::pane plus bas, meme motif pour
        Pyxel Studio) : il faut le desactiver explicitement, meme quand on ne veut rien a
        la place. `focus` n'est plus utilise - conserve pour ne pas changer la signature
        des appelants (_on_screen_focused, _on_screen_focus_lost, __init__).
        """
        self._tabs.setStyleSheet("QTabWidget::pane { border: 0; }")

    def _on_screen_focus_lost(self):
        """Le cadre ne redevient gris que si le clavier a QUITTE le panneau.

        Passer d'un onglet a l'autre produit un focus-out suivi d'un focus-in : sans ce
        controle, le cadre clignoterait a chaque changement d'onglet.
        """
        if not self.isAncestorOf(QApplication.focusWidget()):
            self._apply_tabs_stylesheet(focus=False)

    def get_focus_widget(self):
        """L'ecran de l'onglet courant, et non le panneau.

        Appele par Spyder quand le dock est remonte au premier plan. Sans cela le focus
        allait au panneau, donc a personne d'utile : il fallait encore cliquer dans
        l'ecran pour pouvoir jouer ou dessiner.
        """
        return self._tabs.currentWidget() or self

    def set_maximized_state(self, state):
        """Reprend le clavier un tour de boucle APRES "agrandir ce panneau".

        RAISE_AND_FOCUS (plugin_base.py) fait deja rappeler get_focus_widget().setFocus()
        AU MEME TOUR, dans layout.plugin.maximize_dockwidget() apres le reparentage
        (setCentralWidget). Insuffisant en pratique (signale par l'utilisateur le
        31/07/2026, confirme par une sonde sur QApplication.focusChanged : le focus
        atterrit sur le MainWindow, pas sur l'ecran) - le reparentage semble declencher,
        cote fenetre reelle (KWin/Wayland), une reactivation qui arrive APRES notre
        setFocus() synchrone et l'ecrase. Meme classe de defaut, et meme remede, que
        PyxelStudioWidget.showEvent un peu plus bas dans ce fichier : différer d'un tour de
        boucle avec QTimer.singleShot(0, ...) laisse la reactivation se produire d'abord.
        """
        super().set_maximized_state(state)
        if state:
            from qtpy.QtCore import QTimer

            def _reprendre_le_clavier():
                cible = self.get_focus_widget()
                if cible is not None and self.get_maximized_state():
                    cible.setFocus(Qt.OtherFocusReason)

            QTimer.singleShot(0, _reprendre_le_clavier)

    def _update_tab_bar(self):
        """La barre n'apparait que si elle apprend quelque chose (cf. ALWAYS_SHOW_TABS)."""
        self._tabs.tabBar().setVisible(
            self.ALWAYS_SHOW_TABS or self._tabs.count() > 1)

    def _channel_of(self, screen):
        for channel, candidate in self._screens.items():
            if candidate is screen:
                return channel
        return None

    def _on_frame(self, kind, frame, channel):
        if kind != self.KIND:
            return
        screen = self._screen_for(channel)
        screen.set_frame(frame)

        # Tant que le debogueur attend une commande, le clavier appartient a la console :
        # ni la reprise ci-dessous ni le demarrage d'un jeu ne doivent le lui reprendre.
        if self._bridge.is_debug_waiting(self.KIND):
            self._last_frame_numbers[channel] = frame.number
            return

        # Un nouveau jeu vient de demarrer : son compteur d'images repart de 1. On lui
        # donne alors le clavier, sinon les touches continuent d'aller a l'editeur de
        # texte et l'utilisateur doit cliquer dans l'ecran avant de pouvoir jouer.
        # Uniquement au demarrage : voler le focus a chaque image rendrait Spyder
        # inutilisable pendant qu'un jeu tourne.
        previous = self._last_frame_numbers.get(channel)
        self._last_frame_numbers[channel] = frame.number
        if previous is None or frame.number < previous:
            self._tabs.setCurrentWidget(screen)
            self._update_window_title()
            self._grab_keyboard_for_game()
            return

        # Reprise apres un arret du debogueur : on ne rend le clavier au jeu qu'une fois
        # qu'il produit reellement des images. C'est ce qui distingue un `c` (le jeu
        # repart) d'un `n` sur un point d'arret atteint a chaque image (le jeu avance
        # d'un cran et se rearrete aussitot). Rendre le clavier des la reprise ferait
        # clignoter le focus a chaque pas, et la commande suivante partirait dans le jeu.
        # Seules les images de l'onglet AFFICHE comptent pour rendre le clavier : celles
        # d'un programme en arriere-plan n'apprennent rien sur celui qu'on regarde.
        if self._keyboard_owed and screen is self._tabs.currentWidget():
            self._frames_since_resume += 1
            if self._frames_since_resume >= self.FRAMES_BEFORE_REGRAB:
                self._keyboard_owed = False
                if self._console_still_has_the_keyboard():
                    current = self._tabs.currentWidget()
                    if current is not None:
                        current.setFocus(Qt.OtherFocusReason)

    def _grab_keyboard_for_game(self):
        """Amene le panneau au premier plan et lui donne le clavier."""
        try:
            plugin = getattr(self, "_plugin", None)
            if plugin is not None:
                # Fait remonter le panneau s'il est masque derriere un autre onglet.
                plugin.switch_to_plugin()
        except Exception:
            # Le focus n'est qu'un confort : jamais au prix d'une exception qui
            # interromprait l'affichage du jeu.
            pass
        current = self._tabs.currentWidget()
        if current is not None:
            current.setFocus(Qt.OtherFocusReason)

    def _on_debug_waiting(self, kind, waiting):
        """Le debogueur de la console qui fait tourner ce jeu s'arrete, ou repart.

        C'est ce qui rend Ctrl+F5 utilisable. Sans cela, le panneau prend le clavier des
        la premiere image (donc des `pyxel.init()`, avant meme que le jeu n'affiche quoi
        que ce soit) et ne le rend jamais : l'invite `ipdb>` est bien la, dans la console,
        mais chaque `n`, `s` ou `c` tape par l'utilisateur est intercepte par
        PyxelScreenWidget.keyPressEvent et expedie au jeu, qui est justement arrete. Le
        debogueur parait fige alors que rien n'est casse - seul le clavier est mal
        aiguille.

        On ne rend le clavier que si le panneau le detenait : ne jamais deplacer un focus
        que l'utilisateur a pose ailleurs lui-meme.
        """
        if kind != self.KIND:
            return
        if waiting:
            self._frames_since_resume = 0
            if self._current_screen_has_focus():
                self._keyboard_owed = True
                control = self._bridge.console_control_for_kind(self.KIND)
                self._console_control = control
                if control is not None:
                    control.setFocus(Qt.OtherFocusReason)
                else:
                    current = self._tabs.currentWidget()
                    if current is not None:
                        current.clearFocus()
                # ⚠ Ce deplacement de focus declenche focusOutEvent, qui relache toutes
                # les touches encore enfoncees. Ce n'est pas un bonus, c'est ce qui rend
                # le correctif sur : sans le correctif, une touche maintenue pendant un
                # arret ne posait aucun probleme (le panneau gardait le focus, donc le
                # relachement physique lui parvenait). En rendant le clavier a la console
                # on cree le risque - le relachement part desormais dans la console - et
                # c'est focusOutEvent qui l'annule. Verifie par test_debug_mode.py.
        else:
            self._frames_since_resume = 0

    def _console_still_has_the_keyboard(self):
        """Le clavier est-il encore la ou on l'avait pose en s'arretant ?

        Sinon, c'est que l'utilisateur l'a deplace LUI-MEME pendant l'arret - typiquement
        un clic dans l'editeur pour relire du code. Reprendre le clavier a ce moment-la
        lui arracherait un focus qu'il vient de choisir (demande explicite de
        l'utilisateur, 21/07/2026). On s'abstient donc, et le jeu attend un clic.

        Le controle se fait ICI, a la reprise, et non par un suivi des changements de
        focus : c'est le seul instant qui compte, et cela rend le comportement
        auto-correcteur - si l'utilisateur revient dans la console avant de taper `c`, le
        jeu retrouve le clavier normalement.
        """
        control = self._console_control
        if control is None:
            # On n'avait pas trouve la console : on ne peut rien affirmer, et le
            # comportement d'origine (le jeu reprend le clavier) reste le plus utile.
            return True
        focused = QApplication.focusWidget()
        if focused is None:
            return True
        # Le widget de saisie de la console, ou n'importe lequel de ses enfants.
        while focused is not None:
            if focused is control:
                return True
            focused = focused.parentWidget()
        return False

    def _current_screen_has_focus(self):
        current = self._tabs.currentWidget()
        return current is not None and current.hasFocus()

    def _on_publisher_gone(self, kind, channel):
        """Ce programme s'est arrete : son onglet n'a plus lieu d'etre.

        On garde toujours AU MOINS un onglet, celui d'accueil : un QTabWidget vide
        n'afficherait rien du tout, pas meme le message d'invite.
        """
        if kind != self.KIND:
            return
        screen = self._screens.pop(channel, None)
        if screen is None:
            return
        if self._screens:
            index = self._tabs.indexOf(screen)
            if index >= 0:
                self._tabs.removeTab(index)
            screen.deleteLater()
        else:
            # Dernier programme : l'onglet redevient l'accueil au lieu de disparaitre.
            self.screen = screen
            screen.clear_screen()
            screen.set_placeholder(self.PLACEHOLDER_TEXT)
            self._tabs.setTabText(self._tabs.indexOf(screen), "")
        self._update_tab_bar()
        self._last_frame_numbers.pop(channel, None)
        self._keyboard_owed = False
        self._frames_since_resume = 0

    # --- Entrees --------------------------------------------------------------

    def _send(self, screen, method, *arguments):
        """Envoie une entree au canal de l'ONGLET qui l'a produite.

        ⚠ Et non au "canal actif du marqueur" comme avant : avec plusieurs onglets, les
        touches tapees dans l'un partiraient dans le programme d'un autre - celui qui a
        publie en dernier. Defaut invisible tant qu'un seul programme tournait.
        """
        channel = self._channel_of(screen)
        if channel is not None:
            getattr(channel, method)(*arguments)

    # --- Visibilite -----------------------------------------------------------

    def showEvent(self, event):
        # La relecture des canaux ne tourne que s'il existe un panneau visible pour la
        # regarder. Le profilage montre que l'affichage est de loin l'etage le plus cher
        # (1 a 3 ms par image contre 4 microsecondes pour la recopie) : ne pas le payer
        # quand personne ne regarde vaut mieux que de l'optimiser.
        if not self._subscribed:
            self._bridge.subscribe()
            self._subscribed = True
        self._update_window_title()
        super().showEvent(event)

    def hideEvent(self, event):
        if self._subscribed:
            self._bridge.unsubscribe()
            self._subscribed = False
        super().hideEvent(event)


class PyxelGameWidget(PyxelPaneWidget):

    KIND = protocol.KIND_GAME
    # Un jeu veut tous ses pixels : pas de barre d'onglets tant qu'il n'y en a qu'un.
    ALWAYS_SHOW_TABS = False
    DEFAULT_TAB_TITLE = _("Jeu")
    PLACEHOLDER_TEXT = _(
        "Lancez un script Pyxel avec F5 : son ecran s'affichera ici.\n\n"
        "Cliquez dans l'ecran pour lui donner le clavier et la souris."
    )

    def get_title(self):
        return _("Pyxel")


class PyxelStudioWidget(PyxelPaneWidget):

    #: Le panneau demande, le greffon fait : lui seul sait ouvrir un fichier dans la
    #: console dediee (meme decoupage que le panneau Terminal).
    sig_nouveau_fichier = Signal()

    #: Fermer un onglet demande d'ARRETER l'editeur qui le nourrit — sinon il continue de
    #: publier et son onglet reapparait a l'image suivante. Le panneau ne sait pas
    #: interrompre une console : il porte la demande, le greffon l'execute.
    sig_fermer_editeur = Signal(object)

    KIND = protocol.KIND_EDITOR
    CLASSE_ONGLETS = Tabs
    # Ici on travaille sur des FICHIERS : voir le nom de celui qu'on edite vaut la bande
    # de hauteur, meme quand il n'y en a qu'un. Mais SEULEMENT s'il y a un fichier :
    # l'onglet d'accueil, lui, n'apprend rien (demande de l'utilisateur, 26/07/2026 :
    # « on peut ne pas avoir d'onglet du tout quand aucun fichier pyxres est ouvert ? »).
    # C'est _update_tab_bar, redefini plus bas, qui fait la difference — pas ce drapeau,
    # qui ne connait que le nombre d'onglets et compterait l'accueil.
    ALWAYS_SHOW_TABS = True
    DEFAULT_TAB_TITLE = _("Ressources")
    # L'editeur de ressources fait 240x180 (pyxel/editor/settings.py) et le panneau a la
    # forme que l'utilisateur lui donne : sans cela, il reste des bandes en haut et en bas,
    # ou sur les cotes. Son pourtour etant d'une seule couleur, les etirer revient a le
    # faire remplir l'onglet.
    BORDS_ETIRES = True
    # Et l'image collee en haut : la barre d'outils de l'editeur reste contre le haut du
    # cadre, toute la place restante passant en une seule bande en bas.
    ALIGNE_EN_HAUT = True
    SETS_WINDOW_TITLE = True
    PLACEHOLDER_TEXT = _(
        "Editeur de ressources Pyxel.\n\n"
        "Appuyez sur le \"+\" en haut a droite pour creer un nouveau fichier de "
        "ressources.\n\n"
        "Ou lancez-en un depuis la console :\n"
        "    import pyxel.editor\n"
        "    pyxel.editor.App(\"mes_ressources.pyxres\", \"image\")\n\n"
        "Le fichier peut ne pas exister encore : c'est ainsi qu'on en cree un."
    )

    def get_title(self):
        return _("Pyxel Studio")

    # ------------------------------------------------------------------------
    # Aspect aligne sur les autres panneaux (demande de l'utilisateur, 26/07/2026 :
    # « adapte le panneau Pyxel Studio sur le modele du terminal »). Trois points :
    # le mode document — qui donne aux onglets la meme hauteur et a la croix de
    # fermeture la meme place que dans la console IPython et le Terminal —, la croix
    # elle-meme, et un « + » apres le dernier onglet pour creer un .pyxres.
    #
    # ⚠ Le mode document SUPPRIME le cadre du conteneur, meme defini entierement par une
    # feuille de style (mesure du 26/07/2026). Le cadre est donc peint par l'ECRAN
    # lui-meme (PyxelScreenWidget.set_border_color), ce qui le conserve a l'identique —
    # meme couleur, meme rayon, gris au repos et bleu au focus.
    # ------------------------------------------------------------------------

    #: Espace entre le dernier onglet et le bouton « + », en pixels.
    ECART_BOUTON = 4

    #: Hauteur d'une barre d'onglets de panneau, MESUREE sur le theme de Spyder le
    #: 26/07/2026 (44 px, identique a la console IPython). Sert tant que la barre n'a pas
    #: encore ete affichee : des qu'elle l'est, on retient sa hauteur reelle.
    HAUTEUR_BARRE_MESUREE = 44

    def __init__(self, name=None, plugin=None, parent=None):
        self._canaux_fermes = set()      # avant super() : _screen_for peut etre appele tot
        super().__init__(name, plugin, parent)
        self._tabs.setDocumentMode(True)
        self._tabs.set_close_function(self._fermer_onglet)
        # Le cadre ne passe plus par le conteneur : on l'ETEINT explicitement, et on le
        # confie aux ecrans. Une feuille vide ne suffit pas — la feuille GLOBALE de
        # Spyder continue alors de dessiner un cadre gris, insensible au focus, et l'on
        # se retrouve avec DEUX cadres imbriques : le gris du theme et le notre, bleu,
        # juste a l'interieur (mesure du 26/07/2026 : le pixel du bord lisait #455364
        # alors que l'ecran portait bien #1A72BB).
        # ⚠ POSEE SUR LE PANNEAU, PAS SUR LE CONTENEUR D'ONGLETS. Une feuille posee sur
        # un widget ecrase la feuille GLOBALE de Spyder pour tout ce qu'elle touche, y
        # compris ce qu'elle ne mentionne pas explicitement pour ses enfants : posee sur
        # le conteneur, elle faisait retomber la barre d'onglets a 29 px de haut au lieu
        # des 44 px des autres panneaux (mesure du 26/07/2026 — la regle
        # `QTabBar#pane-tabbar { height: 37px }` de Spyder ne s'appliquait plus).
        # Depuis le panneau, avec un selecteur nomme, la feuille globale reste en place.
        self._tabs.setObjectName("pyxel_studio_tabs")
        self.setStyleSheet("QTabWidget#pyxel_studio_tabs::pane { border: 0; }")
        self._appliquer_cadre_aux_ecrans(focus=False)
        self._garder_la_barre_du_coin_masquee()
        # La classe de base a montre la barre (ALWAYS_SHOW_TABS) : on tranche nous-memes,
        # sur le nombre de FICHIERS et non d'onglets. Sans cet appel, le panneau demarre
        # avec une barre vide (mesure du 26/07/2026 : barre visible, zero fichier).
        self._update_tab_bar()

    def setup(self):
        super().setup()
        from qtpy.QtCore import Qt as _Qt
        self._bouton_nouveau = self.create_toolbutton(
            "pyxel_studio_new_file",
            text=_("Nouveau fichier de ressources"),
            icon=qta.icon("mdi.plus", color=ima.MAIN_FG_COLOR),
            tip=_("Cree un fichier .pyxres et l'ouvre dans l'editeur."),
            triggered=self.sig_nouveau_fichier,
        )
        self._bouton_nouveau.setParent(self)
        self._bouton_nouveau.setFocusPolicy(_Qt.NoFocus)
        self._bouton_nouveau.show()
        self._tabs.tabBar().installEventFilter(self)
        self._tabs.installEventFilter(self)
        self._placer_bouton_nouveau()

    def showEvent(self, evenement):  # noqa: N802 - API Qt
        super().showEvent(evenement)
        # ⚠ DIFFERE D'UN TOUR DE BOUCLE. Masquer un widget PENDANT le showEvent deplace le
        # focus : le panneau ne prenait plus le clavier au demarrage, et le test du mode
        # debogage le voyait (« le panneau n'a pas pris le clavier au demarrage »,
        # reproduit deux fois le 26/07/2026). Un tour plus tard, le clavier est pose.
        from qtpy.QtCore import QTimer
        QTimer.singleShot(0, self._garder_la_barre_du_coin_masquee)

    def _garder_la_barre_du_coin_masquee(self):
        """Empeche la barre du COIN de reprendre 16 px quand on masque les onglets.

        LE MECANISME, mesure des deux cotes le 26/07/2026 (et c'est l'utilisateur qui a
        oriente la mesure : « l'encadre est a la bonne place ; c'est quand le dernier
        onglet vide est fermable qu'on a des problemes ») :

            barre d'onglets VISIBLE  -> le coin (le burger) vit DANS la barre d'onglets,
                                        la barre du coin est masquee, la rangee fait 0 px
            barre d'onglets MASQUEE  -> Spyder rend le coin a la barre du COIN, qui
                                        devient visible et haute de 16 px

        Les 16 px sont donc la CONSEQUENCE du masquage. Et comme c'est Spyder qui rallume
        cette barre a chaque deplacement du coin, un setVisible(False) une bonne fois ne
        tient pas (quatre variantes essayees, toutes sans effet). Le seul mecanisme qui
        marche est le meme que pour le burger vide du panneau Terminal : un filtre
        d'evenements qui remasque a chaque tentative d'affichage.
        """
        barre = getattr(self, "_corner_toolbar", None)
        if barre is None:
            return
        if not getattr(self, "_garde_barre_du_coin", False):
            barre.installEventFilter(self)
            self._garde_barre_du_coin = True
        barre.setVisible(False)

    def eventFilter(self, objet, evenement):  # noqa: N802 - API Qt
        """Replace le « + », et remasque la barre du coin des que Spyder la rallume."""
        from qtpy.QtCore import QEvent
        if (objet is getattr(self, "_corner_toolbar", None)
                and evenement.type() == QEvent.Show):
            objet.setVisible(False)
            return True
        if (objet in (self._tabs, self._tabs.tabBar())
                and evenement.type() in (QEvent.Resize, QEvent.LayoutRequest,
                                         QEvent.Show, QEvent.ChildAdded,
                                         QEvent.ChildRemoved)):
            self._placer_bouton_nouveau()
        return super().eventFilter(objet, evenement)

    def _placer_bouton_nouveau(self):
        """Le « + » se pose en haut a droite du panneau.

        Son parent est le CONTENEUR d'onglets et non la BARRE : la barre n'est large que
        de ses onglets, et un enfant positionne a droite du CONTENEUR serait sinon rogne
        s'il etait pose sur la barre.
        """
        bouton = getattr(self, "_bouton_nouveau", None)
        if bouton is None or getattr(self, "_placement_en_cours", False):
            return
        # ⚠ GARDE CONTRE LA RE-ENTREE. Deplacer, montrer ou remonter le bouton produit sur
        # son parent des evenements (LayoutRequest, ChildAdded) que notre propre filtre
        # ecoute : sans ce drapeau, chaque placement en declenche un autre, et la pile
        # deborde — segfault silencieux pendant un grab() (constate le 26/07/2026 en
        # rejouant les tests du greffon Pyxel).
        self._placement_en_cours = True
        try:
            self._placer_maintenant(bouton)
        finally:
            self._placement_en_cours = False

    def _placer_maintenant(self, bouton):
        """Le « + » reste EN HAUT A DROITE, quel que soit le nombre d'onglets.

        Demande de l'utilisateur (31/07/2026) : il suivait auparavant le dernier onglet, ce
        qui le deplacait a chaque fichier ouvert ou ferme - loin a droite le laisse a une
        place fixe, cf. le texte d'accueil qui la nomme explicitement.

        ⚠ RESERVER LA PLACE DU COIN D'ONGLETS (bouton "Agrandir le volet",
        patch_spyder_pane_maximize_button.py) QUAND LA BARRE EST VISIBLE. Ce coin est un
        cornerWidget natif de `self._tabs` (Qt), sa LARGEUR est fixee des la construction du
        panneau et ne varie pas quand la barre d'onglets apparait - seule sa HAUTEUR passe de
        0 a sa valeur reelle a ce moment-la (mesure du 01/08/2026 : coin 52 px de large dans
        les deux cas, haut de 0 px sans fichier ouvert puis de 43 px des qu'un fichier l'est).
        Sans cette reservation, le « + » se calait sur `self._tabs.width()` seul - qui ne
        bouge jamais, le CONTENEUR d'onglets gardant sa largeur totale - et se retrouvait
        exactement sous le bouton d'agrandissement des qu'il devenait visible : plus rien ne
        distinguait les deux a l'ecran, l'agrandissement dessine par-dessus (signale par
        l'utilisateur : « un nouveau bouton d'agrandissement apparait superpose au + »).
        Gardee sur `barre.isVisible()`, pas sur la hauteur du coin lui-meme : c'est le meme
        signal que la ligne juste en dessous, et il evite de retrancher a tort la largeur
        d'un coin present mais pas encore rendu (hauteur nulle, barre encore masquee).
        """
        barre = self._tabs.tabBar()
        taille = bouton.sizeHint()
        largeur_coin = 0
        if barre.isVisible():
            coin = self._tabs.cornerWidget(Qt.TopRightCorner)
            if coin is not None and coin.isVisible():
                largeur_coin = coin.width()
        x = self._tabs.width() - taille.width() - self.ECART_BOUTON - largeur_coin
        hauteur_barre = barre.height() if barre.isVisible() else barre.sizeHint().height()
        y = max(0, (hauteur_barre - taille.height()) // 2)
        bouton.setGeometry(x, y, taille.width(), taille.height())
        bouton.raise_()
        bouton.setVisible(True)

    def _fermer_onglet(self, index):
        """Ferme l'onglet, et avec lui l'editeur qui le nourrit.

        ⚠ RETIRER L'ONGLET NE SUFFIT PAS. L'editeur tourne dans sa console et continue de
        publier : `_on_frame` rappelle `_screen_for`, qui RECREE aussitot un onglet. Vu de
        l'utilisateur, le fichier « ne se ferme pas » (signale le 26/07/2026). Il faut
        donc deux choses : demander l'arret de l'editeur (le greffon interrompt sa
        console), et ignorer les images qui arriveraient encore de ce canal.

        On garde toujours au moins l'onglet d'accueil : un conteneur vide n'afficherait
        rien, pas meme le message d'invite — et ferait disparaitre le « + » avec la
        barre.
        """
        ecran = self._tabs.widget(index)
        canal = next((c for c, e in self._screens.items() if e is ecran), None)
        if canal is not None:
            self._screens.pop(canal, None)
            self._last_frame_numbers.pop(canal, None)
            self._canaux_fermes.add(canal)
            self.sig_fermer_editeur.emit(canal)
        if self._tabs.count() > 1:
            self._tabs.removeTab(index)
            ecran.deleteLater()
        else:
            # Dernier onglet : il redevient l'accueil, comme a l'arret d'un programme.
            self.screen = ecran
            ecran.clear_screen()
            ecran.set_placeholder(self.PLACEHOLDER_TEXT)
            self._tabs.setTabText(index, "")
        self._update_tab_bar()
        self._placer_bouton_nouveau()

    #: Canaux dont l'utilisateur a ferme l'onglet : leurs images sont ignorees jusqu'a ce
    #: que le programme s'arrete pour de bon (`_on_publisher_gone` les oublie).
    _canaux_fermes = None

    def _update_tab_bar(self):
        """La barre n'apparait que s'il y a au moins un FICHIER ouvert.

        L'onglet d'accueil ne compte pas : il ne porte pas de nom de fichier, donc il
        n'apprend rien et ne vaut pas sa bande de hauteur. Le panneau vide se reduit alors
        a son message d'invite — et au « + », qui reste visible et se replie en haut a
        gauche (cf. _placer_maintenant).
        """
        barre = self._tabs.tabBar()
        avec_fichiers = bool(self._screens)
        barre.setVisible(avec_fichiers)
        # ⚠ MASQUER LA BARRE NE DOIT PAS FAIRE MONTER LE CADRE. Sans la marge, la page
        # d'onglet recupere la hauteur liberee et le cadre du panneau devient plus haut
        # que celui des autres panneaux (defaut signale par l'utilisateur le 26/07/2026).
        # On garde donc la bande, vide : le cadre reste a sa place, et le « + » s'y loge.
        # ⚠ LA HAUTEUR A RESERVER SE MESURE, ELLE NE SE DEDUIT PAS. Ni sizeHint() ni
        # tabRect() ne donnent la bonne : tous deux valent 60 alors que la barre AFFICHEE
        # fait 44 px — c'est la feuille de style de Spyder qui impose cette hauteur, et
        # ces deux methodes ne la voient pas. Reserver 60 faisait descendre le cadre de
        # 16 px de trop (mesure du 26/07/2026 : cadre a 60 px du haut du panneau, contre
        # 44 pour la console IPython).
        # On retient donc la hauteur REELLE des que la barre a ete affichee une fois, et
        # on part de la valeur mesuree sur ce theme tant que ce n'est pas arrive.
        if avec_fichiers and barre.height() > 0:
            self._hauteur_barre = barre.height()
        hauteur = 0 if avec_fichiers else getattr(
            self, "_hauteur_barre", self.HAUTEUR_BARRE_MESUREE)
        marges = self._layout.contentsMargins()
        self._layout.setContentsMargins(marges.left(), hauteur,
                                        marges.right(), marges.bottom())
        self._placer_bouton_nouveau()

    def _on_frame(self, kind, frame, channel):
        """Ignore les images d'un canal ferme — sauf si un NOUVEAU programme y demarre.

        ⚠ LA CONSOLE DEDIEE EST REUTILISEE. Fermer un onglet puis creer un fichier relance
        un editeur DANS LA MEME CONSOLE, donc sur le MEME canal : si le canal restait
        marque ferme, le nouvel editeur n'aurait jamais d'onglet (defaut signale par
        l'utilisateur le 26/07/2026, avec en prime une AttributeError a chaque image).
        Le numero d'image tranche : un programme neuf repart de 1, celui qu'on vient de
        fermer continue de compter.

        Le filtre est ICI et non dans `_screen_for` : celui-ci doit toujours rendre un
        ecran, la classe de base ne verifiant pas son resultat — c'est ce qui produisait
        « 'NoneType' object has no attribute 'set_frame' ».
        """
        if kind == self.KIND and channel in (self._canaux_fermes or ()):
            if frame.number > 1:
                return                      # le meme editeur publie encore : on l'ignore
            self._canaux_fermes.discard(channel)   # un nouveau : on rouvre le canal
        super()._on_frame(kind, frame, channel)

    def _on_publisher_gone(self, kind, channel):
        if self._canaux_fermes is not None:
            self._canaux_fermes.discard(channel)
        super()._on_publisher_gone(kind, channel)

    def _appliquer_cadre_aux_ecrans(self, focus):
        couleur = (SpyderPalette.COLOR_ACCENT_3 if focus
                   else SpyderPalette.COLOR_BACKGROUND_4)
        for index in range(self._tabs.count()):
            ecran = self._tabs.widget(index)
            if hasattr(ecran, "set_border_color"):
                ecran.set_border_color(couleur, SpyderPalette.SIZE_BORDER_RADIUS)

    def _apply_tabs_stylesheet(self, focus):
        """Le cadre est peint par les ecrans, pas par le conteneur (cf. l'en-tete)."""
        self._appliquer_cadre_aux_ecrans(focus)
