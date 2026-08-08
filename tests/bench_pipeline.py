# -*- coding: utf-8 -*-
"""
Mesure le cout reel du transport des pixels, etape par etape.

Question posee : recopier l'ecran a chaque image, n'est-ce pas gourmand ?
Ce banc mesure separement les trois etages, pour chaque taille d'ecran interessante :

  publier   cote jeu    : lire le framebuffer de Pyxel + l'ecrire dans la memoire partagee
  lire      cote dock   : relire la memoire partagee sous seqlock
  peindre   cote dock   : construire la QImage indexee et la blitter agrandie

Le budget de reference est 16,7 ms : la duree d'une image a 60 par seconde.

Lancement :
    QT_QPA_PLATFORM=offscreen python tests/bench_pipeline.py
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qtpy.QtCore import QRect  # noqa: E402
from qtpy.QtGui import QImage, QPainter  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

from spyder_pyxel.bridge import reader  # noqa: E402

# Tailles representatives : la valeur par defaut des exemples Pyxel, une taille
# confortable, et le maximum que Pyxel accepte.
TAILLES = [(128, 128), (160, 120), (256, 256)]

# Taille du dock a l'ecran pour la mesure du dessin. C'est l'etage dont le cout depend
# de la taille d'AFFICHAGE et non de celle du jeu : on prend un panneau genereux.
DOCK = (960, 720)

REPETITIONS = 300


def chrono(fonction, repetitions=REPETITIONS):
    """Retourne la duree mediane d'un appel, en millisecondes.

    Mediane et non moyenne : une seule interruption du systeme pendant la mesure
    deplacerait la moyenne, alors que ce qu'on veut connaitre est le cout habituel.
    """
    durees = []
    for _ in range(repetitions):
        depart = time.perf_counter()
        fonction()
        durees.append((time.perf_counter() - depart) * 1000.0)
    durees.sort()
    return durees[len(durees) // 2]


class FauxPyxel:
    """Imite juste ce que le publieur lit sur le module pyxel.

    On ne fait pas tourner un vrai jeu ici : on veut mesurer le TRANSPORT, pas la vitesse
    a laquelle Pyxel dessine. Le framebuffer est un vrai tableau ctypes, comme celui que
    renvoie pyxel.screen.data_ptr().
    """

    def __init__(self, width, height):
        import ctypes

        self.width = width
        self.height = height
        self._buffer = (ctypes.c_uint8 * (width * height))()
        for i in range(width * height):
            self._buffer[i] = i % 16
        self.colors = [0x000000 + i * 0x0F0F0F for i in range(16)]
        self.screen = self

    def data_ptr(self):
        return self._buffer


def main():
    # QApplication requis : QImage/QPainter n'existent pas sans lui.
    QApplication.instance() or QApplication([])

    from spyder_pyxel.bridge.hooks import ScreenPublisher

    print("Budget d'une image a 60 par seconde : 16,700 ms")
    print(f"Dock simule : {DOCK[0]}x{DOCK[1]}")
    print()
    print(f"{'ecran':>10} {'publier':>9} {'lire':>9} {'peindre':>9} {'total':>9} "
          f"{'% budget':>9} {'debit':>10}")
    print("-" * 72)

    for width, height in TAILLES:
        session = reader.PyxelChannel()
        session.create()
        faux = FauxPyxel(width, height)

        from multiprocessing import shared_memory
        shm = shared_memory.SharedMemory(name=session.name)
        publieur = ScreenPublisher(shm.buf)

        # 1. Publication cote jeu.
        t_publier = chrono(lambda: publieur.publish(faux))

        # 2. Lecture cote dock. only_if_new=False : on veut mesurer une vraie lecture a
        #    chaque appel, pas le raccourci "rien de neuf".
        t_lire = chrono(lambda: session.read_frame(only_if_new=False))

        # 3. Dessin cote dock : QImage indexee + blit agrandi, exactement ce que fait
        #    PyxelScreenWidget.paintEvent.
        image_frame = session.read_frame(only_if_new=False)
        cible = QImage(DOCK[0], DOCK[1], QImage.Format_RGB32)
        echelle = min(DOCK[0] // width, DOCK[1] // height)
        rect = QRect(0, 0, width * echelle, height * echelle)

        def peindre():
            image = QImage(image_frame.pixels, width, height, width,
                           QImage.Format_Indexed8)
            image.setColorTable([0xFF000000 | c for c in image_frame.palette])
            painter = QPainter(cible)
            painter.drawImage(rect, image)
            painter.end()

        t_peindre = chrono(peindre)

        total = t_publier + t_lire + t_peindre
        octets = width * height
        debit_mo = octets * 60 / 1e6  # trois etages, mais un seul flux d'images
        print(f"{width:>4}x{height:<5} {t_publier:>8.3f}ms {t_lire:>8.3f}ms "
              f"{t_peindre:>8.3f}ms {total:>8.3f}ms {total / 16.7 * 100:>8.1f}% "
              f"{debit_mo:>7.1f} Mo/s")

        publieur.close()
        session.release()

    print()
    print("Rappel : 'publier' tourne dans le processus du JEU (il ampute son budget de")
    print("frame), 'lire' et 'peindre' tournent dans Spyder. Les deux ne se cumulent")
    print("donc pas dans le meme budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
