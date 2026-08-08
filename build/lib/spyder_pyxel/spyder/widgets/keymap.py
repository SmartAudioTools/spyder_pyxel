# -*- coding: utf-8 -*-
"""
Traduction des touches Qt vers les codes de touches Pyxel.

Les codes de Pyxel sont les "keycodes" SDL2 : les caracteres imprimables valent leur
code ASCII *non modifie* (KEY_A vaut 97, pas 65), les autres touches valent un scancode
avec le bit 30 arme. Qt utilise sa propre numerotation. D'ou cette table.

Deux pieges verifies sur place avec Pyxel 2.9.8 :

1. Les touches "combinees" (KEY_SHIFT, KEY_CTRL, KEY_ALT, KEY_GUI) ne sont PAS deduites
   des variantes gauche/droite quand on injecte l'etat par set_btn() : Pyxel ne les
   recalcule que dans son traitement d'evenements SDL, court-circuite ici. Un jeu qui
   teste pyxel.btn(pyxel.KEY_SHIFT) ne verrait donc jamais rien si on n'envoyait que
   KEY_LSHIFT. Chaque modificateur est pour cette raison associe a DEUX codes, envoyes
   ensemble.

2. Qt ne distingue pas Maj gauche de Maj droite dans `event.key()`. On envoie la variante
   gauche, qui est celle que les jeux testent en pratique quand ils ne se contentent pas
   de la touche combinee.

Les caracteres imprimables ne sont volontairement pas tabules : on les derive de
`event.text()`, ce qui suit la disposition clavier reelle (AZERTY ici) au lieu de
supposer un QWERTY americain.
"""

from qtpy.QtCore import Qt

# Codes Pyxel (= keycodes SDL2). Recopies depuis pyxel 2.9.8 pour que le processus de
# Spyder n'ait pas besoin d'importer pyxel - donc pas de libSDL2 chargee dans Spyder.
# Ces valeurs font partie de l'ABI publique de SDL2 et ne bougent pas d'une version a
# l'autre ; `tests/test_keymap_matches_pyxel.py` le reverifie contre le pyxel installe.
KEY_BACKSPACE = 8
KEY_TAB = 9
KEY_RETURN = 13
KEY_ESCAPE = 27
KEY_SPACE = 32
KEY_DELETE = 127

KEY_CAPSLOCK = 1073741881
KEY_F1 = 1073741882
KEY_PRINTSCREEN = 1073741894
KEY_SCROLLLOCK = 1073741895
KEY_PAUSE = 1073741896
KEY_INSERT = 1073741897
KEY_HOME = 1073741898
KEY_PAGEUP = 1073741899
KEY_END = 1073741901
KEY_PAGEDOWN = 1073741902
KEY_RIGHT = 1073741903
KEY_LEFT = 1073741904
KEY_DOWN = 1073741905
KEY_UP = 1073741906
KEY_NUMLOCKCLEAR = 1073741907
KEY_KP_DIVIDE = 1073741908
KEY_KP_MULTIPLY = 1073741909
KEY_KP_MINUS = 1073741910
KEY_KP_PLUS = 1073741911
KEY_KP_ENTER = 1073741912
KEY_KP_1 = 1073741913
KEY_KP_0 = 1073741922
KEY_KP_PERIOD = 1073741923
KEY_MENU = 1073741942

KEY_LCTRL = 1073742048
KEY_LSHIFT = 1073742049
KEY_LALT = 1073742050
KEY_LGUI = 1073742051

KEY_SHIFT = 1342177281
KEY_CTRL = 1342177282
KEY_ALT = 1342177283
KEY_GUI = 1342177284

MOUSE_BUTTON_LEFT = 1342177540
MOUSE_BUTTON_MIDDLE = 1342177541
MOUSE_BUTTON_RIGHT = 1342177542
MOUSE_BUTTON_X1 = 1342177543
MOUSE_BUTTON_X2 = 1342177544


def _function_keys():
    """F1..F12 se suivent dans la numerotation SDL comme dans celle de Qt."""
    return {
        getattr(Qt, f"Key_F{index}"): (KEY_F1 + index - 1,)
        for index in range(1, 13)
    }


def _keypad_digits():
    """Pave numerique : SDL numerote 1..9 puis 0, Qt numerote 0..9."""
    mapping = {KEY_KP_0: 0}
    for digit in range(1, 10):
        mapping[KEY_KP_1 + digit - 1] = digit
    return mapping


