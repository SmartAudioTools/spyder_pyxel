# -*- coding: utf-8 -*-
"""Balayages de l'ecran pour cadencer le jeu (W574).

Le jeu tourne dans le noyau, sans fenetre : il ne peut pas voir l'ecran. Le panneau, lui,
est dans une fenetre de la session : QWindow.requestUpdate() lui livre un QEvent.UpdateRequest
au rythme ou le compositeur accepte une nouvelle image (frame callbacks sous Wayland ;
minuterie a la frequence de l'ecran ailleurs). A chaque evenement, on redemande le suivant
et on previent le pont, qui envoie un octet au jeu (PyxelChannel.send_vsync_tick) ; le jeu
joue une image tous les round(hz / fps) balayages par pyxel.step().

Alternative ecartee : un QOpenGLWidget et son signal frameSwapped. Un seul QOpenGLWidget
fait passer TOUTE la fenetre principale de Spyder en composition OpenGL (comportement
documente de Qt), pour un panneau qui peint aujourd'hui une QImage 256 x 256 en raster.
requestUpdate ne change rien au rendu ; a mesurer au matin (histogramme, w574/).
"""
from qtpy.QtCore import QEvent, QObject


class VsyncTicker(QObject):
    """Appelle `on_tick(hz)` a chaque image acceptee par le compositeur, tant qu'actif."""

    def __init__(self, on_tick, parent=None):
        super().__init__(parent)
        self._on_tick = on_tick
        self._window = None

    def start(self, window):
        if window is None or window is self._window:
            return
        self.stop()
        self._window = window
        window.installEventFilter(self)
        window.requestUpdate()

    def stop(self):
        if self._window is not None:
            try:
                self._window.removeEventFilter(self)
            except RuntimeError:
                pass  # fenetre flottante deja detruite par Qt
            self._window = None

    @property
    def active(self):
        return self._window is not None

    def eventFilter(self, obj, event):
        if obj is self._window and event.type() == QEvent.Type.UpdateRequest:
            screen = obj.screen()
            hz = screen.refreshRate() if screen is not None else 60.0
            self._on_tick(hz if hz > 0 else 60.0)
            obj.requestUpdate()
        return False  # l'evenement suit son cours : le panneau se repeint normalement
