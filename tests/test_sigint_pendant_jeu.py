# -*- coding: utf-8 -*-
"""Interrompre un jeu Pyxel DE L'EXTERIEUR (bouton Stop / interruption du noyau) pendant
qu'il tourne ne doit PAS planter le noyau entier.

Pourquoi ce test existe
------------------------
pyxel.init() installe SON PROPRE gestionnaire SIGINT natif (Rust,
pyxel::platform::facade::sigint_handler), par un appel direct a sigaction() en C - donc
invisible depuis Python (signal.getsignal() reste trompeusement inchange, cf. le journal
DONE pour la mesure qui l'a prouve, via le VRAI sigaction() du processus). Consequence
mesuree AVANT le correctif : un SIGINT envoye pendant que le jeu tourne dans la boucle
maison de patched_run() ne leve JAMAIS de KeyboardInterrupt Python - le noyau tout entier
meurt en ~0.2s, silencieusement (code de sortie 0, aucun traceback, meme le `except
BaseException` le plus large ne voit rien passer).

Le correctif restaure explicitement le gestionnaire SIGINT qui etait en place juste avant
l'appel natif, juste apres celui-ci (une seule fois, hooks.py: patched_init) - verifie que
pyxel ne reinstalle PAS le sien a chaque image.

Lancement :
    python tests/test_sigint_pendant_jeu.py
"""

import os
import signal
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spyder_kernel_harness import assert_is_spyder_kernel, start_kernel  # noqa: E402
from spyder_pyxel.bridge import reader  # noqa: E402

GAME = '''
import pyxel
pyxel.init(40, 30, title="sigint-test", fps=30)
def update():
    pass
def draw():
    pyxel.cls(5)
pyxel.run(update, draw)
'''


def main():
    directory = Path(tempfile.mkdtemp(prefix="spyder_pyxel_sigint_"))
    (directory / "game.py").write_text(GAME, encoding="utf-8")

    channel = reader.PyxelChannel()
    name = channel.create()

    print("demarrage d'un vrai noyau spyder-kernels...")
    manager, client = start_kernel()
    print("OK  noyau pret")

    try:
        assert_is_spyder_kernel(client)
        print("OK  c'est bien un noyau spyder-kernels")

        client.execute(reader.kernel_bootstrap_code(name), silent=True)
        time.sleep(2.0)

        # F5 sur le jeu : asynchrone, ne rend jamais la main au client tant que le jeu
        # tourne - exactement comme un vrai F5 dans Spyder.
        client.execute(
            f"exec(compile(open({str(directory / 'game.py')!r}).read(), 'game.py', 'exec'))")

        # Attendre qu'une image soit publiee : preuve que le processus est bien ENTRE
        # dans la boucle patched_run (donc, la plupart du temps, dans original_flip()).
        frame = None
        deadline = time.time() + 40
        while time.time() < deadline:
            frame = channel.read_frame()
            if frame is not None:
                break
            time.sleep(0.02)
        assert frame is not None, "aucune image publiee, le jeu n'a jamais demarre"
        print(f"OK  jeu en cours, {frame.width}x{frame.height} publie")

        # Laisser tourner quelques images, pour etre bien EN VOL dans la boucle native,
        # pas au tout premier tour.
        time.sleep(0.5)

        provisioner_process = manager.provisioner.process
        print("-- envoi SIGINT (Stop) au noyau --")
        manager.interrupt_kernel()  # exactement ce que fait le bouton Stop de Spyder

        # Le noyau doit rester VIVANT : sans le correctif, il meurt en ~0.2s.
        deadline = time.time() + 10
        while time.time() < deadline:
            if provisioner_process.poll() is not None:
                break
            time.sleep(0.1)
        assert provisioner_process.poll() is None, (
            "le noyau est mort apres le SIGINT (code retour="
            f"{provisioner_process.poll()}) - le crochet SIGINT natif de pyxel a repris "
            "la main, cf. hooks.py:patched_init")
        print("OK  le noyau est toujours vivant apres le SIGINT")

        # Et il doit avoir vu un KeyboardInterrupt Python normal, pas un silence total.
        got_keyboard_interrupt = False
        deadline = time.time() + 10
        while time.time() < deadline and not got_keyboard_interrupt:
            try:
                message = client.get_iopub_msg(timeout=1)
            except Exception:
                continue
            if message["msg_type"] == "error" and \
                    message["content"].get("ename") == "KeyboardInterrupt":
                got_keyboard_interrupt = True
        assert got_keyboard_interrupt, (
            "aucun KeyboardInterrupt recu sur iopub apres le SIGINT")
        print("OK  KeyboardInterrupt Python normal recu (pas une sortie native silencieuse)")

        # Et il doit repondre normalement a une commande APRES l'interruption.
        client.execute("print('NOYAU_REPONDANT_APRES_SIGINT')")
        deadline = time.time() + 10
        responded = False
        while time.time() < deadline and not responded:
            try:
                message = client.get_iopub_msg(timeout=1)
            except Exception:
                continue
            if message["msg_type"] == "stream" and \
                    "NOYAU_REPONDANT_APRES_SIGINT" in message["content"].get("text", ""):
                responded = True
        assert responded, "le noyau ne repond plus a une commande apres le SIGINT"
        print("OK  le noyau repond encore a une commande apres l'interruption")
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

    print("\nINTERROMPRE UN JEU PYXEL DE L'EXTERIEUR NE PLANTE PLUS LE NOYAU")
    return 0


if __name__ == "__main__":
    sys.exit(main())
