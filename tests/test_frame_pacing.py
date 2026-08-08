# -*- coding: utf-8 -*-
"""
Mesure combien d'images publiees par le jeu arrivent reellement jusqu'au panneau.

Le probleme
-----------
Trois cadences independantes coexistent : le jeu publie a son propre rythme (60 images
par seconde en general), le panneau relit la memoire partagee sur une minuterie Qt, et
l'ecran se rafraichit a sa propre frequence. Quand la periode de relecture est proche de
celle du jeu sans lui etre inferieure de moitie, il arrive regulierement que DEUX images
soient publiees entre deux relectures : la premiere est perdue. Sur un defilement regulier
- le traveling d'un jeu de plateforme, typiquement - cela se voit comme une saccade.

Ce que ce test mesure
---------------------
Le compteur d'images de l'en-tete partage s'incremente a chaque publication. Il suffit
donc de verifier la CONTINUITE des numeros observes : un saut de N signifie N-1 images
perdues. On ne mesure pas un ressenti, on compte.

Le test echoue si le taux de perte depasse le seuil, ce qui protege contre une
regression du reglage de la cadence de relecture.

Lancement :
    python tests/test_frame_pacing.py
"""

import os
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spyder_pyxel.bridge import reader  # noqa: E402
from spyder_pyxel.spyder import bridge_manager  # noqa: E402

FAKE_KERNEL = '''
import sys
exec(compile(open(sys.argv[1]).read(), "<bootstrap>", "exec"), {})
import runpy
runpy.run_path(sys.argv[2], run_name="__main__")
'''

GAME = '''
import pyxel
pyxel.init(64, 48, title="pacing", fps={fps})
state = {{"n": 0}}
def update():
    state["n"] += 1
def draw():
    pyxel.cls(state["n"] % 16)
pyxel.run(update, draw)
'''

# Duree d'observation. Assez longue pour que le battement ait le temps de se manifester :
# a 60 images par seconde, un battement lent produit une perte toutes les quelques
# secondes seulement.
DUREE = 4.0

# Seuil d'echec. Zero perte est impossible a garantir (l'ordonnanceur du systeme peut
# toujours retarder une relecture), mais au-dela de 2 % le defilement se voit.
PERTE_MAX = 2.0

# Seuil de gigue : ecart type entre l'intervalle d'arrivee observe et l'intervalle
# theorique du jeu. Au-dela du quart d'une periode d'ecran (~4 ms a 60 Hz), une image sur
# quelques-unes bascule sur un rafraichissement voisin et le defilement saccade.
GIGUE_MAX = 4.0


def mesure(intervalle_ms, fps, signal=False):
    """Lance un vrai jeu et compte les images perdues a cette cadence de relecture."""
    directory = Path(tempfile.mkdtemp(prefix="spyder_pyxel_pacing_"))
    (directory / "kernel.py").write_text(FAKE_KERNEL, encoding="utf-8")
    (directory / "game.py").write_text(GAME.format(fps=fps), encoding="utf-8")

    channel = reader.PyxelChannel()
    name = channel.create()
    (directory / "boot.py").write_text(
        reader.kernel_bootstrap_code(name), encoding="utf-8")

    process = subprocess.Popen(
        [sys.executable, str(directory / "kernel.py"),
         str(directory / "boot.py"), str(directory / "game.py")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        # Attendre que le jeu tourne vraiment avant de compter.
        deadline = time.time() + 30
        while time.time() < deadline:
            if channel.read_frame() is not None:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("le jeu n'a pas demarre")

        premier = dernier = None
        vues = 0
        perdues = 0
        instants = []
        fin = time.time() + DUREE
        while time.time() < fin:
            frame = channel.read_frame()
            if frame is not None:
                maintenant = time.perf_counter()
                if premier is None:
                    premier = frame.number
                elif frame.number > dernier + 1:
                    perdues += frame.number - dernier - 1
                dernier = frame.number
                vues += 1
                instants.append(maintenant)
            if signal and channel.notify_fd is not None:
                # Exactement ce que fait QSocketNotifier : on dort jusqu'a ce que le jeu
                # ecrive dans le tube, sans jamais interroger a l'aveugle.
                select.select([channel.notify_fd], [], [], 0.5)
                channel.drain_notifications()
            else:
                time.sleep(intervalle_ms / 1000.0)

        publiees = (dernier - premier + 1) if premier is not None else 0
        taux = (100.0 * perdues / publiees) if publiees else 100.0

        # Regularite : c'est elle, et non la perte, qui produit les saccades. Le jeu
        # publie a intervalle constant ; si le panneau les voit arriver de facon
        # irreguliere, certaines images restent affichees deux rafraichissements d'ecran
        # et d'autres un seul - ce qui se voit sur un defilement continu.
        ecarts = [(b - a) * 1000.0 for a, b in zip(instants, instants[1:])]
        if ecarts:
            attendu = 1000.0 / fps
            ecart_type = (sum((e - attendu) ** 2 for e in ecarts) / len(ecarts)) ** 0.5
            pire = max(abs(e - attendu) for e in ecarts)
        else:
            ecart_type = pire = float("nan")
        return publiees, vues, perdues, taux, ecart_type, pire
    finally:
        process.kill()
        process.wait(timeout=5)
        channel.release()


def main():
    print(f"Duree d'observation : {DUREE} s par mesure\n")
    print(f"{'jeu':>12} {'mode':>22} {'publiees':>9} {'perdues':>8} "
          f"{'gigue type':>11} {'pire ecart':>11}")
    print("-" * 78)

    echecs = []
    for fps in (30, 60):
        # 15 ms : l'ancien reglage, garde comme temoin pour que le gain soit chiffre et
        # non affirme.
        for intervalle, etiquette, signal in (
                (15, "sondage 15 ms (origine)", False),
                (bridge_manager.POLL_INTERVAL_MS, "sondage 4 ms", False),
                (0, "signalement", True)):
            publiees, vues, perdues, taux, gigue, pire = mesure(intervalle, fps, signal)
            marque = ""
            if signal and (taux > PERTE_MAX or gigue > GIGUE_MAX):
                marque = "  <-- AU-DESSUS DU SEUIL"
                echecs.append((fps, intervalle, taux, gigue))
            print(f"{fps:>8} fps {etiquette:>22} {publiees:>9} {perdues:>8} "
                  f"{gigue:>10.2f}ms {pire:>10.2f}ms{marque}")

    print()
    if echecs:
        for fps, intervalle, taux, gigue in echecs:
            print(f"ECHEC : a {fps} fps, relecture toutes les {intervalle} ms -> "
                  f"{taux:.1f} % perdues (seuil {PERTE_MAX} %), "
                  f"gigue {gigue:.2f} ms (seuil {GIGUE_MAX} ms)")
        return 1

    print(f"OK  perte < {PERTE_MAX} % et gigue < {GIGUE_MAX} ms a toutes les cadences")
    leftovers = [n for n in os.listdir("/dev/shm") if n.startswith("spyder_pyxel_")]
    assert not leftovers, f"segments non liberes : {leftovers}"
    print("OK  /dev/shm est propre")
    return 0


if __name__ == "__main__":
    sys.exit(main())
