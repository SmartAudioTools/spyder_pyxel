# -*- coding: utf-8 -*-
"""
pyxel.quit() ne doit plus tuer tout le processus qui l'appelle.

Contexte (signale par l'utilisateur le 01/08/2026, en creusant "pourquoi Stop sur un jeu
Pyxel profile n'ecrit jamais de statistiques") : pyxel.run() (Rust/PyO3) ne rend JAMAIS la
main a Python, quelle que soit la facon dont le jeu se termine - ni sur une exception
ORDINAIRE issue de update()/draw() (le traceback qui semble s'afficher normalement est en
realite imprime par pyxel LUI-MEME, juste avant une sortie native du processus), ni sur
pyxel.quit(), ni sur la touche de sortie. Prouve par des marqueurs uniques dans les blocs
except/finally du code appelant, jamais atteints meme sur une exception SANS RAPPORT avec un
signal quelconque.

Consequence GRAVE, au-dela du seul profileur : un jeu Pyxel lance par F5 dans une console
Spyder et qui appelle pyxel.quit() lui-meme (plutot que de compter sur un arret EXTERNE -
Stop, fermeture de fenetre) tuerait le NOYAU IPYTHON ENTIER de la console. Jamais remarque
jusqu'ici parce que la plupart des jeux de demonstration ne definissent pas de touche de
sortie explicite.

CORRECTIF (hooks.py) : patched_quit() ne fait plus appel a la vraie sortie native - elle
leve une sentinelle interne (_ArretJeuVolontaire), attrapee par la boucle ECRITE A LA MAIN
de patched_run() (update() / draw() / pyxel.flip() natif, exactement le motif documente par
pyxel pour ecrire sa propre boucle - deja utilise ailleurs dans ce fichier par
patched_show()). La cadence et la gestion des entrees restent au natif (pyxel.flip() natif,
PAS le patch, pour eviter de publier/pomper deux fois par image) ; seule la SORTIE change de
comportement.

Ce test verifie le cas le plus critique - PAS le profileur (deja couvert par
test_profiler_launcher.py) : un jeu qui appelle pyxel.quit() DANS UN VRAI NOYAU
spyder-kernels ne doit PLUS tuer ce noyau. On le prouve en envoyant une DEUXIEME commande
apres le jeu et en verifiant qu'elle recoit bien une reponse.

Lancement :
    python tests/test_quit_rend_la_main.py
"""

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
compteur = {"n": 0}
pyxel.init(40, 30, title="quittest", fps=30)
def update():
    compteur["n"] += 1
    if compteur["n"] == 5:
        pyxel.quit()
def draw():
    pyxel.cls(5)
pyxel.run(update, draw)
print("APRES pyxel.run() : le script continue", flush=True)
'''


def _attendre_texte(client, attendu, deadline):
    """Lit le flux iopub jusqu'a voir `attendu` dans un message 'stream', ou expire."""
    while time.time() < deadline:
        try:
            message = client.get_iopub_msg(timeout=1)
        except Exception:
            continue
        if message["msg_type"] == "stream":
            if attendu in message["content"]["text"]:
                return True
    return False


def main():
    directory = Path(tempfile.mkdtemp(prefix="spyder_pyxel_quittest_"))
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

        client.execute(
            f"exec(compile(open({str(directory / 'game.py')!r}).read(), 'game.py', 'exec'))")

        deadline = time.time() + 30
        assert _attendre_texte(client, "APRES pyxel.run()", deadline), (
            "le jeu n'a jamais rendu la main - pyxel.quit() a probablement tue le noyau")
        print("OK  pyxel.run() a rendu la main apres pyxel.quit() : le script a continue")

        # Preuve definitive que le NOYAU LUI-MEME a survecu, pas seulement le fil
        # d'execution du script : une deuxieme commande, independante, doit repondre.
        client.execute("print('NOYAU_TOUJOURS_VIVANT')")
        deadline = time.time() + 15
        assert _attendre_texte(client, "NOYAU_TOUJOURS_VIVANT", deadline), (
            "le noyau ne repond plus a une commande APRES le jeu - il a ete tue")
        print("OK  le noyau repond encore a une commande APRES le jeu : il n'a pas ete tue")
    finally:
        try:
            client.stop_channels()
        except Exception:
            pass
        manager.shutdown_kernel(now=True)
        channel.release()

    print("\nPYXEL.QUIT() NE TUE PLUS LE NOYAU")
    return 0


if __name__ == "__main__":
    sys.exit(main())
