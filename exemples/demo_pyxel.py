# -*- coding: utf-8 -*-
"""
Petit jeu de demonstration pour verifier le dock Pyxel de Spyder.

Ouvrez ce fichier dans Spyder, puis cliquez sur "Executer le fichier courant dans le
dock" dans le panneau Pyxel. Cliquez dans l'ecran pour lui donner le focus, sinon les
touches partent a l'editeur.

  Fleches      deplacer le carre
  Espace       changer sa couleur
  Souris       le point clair suit le curseur
  Molette      changer la couleur du fond
"""

import pyxel

LARGEUR, HAUTEUR = 160, 120


class Demo:
    def __init__(self):
        pyxel.init(LARGEUR, HAUTEUR, title="Demo Spyder Pyxel", fps=60)
        self.x = LARGEUR // 2
        self.y = HAUTEUR // 2
        self.couleur = 10
        self.fond = 1
        self.frames = 0
        pyxel.run(self.update, self.draw)

    def update(self):
        self.frames += 1

        if pyxel.btn(pyxel.KEY_LEFT):
            self.x -= 2
        if pyxel.btn(pyxel.KEY_RIGHT):
            self.x += 2
        if pyxel.btn(pyxel.KEY_UP):
            self.y -= 2
        if pyxel.btn(pyxel.KEY_DOWN):
            self.y += 2

        self.x = max(0, min(LARGEUR - 8, self.x))
        self.y = max(0, min(HAUTEUR - 8, self.y))

        if pyxel.btnp(pyxel.KEY_SPACE):
            self.couleur = (self.couleur + 1) % 16

        if pyxel.mouse_wheel:
            self.fond = (self.fond + pyxel.mouse_wheel) % 16

    def draw(self):
        pyxel.cls(self.fond)

        pyxel.rect(self.x, self.y, 8, 8, self.couleur)
        pyxel.circ(pyxel.mouse_x, pyxel.mouse_y, 2, 7)

        pyxel.text(4, 4, "Fleches / Espace / Molette", 7)
        pyxel.text(4, 12, f"frame {self.frames}", 13)
        pyxel.text(4, HAUTEUR - 10, f"souris {pyxel.mouse_x},{pyxel.mouse_y}", 13)


Demo()
