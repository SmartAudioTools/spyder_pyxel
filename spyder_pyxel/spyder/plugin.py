# -*- coding: utf-8 -*-
"""Le greffon du panneau "Pyxel" : l'ecran du jeu lance depuis la console.

⚠ Ce greffon et PyxelStudio vivent dans deux modules distincts, obligatoirement :
cf. l'avertissement en tete de plugin_base.py.
"""

import qtawesome as qta

from spyder.utils.icon_manager import ima

from spyder_pyxel.spyder.config import (
    CONF_VERSION, GAME_CONF_DEFAULTS, GAME_CONF_SECTION)
from spyder_pyxel.spyder.plugin_base import PyxelPanePlugin
from spyder_pyxel.spyder.translations import _
from spyder_pyxel.spyder.widgets.panes import PyxelGameWidget


class PyxelGame(PyxelPanePlugin):
    """Panneau affichant le jeu Pyxel lance depuis la console."""

    NAME = "pyxel_game"  # doit etre identique au nom du point d'entree
    WIDGET_CLASS = PyxelGameWidget
    CONF_SECTION = GAME_CONF_SECTION
    CONF_DEFAULTS = GAME_CONF_DEFAULTS
    CONF_VERSION = CONF_VERSION

    @staticmethod
    def get_name():
        return _("Pyxel")

    @staticmethod
    def get_description():
        return _("Affiche dans un panneau l'ecran du jeu Pyxel lance depuis la console.")

    @classmethod
    def get_icon(cls):
        return qta.icon("mdi.gamepad-variant", color=ima.MAIN_FG_COLOR)
