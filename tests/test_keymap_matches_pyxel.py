# -*- coding: utf-8 -*-
"""
Verifie que les codes recopies dans keymap.py sont bien ceux de Pyxel.

keymap.py duplique volontairement une trentaine de constantes de Pyxel pour que le
processus de Spyder n'ait pas a importer pyxel (et donc a charger libSDL2). Ce test est
le garde-fou de cette duplication : si une version de Pyxel renumerotait une touche, il
echouerait au lieu de laisser le dock envoyer des touches fantomes.
"""

import pyxel

from spyder_pyxel.spyder.widgets import keymap


def test_all_copied_constants_match_pyxel():
    copied = {
        name: value for name, value in vars(keymap).items()
        if name.startswith(("KEY_", "MOUSE_")) and isinstance(value, int)
    }
    assert copied, "aucune constante recopiee trouvee dans keymap.py"

    mismatches = {
        name: (value, getattr(pyxel, name))
        for name, value in copied.items()
        if getattr(pyxel, name, None) != value
    }
    assert not mismatches, f"constantes divergentes : {mismatches}"