_NAMED_KEYS = {
    Qt.Key_Backspace: (KEY_BACKSPACE,),
    Qt.Key_Tab: (KEY_TAB,),
    Qt.Key_Backtab: (KEY_TAB,),
    Qt.Key_Return: (KEY_RETURN,),
    Qt.Key_Enter: (KEY_KP_ENTER,),
    Qt.Key_Escape: (KEY_ESCAPE,),
    Qt.Key_Space: (KEY_SPACE,),
    Qt.Key_Delete: (KEY_DELETE,),
    Qt.Key_Insert: (KEY_INSERT,),
    Qt.Key_Home: (KEY_HOME,),
    Qt.Key_End: (KEY_END,),
    Qt.Key_PageUp: (KEY_PAGEUP,),
    Qt.Key_PageDown: (KEY_PAGEDOWN,),
    Qt.Key_Left: (KEY_LEFT,),
    Qt.Key_Right: (KEY_RIGHT,),
    Qt.Key_Up: (KEY_UP,),
    Qt.Key_Down: (KEY_DOWN,),
    Qt.Key_CapsLock: (KEY_CAPSLOCK,),
    Qt.Key_NumLock: (KEY_NUMLOCKCLEAR,),
    Qt.Key_ScrollLock: (KEY_SCROLLLOCK,),
    Qt.Key_Print: (KEY_PRINTSCREEN,),
    Qt.Key_Pause: (KEY_PAUSE,),
    Qt.Key_Menu: (KEY_MENU,),
    # Modificateurs : variante gauche + touche combinee (voir docstring, piege n.1).
    Qt.Key_Shift: (KEY_LSHIFT, KEY_SHIFT),
    Qt.Key_Control: (KEY_LCTRL, KEY_CTRL),
    Qt.Key_Alt: (KEY_LALT, KEY_ALT),
    Qt.Key_AltGr: (KEY_LALT, KEY_ALT),
    Qt.Key_Meta: (KEY_LGUI, KEY_GUI),
}
_NAMED_KEYS.update(_function_keys())

_MOUSE_BUTTONS = {
    Qt.LeftButton: MOUSE_BUTTON_LEFT,
    Qt.MiddleButton: MOUSE_BUTTON_MIDDLE,
    Qt.RightButton: MOUSE_BUTTON_RIGHT,
    Qt.XButton1: MOUSE_BUTTON_X1,
    Qt.XButton2: MOUSE_BUTTON_X2,
}


def pyxel_keys_for_event(event):
    """Codes Pyxel correspondant a un QKeyEvent. Tuple vide si la touche est ignoree.

    Retourne un tuple, car un modificateur en produit deux (cf. docstring du module).
    """
    key = event.key()

    named = _NAMED_KEYS.get(key)
    if named is not None:
        return named

    # Caracteres imprimables : on part du texte produit par la touche, ce qui respecte
    # la disposition du clavier. Les majuscules sont ramenees en minuscules parce que
    # SDL identifie une touche par son caractere non modifie.
    text = event.text()
    if len(text) == 1:
        code = ord(text.lower())
        if 32 <= code <= 126:
            return (code,)

    # Cas restant : combinaison avec Ctrl, ou touche morte. `event.text()` vaut alors ""
    # ou un caractere de controle, mais `event.key()` porte encore la lettre ou le
    # chiffre - que Qt numerote comme l'ASCII majuscule.
    if Qt.Key_A <= key <= Qt.Key_Z:
        return (key + 32,)
    if Qt.Key_0 <= key <= Qt.Key_9:
        return (key,)

    return ()


def pyxel_button_for_qt(button):
    """Code Pyxel d'un bouton de souris Qt, ou None."""
    return _MOUSE_BUTTONS.get(button)


def printable_text(event):
    """Texte a transmettre a pyxel.set_input_text(), ou "" si la touche n'en produit pas.

    L'editeur Pyxel s'en sert pour ses champs de saisie. On exclut les caracteres de
    controle (Entree, Echap, Ctrl+lettre...) que Pyxel traite comme des touches et non
    comme du texte.
    """
    text = event.text()
    if not text:
        return ""
    return "".join(character for character in text if character.isprintable())
