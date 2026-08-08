# -*- coding: utf-8 -*-
"""
Le widget qui affiche l'ecran Pyxel et lui renvoie les entrees clavier/souris.
"""

import os

from qtpy.QtCore import QRect, QRectF, Qt, Signal
from qtpy.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from qtpy.QtWidgets import QSizePolicy, QWidget

from spyder_pyxel.spyder.widgets import keymap

# Couleur de repli des bandes laissees autour de l'image, utilisee seulement si la palette
# de Spyder n'est pas accessible (widget instancie hors de Spyder, dans les tests).
FALLBACK_LETTERBOX_COLOR = QColor(25, 35, 45)

_letterbox_color = None


def letterbox_color():
    """Couleur des bandes : celle du fond de Spyder, pour qu'elles ne se voient pas.

    On la prend dans la palette de Spyder plutot que de la figer, afin qu'elle suive le
    theme choisi par l'utilisateur (et le correctif de couleurs de ce depot, cf.
    Commun/scripts_installation/spyder_patch/patch_spyder_colors.py). L'import est fait ici et non en tete de module
    pour que le widget reste utilisable sans Spyder - c'est ce qui permet aux tests de
    l'instancier seul.

    Le resultat est memorise : cette fonction est appelee a chaque repeinture, donc
    jusqu'a 60 fois par seconde.
    """
    global _letterbox_color
    if _letterbox_color is None:
        try:
            from spyder.utils.palette import SpyderPalette

            _letterbox_color = QColor(SpyderPalette.COLOR_BACKGROUND_1)
        except Exception:
            _letterbox_color = FALLBACK_LETTERBOX_COLOR
    return _letterbox_color


