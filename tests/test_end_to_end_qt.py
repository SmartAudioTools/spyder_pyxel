# -*- coding: utf-8 -*-
"""
Test de bout en bout : faux noyau IPython -> memoire partagee -> pixels reellement peints.

Reproduit exactement ce que fait Spyder : on cree un canal, on execute le code d'amorcage
dans un processus separe (comme `silent_execute` le ferait dans un noyau), puis ce
processus lance un vrai jeu Pyxel. On verifie ensuite que le widget affiche bien les
pixels attendus et que le clavier redescend jusqu'au jeu.

Verifie aussi le point qui distingue les deux panneaux : le marqueur jeu/editeur, seul
moyen de savoir a qui destiner une image maintenant que tout part de la console.

Lancement :
    QT_QPA_PLATFORM=offscreen python tests/test_end_to_end_qt.py
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qtpy.QtCore import QEvent, Qt  # noqa: E402
from qtpy.QtGui import QImage, QKeyEvent  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

from spyder_pyxel.bridge import protocol, reader  # noqa: E402
from spyder_pyxel.spyder.widgets.screen import PyxelScreenWidget  # noqa: E402

# Ce que ferait un noyau IPython : executer l'amorcage, puis (bien plus tard) le script.
FAKE_KERNEL = '''
import sys, runpy
exec(compile(open(sys.argv[1]).read(), "<bootstrap>", "exec"), {})
print("[noyau] la sortie du jeu arrive bien dans la console", flush=True)
runpy.run_path(sys.argv[2], run_name="__main__")
'''

GAME = '''
import pyxel
print("le jeu demarre", flush=True)
pyxel.init(40, 30, title="test", fps=30)
state = {"x": 0}
def update():
    if pyxel.btn(pyxel.KEY_RIGHT):
        state["x"] += 1
def draw():
    pyxel.cls(5)
    pyxel.rect(state["x"], 3, 3, 3, 9)
pyxel.run(update, draw)
'''


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def main():
    app = QApplication.instance() or QApplication([])

    directory = Path(tempfile.mkdtemp(prefix="spyder_pyxel_test_"))
    (directory / "kernel.py").write_text(FAKE_KERNEL, encoding="utf-8")
    (directory / "game.py").write_text(GAME, encoding="utf-8")

    channel = reader.PyxelChannel()
    name = channel.create()
    (directory / "boot.py").write_text(
        reader.kernel_bootstrap_code(name), encoding="utf-8")

    widget = PyxelScreenWidget()
    widget.resize(400, 300)
    widget.show()
    widget.sig_key.connect(channel.send_key)

    process = subprocess.Popen(
        [sys.executable, str(directory / "kernel.py"),
         str(directory / "boot.py"), str(directory / "game.py")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    frames = []
    deadline = time.time() + 30
    while time.time() < deadline:
        frame = channel.read_frame()
        if frame is not None:
            frames.append(frame)
            widget.set_frame(frame)
            break
        if process.poll() is not None:
            break
        pump(app, 0.02)

    assert frames, "aucune image recue du faux noyau"
    frame = frames[-1]
    assert (frame.width, frame.height) == (40, 30), (frame.width, frame.height)
    print(f"OK  image recue du noyau : {frame.width}x{frame.height}")

    # Le marqueur : c'est lui qui aiguille vers l'un ou l'autre panneau.
    assert channel.kind() == protocol.KIND_GAME, channel.kind()
    print("OK  marqueur = KIND_GAME (un jeu, pas l'editeur de ressources)")

    # --- Le widget peint-il vraiment les bons pixels ? ----------------------
    canvas = QImage(widget.size(), QImage.Format_RGB32)
    widget.render(canvas)
    # Echelle = min(400//40, 300//30) = 10, l'image occupe tout le widget.
    # Le carre vit en y = 3..5 ; on echantillonne le fond loin de lui.
    background = canvas.pixelColor(205, 205).rgb() & 0xFFFFFF
    assert background == frame.palette[5], (hex(background), hex(frame.palette[5]))
    row = frame.pixels[3 * frame.width:4 * frame.width]
    square_x = row.index(9)
    foreground = canvas.pixelColor(square_x * 10 + 5, 3 * 10 + 5).rgb() & 0xFFFFFF
    assert foreground == frame.palette[9], (hex(foreground), hex(frame.palette[9]))
    print(f"OK  rendu : fond {hex(background)} = palette[5], "
          f"carre {hex(foreground)} = palette[9]")

    # --- Une touche envoyee par Qt arrive-t-elle au jeu ? -------------------
    x_before = square_x
    widget.setFocus()
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
    end = time.time() + 1.0
    while time.time() < end:
        frame = channel.read_frame()
        if frame is not None:
            frames.append(frame)
        pump(app, 0.02)
    widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, Qt.Key_Right, Qt.NoModifier))
    pump(app, 0.3)

    frame = channel.read_frame(only_if_new=False)
    x_after = frame.pixels[3 * frame.width:4 * frame.width].index(9)
    assert x_after > x_before, f"le carre n'a pas bouge ({x_before} -> {x_after})"
    print(f"OK  clavier via l'anneau partage : x {x_before} -> {x_after}")

    # Relacher doit arreter le mouvement.
    pump(app, 0.4)
    settled = channel.read_frame(only_if_new=False)
    x_final = settled.pixels[3 * settled.width:4 * settled.width].index(9)
    assert x_final == x_after, f"bouge encore apres relachement ({x_after} -> {x_final})"
    print("OK  relachement pris en compte")

    process.kill()
    process.wait(timeout=5)
    output = process.stdout.read()
    channel.release()

    leftovers = [n for n in os.listdir("/dev/shm") if n.startswith("spyder_pyxel_")]
    assert not leftovers, f"segments non liberes : {leftovers}"
    print("OK  /dev/shm est propre")

    # La sortie du jeu doit bien etre remontee au noyau (donc, dans Spyder, a la console).
    assert "le jeu demarre" in output, output[:500]
    print("OK  les print du jeu sont bien sortis cote noyau (= la console dans Spyder)")

    print("\nTOUS LES TESTS SONT PASSES")
    return 0


if __name__ == "__main__":
    sys.exit(main())
