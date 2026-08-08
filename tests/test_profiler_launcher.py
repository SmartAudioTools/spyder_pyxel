# -*- coding: utf-8 -*-
"""
Le profileur (spyder_line_profiler_targets) redirige-t-il vraiment un jeu Pyxel vers le
panneau, au lieu de sa propre fenetre SDL ?

Contexte : lp_launcher.py (le lanceur qui remplace kernprof, cf.
Commun/spyder_plugins/spyder_line_profiler_targets/lp_launcher.py) tourne dans un QProcess
INDEPENDANT, hors de toute console/noyau IPython - le crochet habituel
(bridge_manager.attach_console, pose par silent_execute DANS un noyau) n'y est jamais
atteint. Signale par l'utilisateur le 31/07/2026, corrige par une redirection generique :
Spyder cree un canal AVANT de lancer le sous-processus (bridge_manager.attach_process) et
transmet son nom au lanceur (--pyxel-shm) ; c'est lp_launcher.py, DANS le sous-processus,
qui pose lui-meme le crochet (spyder_pyxel.bridge.kernel.install), le sous-module bridge/
etant concu pour tourner dans n'importe quel interprete ou pyxel est installe (--pyxel-
bridge-path fournit le dossier a ajouter a son sys.path, sans qu'il ait besoin d'y etre
installe par pip).

Ce test ne passe PAS par Spyder ni par widgets.py (aucun serveur d'affichage ici) : il
reproduit exactement ce que fait le patch de widgets.py, a la main - creer le canal cote
"Spyder", lancer lp_launcher.py en sous-processus avec les memes options - et verifie que
l'image du jeu arrive bien dans le canal, exactement comme test_real_kernel.py le fait pour
la voie console.

Lancement :
    python tests/test_profiler_launcher.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spyder_pyxel.bridge import protocol, reader  # noqa: E402

DEPOT = Path(__file__).resolve().parents[4]  # .../SmartOS
LP_LAUNCHER = (DEPOT / "Commun" / "spyder_plugins" / "spyder_line_profiler_targets"
               / "lp_launcher.py")
BRIDGE_PATH = str(Path(__file__).resolve().parents[1])  # .../spyder_pyxel (import racine)

GAME = '''
import pyxel
pyxel.init(40, 30, title="profileur", fps=30)
def update():
    pass
def draw():
    pyxel.cls(5)
    pyxel.rect(3, 3, 3, 3, 9)
pyxel.run(update, draw)
'''


def main():
    assert LP_LAUNCHER.is_file(), f"lp_launcher.py introuvable a {LP_LAUNCHER}"

    directory = Path(tempfile.mkdtemp(prefix="spyder_pyxel_profiler_"))
    game = directory / "game.py"
    game.write_text(GAME, encoding="utf-8")
    config = directory / "config.json"
    config.write_text(json.dumps({"targets": {}, "all_user": False}), encoding="utf-8")
    lprof_out = directory / "out.lprof"

    channel = reader.PyxelChannel()
    name = channel.create()
    print(f"OK  canal cree cote 'Spyder' : {name}")

    argv = [sys.executable, "-X", "utf8", str(LP_LAUNCHER),
            "--lprof", str(lprof_out), "--config", str(config),
            "--pyxel-shm", name, "--pyxel-bridge-path", BRIDGE_PATH,
            str(game)]
    print("demarrage du sous-processus lp_launcher.py, exactement comme widgets.py...")
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True)

    try:
        frame = None
        deadline = time.time() + 30
        while time.time() < deadline:
            if process.poll() is not None:
                break
            frame = channel.read_frame()
            if frame is not None:
                break
            time.sleep(0.05)

        if frame is None and process.poll() is not None:
            sortie = process.stdout.read() if process.stdout else ""
            raise AssertionError(
                f"le sous-processus s'est termine (code {process.returncode}) sans publier "
                f"d'image - le crochet n'a probablement pas ete pose :\n{sortie}")

        assert frame is not None, "aucune image publiee par le sous-processus du profileur"
        assert (frame.width, frame.height) == (40, 30), (frame.width, frame.height)
        print(f"OK  image publiee par le sous-processus du profileur : "
              f"{frame.width}x{frame.height}")
        assert channel.kind() == protocol.KIND_GAME
        print("OK  marqueur = KIND_GAME")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        channel.release()

    leftovers = [n for n in os.listdir("/dev/shm") if n.startswith("spyder_pyxel_")]
    assert not leftovers, f"segments non liberes : {leftovers}"
    print("OK  /dev/shm est propre")

    print("\nLA REDIRECTION PYXEL DU PROFILEUR FONCTIONNE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
