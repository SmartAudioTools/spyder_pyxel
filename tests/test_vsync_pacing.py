# -*- coding: utf-8 -*-
"""W574 : le jeu est cadence par les balayages du panneau (pyxel.step), pas par le sommeil.

Sans ecran ni vrai Pyxel : un faux module pyxel qui compte ses appels, et le vrai tube
nomme des balayages, rempli comme le ferait VsyncTicker. Lancer :
    python tests/test_vsync_pacing.py
"""
import os
import struct
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spyder_pyxel.bridge import hooks, protocol  # noqa: E402
from spyder_pyxel.bridge.reader import PyxelChannel  # noqa: E402


class FauxPyxel:
    """Juste ce que hooks.install touche ; `step` optionnel (Pyxel du fork ou d'origine)."""

    width = height = 8

    def __init__(self, avec_step):
        self.appels = []
        if avec_step:
            self.step = lambda: self.appels.append(("step", time.monotonic()))

    def init(self, *args, **kwargs):
        pass

    def flip(self):
        self.appels.append(("flip", time.monotonic()))

    def run(self, update, draw):
        raise AssertionError("le run natif ne doit pas etre appele")

    resize = load = quit = show = init


class TestVsyncPacing(unittest.TestCase):

    def setUp(self):
        self.canal = PyxelChannel()
        self.nom = self.canal.create("_w574")
        self.assertIsNotNone(self.canal.vsync_fd, "tube des balayages non cree")
        self.tick_fd = os.open(protocol.vsync_fifo_path(self.nom),
                               os.O_RDONLY | os.O_NONBLOCK)
        self.buf = self.canal._shm.buf

    def tearDown(self):
        os.close(self.tick_fd)
        self.canal.release()

    def _jouer(self, faux, images, hz=None, periode=None):
        """Fait tourner patched_run jusqu'a `images` images ; un fil envoie les balayages."""
        publisher = hooks.ScreenPublisher(self.buf, tick_fd=self.tick_fd)
        publisher.publish = lambda pyxel: None
        holder = {}
        hooks.install(faux, publisher, holder)
        faux.init(8, 8, fps=30)
        fin = threading.Event()

        def balayages():
            while not fin.is_set():
                self.canal.send_vsync_tick(hz)
                time.sleep(periode)

        if hz:
            threading.Thread(target=balayages, daemon=True).start()
        compte = {"n": 0}

        def update():
            compte["n"] += 1
            if compte["n"] > images:
                faux.quit()

        faux.run(update, lambda: None)
        fin.set()
        return holder

    def test_step_cadence_sur_deux_balayages_a_30_ips(self):
        faux = FauxPyxel(avec_step=True)
        # 60 Hz simules a 100 Hz reels pour un test court : 10 ms par balayage.
        holder = self._jouer(faux, images=20, hz=60.0, periode=0.010)
        noms = {nom for nom, _ in faux.appels}
        self.assertEqual(noms, {"step"}, "flip (sommeil) appele alors que step existe")
        ecarts = [b - a for (_, a), (_, b) in zip(faux.appels[1:], faux.appels[2:])]
        moyenne = sum(ecarts) / len(ecarts)
        # 2 balayages de 10 ms par image : 20 ms, pas 33 ms (horloge 30 i/s) ni 10 ms.
        self.assertAlmostEqual(moyenne, 0.020, delta=0.004, msg=f"ecarts {ecarts}")
        self.assertIn("pacer", holder)

    def test_sans_balayage_horloge_a_fps(self):
        faux = FauxPyxel(avec_step=True)
        self._jouer(faux, images=8)
        ecarts = [b - a for (_, a), (_, b) in zip(faux.appels[1:], faux.appels[2:])]
        moyenne = sum(ecarts) / len(ecarts)
        self.assertAlmostEqual(moyenne, 1 / 30, delta=0.006, msg=f"ecarts {ecarts}")

    def test_panneau_muet_garde_fps(self):
        # Frequence publiee mais plus aucun balayage (fenetre reduite) : 30 i/s, pas 20.
        self.canal.send_vsync_tick(60.0)
        os.read(self.tick_fd, 16)
        faux = FauxPyxel(avec_step=True)
        self._jouer(faux, images=12)
        ecarts = [b - a for (_, a), (_, b) in zip(faux.appels[2:], faux.appels[3:])]
        moyenne = sum(ecarts) / len(ecarts)
        self.assertAlmostEqual(moyenne, 1 / 30, delta=0.006, msg=f"ecarts {ecarts}")

    def test_arriere_purge_au_lancement(self):
        for _ in range(300):
            self.canal.send_vsync_tick(60.0)
        faux = FauxPyxel(avec_step=True)
        debut = time.monotonic()
        self._jouer(faux, images=6, hz=60.0, periode=0.010)
        self.assertGreater(time.monotonic() - debut, 0.08, "images parties sans attendre")

    def test_pyxel_d_origine_garde_flip(self):
        faux = FauxPyxel(avec_step=False)
        self._jouer(faux, images=5, hz=60.0, periode=0.010)
        self.assertEqual({nom for nom, _ in faux.appels}, {"flip"})

    def test_frequence_publiee_puis_coupee(self):
        self.canal.send_vsync_tick(59.951)
        mhz = struct.unpack_from("<I", self.buf, protocol.OFF_DISPLAY_MHZ)[0]
        self.assertEqual(mhz, 59951)
        self.canal.stop_vsync()
        self.assertEqual(struct.unpack_from("<I", self.buf, protocol.OFF_DISPLAY_MHZ)[0], 0)


class TestVsyncTicker(unittest.TestCase):
    """La fenetre du panneau livre des balayages tant que l'emetteur est actif, plus apres."""

    def test_balayages_puis_arret(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from qtpy.QtCore import QCoreApplication, QElapsedTimer
        from qtpy.QtGui import QWindow
        from qtpy.QtWidgets import QApplication

        from spyder_pyxel.spyder.vsync import VsyncTicker

        app = QApplication.instance() or QApplication([])
        fenetre = QWindow()
        fenetre.show()
        recus = []
        ticker = VsyncTicker(recus.append)
        ticker.start(fenetre)

        def tourner(ms):
            chrono = QElapsedTimer()
            chrono.start()
            while chrono.elapsed() < ms:
                QCoreApplication.processEvents()

        tourner(200)
        self.assertGreater(len(recus), 3, "aucun balayage livre")
        self.assertTrue(all(hz > 0 for hz in recus))
        ticker.stop()
        n = len(recus)
        tourner(100)
        self.assertLessEqual(len(recus), n + 1, "balayages apres stop()")
        fenetre.close()
        del app


if __name__ == "__main__":
    unittest.main(verbosity=2)
