# -*- coding: utf-8 -*-
"""
Le test le plus proche du reel : un VRAI noyau spyder-kernels, pas une imitation.

Pourquoi ce test existe
-----------------------
Les autres tests utilisent un faux noyau (un simple processus Python qui execute
l'amorcage puis le script). Ils n'ont pas vu le bug qui a le plus coute : dans le vrai
Spyder, le crochet etait injecte AVANT que le noyau soit connecte, et `silent_execute`
avale silencieusement l'AttributeError levee quand `kernel_client` n'existe pas encore
(spyder/plugins/ipythonconsole/widgets/shell.py). Resultat : aucun crochet, un panneau
noir, et pas le moindre message.

Ici on demarre le meme noyau que Spyder (spyder_kernels.console), on lui envoie le code
d'amorcage par le meme chemin (execute silencieux via jupyter_client), puis on execute un
jeu Pyxel - et on verifie que les images arrivent et que le clavier redescend.

Ce que ce test NE couvre PAS : l'interface graphique de Spyder elle-meme (creation du
panneau, signaux du plugin IPythonConsole). Aucun serveur d'affichage n'est accessible
depuis l'environnement de developpement.

Lancement :
    python tests/test_real_kernel.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spyder_kernel_harness import (  # noqa: E402
    assert_is_spyder_kernel, start_kernel)
from spyder_pyxel.bridge import protocol, reader  # noqa: E402

GAME = '''
import pyxel
print("le jeu demarre dans le vrai noyau", flush=True)
pyxel.init(40, 30, title="reel", fps=30)
state = {"x": 0}
def update():
    if pyxel.btn(pyxel.KEY_RIGHT):
        state["x"] += 1
def draw():
    pyxel.cls(5)
    pyxel.rect(state["x"], 3, 3, 3, 9)
pyxel.run(update, draw)
'''

KEY_RIGHT = 1073741903


def main():
    directory = Path(tempfile.mkdtemp(prefix="spyder_pyxel_realkernel_"))
    (directory / "game.py").write_text(GAME, encoding="utf-8")

    channel = reader.PyxelChannel()
    name = channel.create()

    print("demarrage d'un vrai noyau spyder-kernels...")
    manager, client = start_kernel()
    print("OK  noyau pret")

    try:
        # ⚠ D'abord verifier que c'en est bien un : ce test a longtemps interroge un
        # ipykernel nu sans que rien ne le signale (cf. spyder_kernel_harness.py).
        assert_is_spyder_kernel(client)
        print("OK  c'est bien un noyau spyder-kernels (%runfile present)")

        # Exactement ce que fait le greffon : un execute SILENCIEUX du code d'amorcage.
        client.execute(reader.kernel_bootstrap_code(name), silent=True)
        time.sleep(2.0)

        # Le crochet doit s'etre pose. On interroge le diagnostic depuis le noyau lui-meme.
        client.execute(
            "import spyder_pyxel.bridge.kernel as _k; print('STATUS', _k.status())")
        deadline = time.time() + 20
        status_line = None
        while time.time() < deadline and status_line is None:
            try:
                message = client.get_iopub_msg(timeout=1)
            except Exception:
                continue
            if message["msg_type"] == "stream":
                for line in message["content"]["text"].splitlines():
                    if line.startswith("STATUS"):
                        status_line = line
        assert status_line, "le noyau n'a pas repondu au diagnostic"
        print(f"OK  {status_line}")
        assert "'installed': True" in status_line, status_line
        assert "'error': None" in status_line, status_line

        # Puis le jeu, comme un F5.
        client.execute(
            f"exec(compile(open({str(directory / 'game.py')!r}).read(), 'game.py', 'exec'))")

        frame = None
        deadline = time.time() + 40
        while time.time() < deadline:
            frame = channel.read_frame()
            if frame is not None:
                break
            time.sleep(0.05)
        assert frame is not None, "aucune image publiee par le vrai noyau"
        assert (frame.width, frame.height) == (40, 30), (frame.width, frame.height)
        print(f"OK  image publiee par le vrai noyau : {frame.width}x{frame.height}")
        assert channel.kind() == protocol.KIND_GAME
        print("OK  marqueur = KIND_GAME")

        row = frame.pixels[3 * frame.width:4 * frame.width]
        x_before = row.index(9)

        channel.send_key(KEY_RIGHT, True)
        time.sleep(0.8)
        channel.send_key(KEY_RIGHT, False)
        time.sleep(0.3)
        frame = channel.read_frame(only_if_new=False)
        x_after = frame.pixels[3 * frame.width:4 * frame.width].index(9)
        assert x_after > x_before, f"le carre n'a pas bouge ({x_before} -> {x_after})"
        print(f"OK  clavier dans un vrai noyau : x {x_before} -> {x_after}")

        time.sleep(0.4)
        settled = channel.read_frame(only_if_new=False)
        assert settled.pixels[3 * settled.width:4 * settled.width].index(9) == x_after
        print("OK  relachement pris en compte")
    finally:
        try:
            client.stop_channels()
        except Exception:
            pass
        manager.shutdown_kernel(now=True)
        channel.release()

    leftovers = [n for n in os.listdir("/dev/shm") if n.startswith("spyder_pyxel_")]
    assert not leftovers, f"segments non liberes : {leftovers}"
    print("OK  /dev/shm est propre")

    print("\nLE PONT FONCTIONNE DANS UN VRAI NOYAU SPYDER")
    return 0


if __name__ == "__main__":
    sys.exit(main())