class PyxelScreenWidget(QWidget):
    """Affiche les images publiees par le jeu et renvoie les entrees.

    L'agrandissement se fait TOUJOURS au plus proche voisin : SmoothPixmapTransform reste
    desactive dans paintEvent, donc aucun flou n'est jamais introduit et les couleurs
    affichees sont exactement celles de la palette.

    Par defaut l'image est affichee ENTIEREMENT, proportions conservees, aussi grande que
    le panneau le permet : des bandes apparaissent donc sur un seul axe. Le facteur reste
    continu, jamais arrondi. L'option "integer_scaling" le restreint a un entier - tous les
    pixels rigoureusement identiques - au prix de marges plus larges.
    """

    sig_key = Signal(int, bool)
    """(code Pyxel, enfoncee) - une touche ou un bouton de souris."""

    sig_mouse = Signal(int, int)
    """(x, y) en coordonnees de l'ecran du jeu."""

    sig_wheel = Signal(int, int)
    """(crans horizontaux, crans verticaux)."""

    sig_text = Signal(str)
    """Texte saisi, pour les champs de l'editeur de ressources."""

    sig_release_all = Signal()
    """Le panneau a perdu le focus : tout relacher."""

    sig_focus_out = Signal()
    """Cet ecran vient de perdre le clavier (cf. sig_focus_in)."""

    sig_focus_in = Signal()
    """Cet ecran vient de prendre le clavier.

    Necessaire parce que PluginMainWidget.focusInEvent ne se declenche que si le PANNEAU
    lui-meme prend le focus - jamais quand c'est un de ses enfants, ce qui est toujours le
    cas ici (on clique dans l'ecran, pas sur le panneau). Sans ce signal, le panneau ne
    sait pas qu'on vient d'y revenir, et ne met donc a jour ni son etat ni le titre de la
    fenetre.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = None
        # QImage ne copie pas le tampon qu'on lui donne : il faut garder une reference
        # vivante sur les octets, sinon on peint de la memoire liberee.
        self._pixels = None
        self._screen_size = (0, 0)
        self._display_rect = None
        self._pressed_buttons = set()
        self._placeholder = ""
        # Agrandissement a facteur entier (marges) ou plein panneau (defaut).
        self.integer_scaling = False
        # Bandes remplies par etirement des pixels de bord (cf. set_edge_bleed).
        self.edge_bleed = False
        # Image collee au bord HAUT plutot que centree verticalement (cf. set_align_top).
        self.align_top = False

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    # --- Contenu -----------------------------------------------------------

    def set_integer_scaling(self, enabled):
        """Bascule entre facteur entier (marges) et occupation totale du panneau."""
        enabled = bool(enabled)
        if enabled != self.integer_scaling:
            self.integer_scaling = enabled
            self._display_rect = None
            self.update()

    def set_edge_bleed(self, enabled):
        """Remplit les bandes en etirant les pixels de BORD de l'image, au lieu du fond.

        Le probleme : le panneau a la forme que l'utilisateur lui donne, l'ecran Pyxel a
        la sienne (240x180 pour l'editeur de ressources), et conserver les proportions
        laisse donc des bandes - en haut et en bas, ou sur les cotes selon la forme de
        l'onglet. Signale par l'utilisateur le 26/07/2026 : "la fenetre de Pyxel Studio
        ne remplit pas l'onglet".

        Etirer la premiere et la derniere COLONNE (ou LIGNE) de l'image comble ces bandes.
        Sur l'editeur de ressources, dont le pourtour est d'une seule couleur, le resultat
        est exactement celui d'une fenetre qui remplirait l'onglet : la couleur de fond de
        l'editeur va jusqu'au cadre.

        POURQUOI PAS L'AUTRE PISTE ENVISAGEE - initialiser Pyxel a la forme du panneau
        quand il lance Pyxel Studio. Elle ne donne rien de plus, pour beaucoup plus cher :
        les widgets de l'editeur sont poses a des coordonnees fixes dans 240x180
        (pyxel/editor/settings.py), agrandir l'ecran n'agrandit donc pas l'editeur - il
        laisse seulement du vide autour, et a la MEME echelle puisque le facteur reste
        commande par le petit cote. Il faudrait en plus faire redescendre la taille du
        panneau jusqu'au processus du jeu, et refaire un pyxel.resize() a chaque
        redimensionnement du dock. Ici, tout suit la souris sans rien echanger.

        ⚠ CE N'EST PAS UN DEFAUT SUR TOUTE IMAGE : un jeu dont le bord porte du decor
        verrait ce decor s'etirer en trainees. L'option reste donc a False par defaut, et
        n'est activee que par le panneau "Pyxel Studio" (BORDS_ETIRES dans panes.py).
        """
        enabled = bool(enabled)
        if enabled != self.edge_bleed:
            self.edge_bleed = enabled
            self.update()

    def set_align_top(self, enabled):
        """Colle l'image au bord HAUT au lieu de la centrer verticalement.

        Toute la place restante passe alors en bas, en une seule bande - au lieu d'etre
        partagee en deux. Demande de l'utilisateur le 26/07/2026 : "verticalement, peut-on
        n'etendre qu'en bas et aligner en haut sur le bord de l'onglet ?". La barre
        d'outils de l'editeur de ressources se retrouve ainsi toujours a la meme place,
        contre le haut du cadre, quelle que soit la hauteur du panneau.

        Horizontalement, rien ne change : l'image reste centree.
        """
        enabled = bool(enabled)
        if enabled != self.align_top:
            self.align_top = enabled
            self._display_rect = None
            self.update()

    def set_placeholder(self, text):
        """Message affiche quand aucun jeu ne tourne."""
        self._placeholder = text
        self.update()

    def clear_screen(self):
        self._image = None
        self._pixels = None
        self._screen_size = (0, 0)
        self.update()

    def set_frame(self, frame):
        """Affiche une image lue dans la memoire partagee."""
        image = QImage(
            frame.pixels, frame.width, frame.height, frame.width,
            QImage.Format_Indexed8,
        )
        # La palette Pyxel est en 0xRRGGBB ; Qt attend un ARGB, d'ou l'alpha force.
        image.setColorTable([0xFF000000 | color for color in frame.palette])

        self._pixels = frame.pixels
        self._image = image
        if self._screen_size != (frame.width, frame.height):
            self._screen_size = (frame.width, frame.height)
            self._display_rect = None
        self.update()

    # --- Geometrie ---------------------------------------------------------

    def _compute_display_rect(self):
        width, height = self._screen_size
        if width <= 0 or height <= 0:
            return None

        available_width = max(1, self.width())
        available_height = max(1, self.height())

        if self.integer_scaling:
            # Facteur entier : des pixels tous exactement de la meme taille, mais des
            # marges perdues des que le panneau n'est pas un multiple exact de l'ecran.
            scale = max(1, min(available_width // width, available_height // height))
            target_width, target_height = width * scale, height * scale
        else:
            # Par defaut : l'image ENTIERE reste visible, proportions conservees, aussi
            # grande que le panneau le permet. Des bandes apparaissent donc sur un seul
            # axe - celui ou le panneau est proportionnellement plus long que l'ecran du
            # jeu (demande explicite de l'utilisateur, 21/07/2026 : "ajouter la marge
            # verticalement ou horizontalement pour afficher toute l'image avec le bon
            # ratio").
            #
            # min() et non max() : c'est toute la difference entre "contenir" et
            # "recouvrir". Avec max(), l'image remplirait le panneau sans aucune marge
            # mais serait rognee sur l'axe le plus long - essaye, et refuse.
            #
            # Le facteur reste CONTINU, jamais arrondi a un entier : l'image est donc
            # toujours aussi grande que possible. L'option "integer_scaling" impose au
            # contraire un facteur entier, ce qui agrandit des marges deja presentes mais
            # rend tous les pixels rigoureusement identiques.
            #
            # L'interpolation reste au plus proche voisin (SmoothPixmapTransform est
            # desactive dans paintEvent) : aucun flou, aucune couleur inventee, les teintes
            # restent exactement celles de la palette.
            ratio = min(available_width / width, available_height / height)
            target_width = max(1, round(width * ratio))
            target_height = max(1, round(height * ratio))

        left = (available_width - target_width) // 2
        if self.align_top:
            top = 0
        else:
            top = (available_height - target_height) // 2
        return (left, top, target_width, target_height)

    # Fichier temoin : s'il existe, chaque calcul de geometrie est journalise a cote.
    # Un widget Qt vit dans le processus de Spyder, hors de portee de tout debogueur
    # externe, et mesurer une capture d'ecran est trompeur - surtout avec un affichage a
    # l'echelle 1,3, ou les pixels de la capture ne sont pas ceux de Qt. Ce temoin permet
    # de constater la geometrie REELLE plutot que de l'estimer a l'oeil.
    _DEBUG_FLAG = "/DATA/Python/SmartOS/HGIGNORED/pyxel_debug"
    _DEBUG_LOG = "/DATA/Python/SmartOS/HGIGNORED/pyxel_geometry.log"

    def _log_geometry(self, rect):
        try:
            if not os.path.exists(self._DEBUG_FLAG):
                return
            with open(self._DEBUG_LOG, "a", encoding="utf-8") as handle:
                handle.write(
                    f"widget={self.width()}x{self.height()} "
                    f"ecran={self._screen_size[0]}x{self._screen_size[1]} "
                    f"entier={self.integer_scaling} rect={rect}\n")
        except Exception:
            pass

    def _display_geometry(self):
        if self._display_rect is None:
            self._display_rect = self._compute_display_rect()
            self._log_geometry(self._display_rect)
        return self._display_rect

    def resizeEvent(self, event):
        self._display_rect = None
        super().resizeEvent(event)

    def set_border_color(self, couleur, rayon=4):
        """Fait dessiner un cadre par l'ECRAN lui-meme. `couleur=None` : aucun cadre.

        POURQUOI ICI, ET PAS SUR LE CONTENEUR D'ONGLETS. Le panneau "Pyxel Studio" est
        passe en mode document, pour que ses onglets et sa croix de fermeture soient
        ceux des autres panneaux ; or ce mode supprime le cadre du conteneur, meme
        defini entierement par une feuille de style (mesure du 26/07/2026 : le pixel de
        bordure passe de #455364 a la couleur du fond). Le cadre doit donc etre porte
        par le contenu — comme dans le panneau Terminal, et comme la console IPython qui
        porte le sien sur son QTextEdit.

        Et il est PEINT plutot que pose en feuille de style : cet ecran a un paintEvent
        opaque qui couvre tout son rectangle, une bordure de feuille de style serait
        recouverte a la premiere image.
        """
        self._border_color = couleur
        # ⚠ LE RAYON PEUT ARRIVER EN CHAINE. SpyderPalette.SIZE_BORDER_RADIUS vaut '4px'
        # — c'est une valeur de FEUILLE DE STYLE, pas un nombre. Passee telle quelle a
        # drawRoundedRect, elle leve DANS le paintEvent : PySide6 imprime l'exception, le
        # peintre reste desequilibre (« Painter ended with 1 saved states ») et le
        # processus tombe en segfault a la capture suivante. Diagnostic du 26/07/2026.
        self._border_radius = self._nombre(rayon, 4.0)
        self.update()

    @staticmethod
    def _nombre(valeur, defaut):
        """« 4px », « 4 » ou 4 -> 4.0. Toute autre forme -> `defaut`."""
        if isinstance(valeur, (int, float)):
            return float(valeur)
        try:
            return float(str(valeur).strip().rstrip("px"))
        except (TypeError, ValueError):
            return defaut

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), letterbox_color())
        self._paint_border(painter)

        if self._image is None:
            if self._placeholder:
                painter.setPen(QColor(150, 150, 160))
                painter.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap,
                                 self._placeholder)
            return

        geometry = self._display_geometry()
        if geometry is None:
            return
        left, top, width, height = geometry
        # ⚠ LE CONTENU DOIT ETRE ROGNE AUX COINS ARRONDIS. Sans cela il passe SOUS le
        # cadre et ressort dans les quatre coins, ou le trait s'incurve mais pas lui :
        # on voit alors les pixels etires deborder autour de l'arrondi (signale par
        # l'utilisateur le 26/07/2026). Le rognage se pose ICI et non autour du seul
        # etirement : l'image elle-meme deborde de la meme facon des qu'elle touche un
        # coin, ce qui est le cas des qu'elle remplit le panneau.
        chemin = self._chemin_du_cadre()
        if chemin is not None:
            painter.setClipPath(chemin)
        if self.edge_bleed:
            self._paint_edge_bleed(painter, left, top, width, height)
        # L'agrandissement est fait par le blit, sans QImage intermediaire : construire
        # une image mise a l'echelle a chaque frame allouerait plusieurs mega-octets par
        # seconde pour rien. SmoothPixmapTransform reste desactive (defaut de QPainter),
        # donc l'agrandissement se fait au plus proche voisin : des pixels nets, ce qui
        # est tout l'interet d'un moteur retro.
        painter.drawImage(QRect(left, top, width, height), self._image)
        # Le cadre EN DERNIER, et HORS rognage : l'image vient d'etre peinte par-dessus
        # tout le rectangle, y compris la ou passe la bordure. Son trait antialiase
        # recouvre du meme coup l'escalier laisse par le rognage, que Qt ne lisse pas.
        painter.setClipping(False)
        self._paint_border(painter)

    def _chemin_du_cadre(self):
        """Le contour arrondi du cadre, pour y rogner le contenu. `None` : pas de cadre.

        Exactement le rectangle que trace `_paint_border` — meme demi-pixel de retrait,
        meme rayon : le contenu s'arrete donc precisement la ou le trait passe.
        """
        if getattr(self, "_border_color", None) is None:
            return None
        rayon = getattr(self, "_border_radius", 4)
        chemin = QPainterPath()
        chemin.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                              rayon, rayon)
        return chemin

    def _paint_edge_bleed(self, painter, left, top, width, height):
        """Comble les bandes en etirant la colonne (ou la ligne) de bord de l'image.

        La geometrie de l'image, elle, ne bouge pas d'un pixel : on ne peint QUE ce qui
        serait reste du fond. C'est peint avant l'image, qui recouvre ensuite son propre
        rectangle.
        """
        source_largeur, source_hauteur = self._screen_size
        if source_largeur <= 0 or source_hauteur <= 0:
            return
        droite, bas = left + width, top + height

        # Les colonnes de bord vont d'un bord A L'AUTRE du widget, hauteur comprise : les
        # COINS sont ainsi couverts eux aussi. Ils n'existent que par l'arrondi d'un pixel
        # (les bandes sont sur un seul axe), mais un coin reste au fond se verrait.
        if left > 0:
            painter.drawImage(QRect(0, 0, left, self.height()), self._image,
                              QRect(0, 0, 1, source_hauteur))
        if droite < self.width():
            painter.drawImage(QRect(droite, 0, self.width() - droite, self.height()),
                              self._image,
                              QRect(source_largeur - 1, 0, 1, source_hauteur))
        if top > 0:
            painter.drawImage(QRect(left, 0, width, top), self._image,
                              QRect(0, 0, source_largeur, 1))
        if bas < self.height():
            painter.drawImage(QRect(left, bas, width, self.height() - bas), self._image,
                              QRect(0, source_hauteur - 1, source_largeur, 1))

    def _paint_border(self, painter):
        """Trace le cadre, s'il y en a un. Antialiase, comme ceux du theme."""
        couleur = getattr(self, "_border_color", None)
        if couleur is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        stylo = QPen(QColor(couleur))
        stylo.setWidth(1)
        painter.setPen(stylo)
        painter.setBrush(Qt.NoBrush)
        # Un demi-pixel de retrait : sans lui, un trait de largeur 1 deborde du
        # rectangle et se fait rogner d'un cote.
        rectangle = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rectangle, getattr(self, "_border_radius", 4),
                                getattr(self, "_border_radius", 4))
        painter.restore()

    # --- Souris ------------------------------------------------------------

    def _widget_to_screen(self, position):
        geometry = self._display_geometry()
        if geometry is None:
            return None
        left, top, width, height = geometry
        screen_width, screen_height = self._screen_size
        x = (position.x() - left) * screen_width / width
        y = (position.y() - top) * screen_height / height
        # On borne au lieu d'ignorer : l'editeur Pyxel, comme beaucoup de jeux, veut
        # savoir de quel cote le curseur est sorti pour continuer un glisser commence
        # dans l'ecran.
        x = min(max(x, 0.0), screen_width - 1.0)
        y = min(max(y, 0.0), screen_height - 1.0)
        return x, y

    def _emit_mouse_position(self, position):
        coordinates = self._widget_to_screen(position)
        if coordinates is not None:
            self.sig_mouse.emit(int(coordinates[0]), int(coordinates[1]))

    def mouseMoveEvent(self, event):
        self._emit_mouse_position(event.pos())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        self.setFocus(Qt.MouseFocusReason)
        self._emit_mouse_position(event.pos())
        code = keymap.pyxel_button_for_qt(event.button())
        if code is not None:
            self._pressed_buttons.add(code)
            self.sig_key.emit(code, True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._emit_mouse_position(event.pos())
        code = keymap.pyxel_button_for_qt(event.button())
        if code is not None:
            self._pressed_buttons.discard(code)
            self.sig_key.emit(code, False)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta()
        # Un cran de molette vaut 120 huitiemes de degre chez Qt ; Pyxel compte en crans.
        steps_x = delta.x() // 120
        steps_y = delta.y() // 120
        if steps_x or steps_y:
            self.sig_wheel.emit(steps_x, steps_y)
        event.accept()

    # --- Clavier -----------------------------------------------------------

    def focusNextPrevChild(self, next_child):
        # Sans cela, Tab sortirait du widget au lieu d'arriver au jeu - et Tab est une
        # touche courante dans un jeu comme dans l'editeur Pyxel.
        return False

    def keyPressEvent(self, event):
        codes = keymap.pyxel_keys_for_event(event)
        text = keymap.printable_text(event)

        if event.isAutoRepeat():
            # La repetition automatique de Qt renvoie des appuis alors que la touche
            # n'a jamais ete relachee : reaffirmer l'etat ne servirait a rien. En
            # revanche le texte, lui, doit bien se repeter (saisie dans l'editeur).
            if text:
                self.sig_text.emit(text)
            event.accept()
            return

        for code in codes:
            self.sig_key.emit(code, True)
        if text:
            self.sig_text.emit(text)

        if codes or text:
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat():
            # Relachement fictif insere par Qt entre deux repetitions : le prendre au
            # serieux ferait clignoter l'etat de la touche cote jeu.
            event.accept()
            return

        codes = keymap.pyxel_keys_for_event(event)
        for code in codes:
            self.sig_key.emit(code, False)

        if codes:
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusInEvent(self, event):
        self.sig_focus_in.emit()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        """Relache tout ce qui etait enfonce.

        Sans cela, cliquer ailleurs dans Spyder pendant qu'une touche est maintenue
        laisserait le personnage courir indefiniment : le relachement partirait vers un
        autre widget et le jeu ne le verrait jamais.
        """
        for code in list(self._pressed_buttons):
            self.sig_key.emit(code, False)
        self._pressed_buttons.clear()
        self.sig_release_all.emit()
        self.sig_focus_out.emit()
        super().focusOutEvent(event)
