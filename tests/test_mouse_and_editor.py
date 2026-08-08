# -*- coding: utf-8 -*-
"""
La SOURIS a travers le pont, et l'editeur de ressources reellement pilote.

POURQUOI CE TEST EXISTE
Jusqu'au 21/07/2026, AUCUN test n'exercait la souris. Tout portait sur le clavier
(test_end_to_end_qt.py, test_real_kernel.py), et le panneau "Pyxel Studio" n'etait
verifie que sur un point : le marqueur KIND_EDITOR de son en-tete (test_editor_kind.py).
Autrement dit, on savait que l'image de l'editeur arrivait dans le bon panneau, et rien
d'autre. Rien ne disait qu'on pouvait s'en SERVIR.

On ne pouvait pas : la position de la souris etait perdue des l'image suivante.

LE DEFAUT, ET POURQUOI IL ETAIT INVISIBLE
Pyxel relit la position du curseur au systeme a chaque tour de boucle, meme en mode
offscreen ou aucun evenement SDL n'arrive. set_mouse_pos() n'etait donc respecte que pour
l'image ou le pont l'appelait ; des la suivante, la position retombait sur celle du
curseur physique. Mesure d'origine : position injectee (20, 30) vue UNE image, puis
(-4, 19) figee pour toujours.

L'etat des TOUCHES, lui, survit sans rien faire - c'est une table que SDL n'alimente pas
en offscreen. D'ou l'asymetrie, et d'ou le fait que le clavier ait toujours marche : rien
dans le code du pont ne laissait deviner que la souris se comporterait autrement.

Consequence : les widgets de Pyxel testent l'appartenance du curseur a leur rectangle au
moment du CLIC. Le clic arrivant toujours au moins une image apres le deplacement, il
etait teste contre la mauvaise position - donc jamais sur le widget vise. L'editeur de
ressources, qui se pilote presque entierement a la souris, etait inutilisable. Un jeu, au
contraire, ne s'en apercevait pas : la plupart lisent pyxel.mouse_x en continu, ou
n'utilisent pas la souris.

CORRECTIF : InputConsumer.pump() reaffirme la derniere position connue a chaque image.

Lancement :
    python tests/test_mouse_and_editor.py
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spyder_pyxel.bridge import protocol, reader  # noqa: E402

# Geometrie relevee dans pyxel/editor (2.9.8) :
#   CanvasPanel(parent, 11, 16, 130, 130) et _screen_to_focus fait (x - 11 - 1) // 8.
# Le pixel image (i, j), avec le cadrage au repos (0, 0), se clique donc en
# (12 + 8*i, 17 + 8*j). Si ces constantes changent chez Pyxel, ce test le dira en
# n'obtenant plus les pixels attendus - c'est voulu, il vaut mieux qu'il casse bruyamment.
CANVAS_X, CANVAS_Y = 11, 16

# Couleur posee par defaut par l'editeur : ColorPicker(..., min(7, num_user_colors - 1)).
COULEUR_CRAYON = 7

JEU_SONDE = '''
import sys
exec(compile(open(sys.argv[1]).read(), "<bootstrap>", "exec"), {})
import pyxel
pyxel.init(64, 64, fps=30)
pyxel.mouse(True)
def update():
    print(f"SOURIS {pyxel.mouse_x} {pyxel.mouse_y} "
          f"{int(pyxel.btn(pyxel.MOUSE_BUTTON_LEFT))}", flush=True)
def draw():
    pyxel.cls(0)
pyxel.run(update, draw)
'''

EDITEUR = '''
import sys
exec(compile(open(sys.argv[1]).read(), "<bootstrap>", "exec"), {})
import pyxel.editor
pyxel.editor.App(sys.argv[2], "image")
'''


def canvas_vers_ecran(i, j):
    return CANVAS_X + 1 + 8 * i, CANVAS_Y + 1 + 8 * j


class Session:
    """Un programme Pyxel lance a cote, pilote par le canal partage.

    On passe par un sous-processus plutot que par un vrai noyau IPython : ce test porte
    sur les ENTREES et sur l'editeur, pas sur l'integration a la console, deja couverte
    par test_real_kernel.py.
    """

    def __init__(self, source, *arguments, prefixe="spyder_pyxel_souris_"):
        self.directory = Path(tempfile.mkdtemp(prefix=prefixe))
        (self.directory / "prog.py").write_text(source, encoding="utf-8")
        self.channel = reader.PyxelChannel()
        nom = self.channel.create()
        (self.directory / "boot.py").write_text(
            reader.kernel_bootstrap_code(nom), encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, str(self.directory / "prog.py"),
             str(self.directory / "boot.py"), *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            cwd=str(self.directory))

    def attendre_demarrage(self, timeout=40):
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.channel.read_frame()
            if frame is not None:
                return frame
            if self.process.poll() is not None:
                raise AssertionError(
                    "le programme est mort avant d'afficher :\n"
                    + self.process.stdout.read()[:3000])
            time.sleep(0.02)
        # ⚠ Remonter la sortie du programme, meme s'il n'est pas mort. Sans cela, un
        # depassement de delai sous forte charge (plusieurs instances Claude en parallele)
        # ne disait rien de plus que "aucune image publiee" - impossible de distinguer une
        # vraie panne d'une machine surchargee. Rencontre en direct le 21/07/2026.
        sortie = ""
        if self.process.poll() is not None:
            sortie = self.process.stdout.read()[:2000]
        raise AssertionError(
            f"aucune image publiee en {timeout} s "
            f"(processus {'mort' if self.process.poll() is not None else 'toujours en vie'})"
            + (f"\n{sortie}" if sortie else ""))

    def images(self, combien=3):
        """Laisse passer `combien` images. Les entrees ne sont lues qu'a ce moment-la."""
        frame = self.channel.read_frame(only_if_new=False)
        base = frame.number if frame else 0
        deadline = time.time() + 10
        while time.time() < deadline:
            frame = self.channel.read_frame(only_if_new=False)
            if frame is not None and frame.number >= base + combien:
                return
            time.sleep(0.005)

    def tuer_le_programme(self):
        """Tue le processus SANS liberer le canal.

        C'est exactement ce que fait Pyxel a la fin d'un jeu : le processus disparait,
        mais le segment partage appartient au PANNEAU et lui survit. Separer les deux est
        indispensable pour observer ce que voit le panneau a ce moment-la.
        """
        self.process.kill()
        self.process.wait(timeout=5)

    def terminer(self):
        self.process.kill()
        sortie = self.process.stdout.read()
        self.process.wait(timeout=5)
        self.channel.release()
        return sortie


def verifier_shm_propre():
    restes = [n for n in os.listdir("/dev/shm") if n.startswith("spyder_pyxel_")]
    assert not restes, f"segments non liberes : {restes}"


# =============================================================================
# 1. La position de la souris tient dans le temps
# =============================================================================

def test_la_position_de_la_souris_survit_aux_images_suivantes():
    """Le garde-fou du defaut trouve le 21/07/2026.

    Sans la reaffirmation dans pump(), la position n'est correcte que sur UNE image.
    Le test echoue alors des la deuxieme observation.
    """
    import pyxel

    session = Session(JEU_SONDE)
    try:
        session.attendre_demarrage()
        session.channel.send_mouse(20, 30)
        session.images(8)
        session.channel.send_key(pyxel.MOUSE_BUTTON_LEFT, True)
        session.images(4)
        session.channel.send_key(pyxel.MOUSE_BUTTON_LEFT, False)
        session.images(4)
    finally:
        sortie = session.terminer()

    observations = []
    for ligne in sortie.splitlines():
        if ligne.startswith("SOURIS"):
            _, x, y, bouton = ligne.split()
            observations.append((int(x), int(y), bool(int(bouton))))

    assert len(observations) > 12, f"trop peu d'images observees : {len(observations)}"

    # On ignore les images d'avant l'arrivee de l'evenement : le premier tour affiche la
    # position du curseur physique, sur laquelle on ne peut rien affirmer.
    try:
        depart = next(i for i, o in enumerate(observations) if (o[0], o[1]) == (20, 30))
    except StopIteration:
        raise AssertionError(
            f"la position (20, 30) n'a jamais ete vue par le jeu : {observations[:6]}")

    apres = observations[depart:]
    mauvaises = [(x, y) for x, y, _ in apres if (x, y) != (20, 30)]
    assert not mauvaises, (
        f"la position a ete perdue apres {len(apres) - len(mauvaises)} image(s) : "
        f"{mauvaises[:5]} - Pyxel l'a relue du systeme et le pont ne la reaffirme pas")
    print(f"OK  position tenue sur {len(apres)} images consecutives")

    # Et l'appui, lui, doit bien monter puis retomber - sans quoi le test passerait
    # meme si aucune entree n'arrivait du tout.
    assert any(b for *_, b in apres), "le bouton n'a jamais ete vu enfonce"
    assert not apres[-1][2], "le bouton est reste enfonce apres relachement"
    print("OK  appui et relachement du bouton gauche vus par le jeu")
    verifier_shm_propre()


# =============================================================================
# 2. L'editeur de ressources, reellement pilote
# =============================================================================

def _lire_pyxres(chemin, points):
    """Relit un .pyxres dans un processus NEUF et rend les couleurs demandees.

    Un processus neuf, et non le notre : c'est la seule facon de prouver que la
    sauvegarde a bien atteint le disque, et non un etat en memoire.
    """
    script = Path(chemin).parent / "relecture.py"
    script.write_text(
        "import pyxel\n"
        "pyxel.init(16, 16)\n"
        f"pyxel.load({str(chemin)!r})\n"
        f"print('PIXELS', [pyxel.images[0].pget(i, j) for i, j in {points!r}])\n",
        encoding="utf-8")
    resultat = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=90,
        cwd=str(Path(chemin).parent),
        # Le crochet n'est pas installe dans ce processus : c'est a nous d'imposer le
        # rendu hors ecran, sinon SDL echoue faute de serveur d'affichage.
        env=dict(os.environ, SDL_VIDEODRIVER="offscreen",
                 SDL_VIDEO_GL_DRIVER="libEGL.so.1"))
    for ligne in resultat.stdout.splitlines():
        if ligne.startswith("PIXELS"):
            return eval(ligne[len("PIXELS"):].strip())
    raise AssertionError(
        f"relecture impossible :\n{resultat.stdout[-1500:]}\n{resultat.stderr[-1500:]}")


def test_editeur_dessine_glisse_et_enregistre():
    """Le parcours reel : cliquer, glisser, Ctrl+S, et relire le fichier ecrit.

    C'est ce que le TODO demandait d'eprouver et qui n'avait jamais ete essaye : "saisie
    dans ses champs, glisser de souris, sauvegarde du .pyxres".
    """
    import pyxel

    session = Session(EDITEUR, "ressources.pyxres", prefixe="spyder_pyxel_studio_")
    ressource = session.directory / "ressources.pyxres"
    try:
        frame = session.attendre_demarrage()
        assert (frame.width, frame.height) == (240, 180), (frame.width, frame.height)
        assert session.channel.kind() == protocol.KIND_EDITOR
        print(f"OK  editeur affiche : {frame.width}x{frame.height}, marqueur EDITOR")

        # -- un clic isole
        session.channel.send_mouse(*canvas_vers_ecran(1, 1))
        session.images(3)
        session.channel.send_key(pyxel.MOUSE_BUTTON_LEFT, True)
        session.images(3)
        session.channel.send_key(pyxel.MOUSE_BUTTON_LEFT, False)
        session.images(3)

        # -- un glisser horizontal sur la ligne 5, des colonnes 2 a 9
        ligne, debut, fin = 5, 2, 9
        session.channel.send_mouse(*canvas_vers_ecran(debut, ligne))
        session.images(3)
        session.channel.send_key(pyxel.MOUSE_BUTTON_LEFT, True)
        session.images(3)
        for i in range(debut + 1, fin + 1):
            session.channel.send_mouse(*canvas_vers_ecran(i, ligne))
            session.images(2)
        session.channel.send_key(pyxel.MOUSE_BUTTON_LEFT, False)
        session.images(4)

        # -- Ctrl+S : le clavier doit atteindre l'editeur, pas seulement les jeux
        session.channel.send_key(pyxel.KEY_CTRL, True)
        session.images(2)
        session.channel.send_key(pyxel.KEY_S, True)
        session.images(4)
        session.channel.send_key(pyxel.KEY_S, False)
        session.channel.send_key(pyxel.KEY_CTRL, False)
        session.images(6)

        assert ressource.exists(), (
            "Ctrl+S n'a rien ecrit : le clavier n'atteint pas l'editeur")
        print(f"OK  Ctrl+S a ecrit {ressource.name} ({ressource.stat().st_size} octets)")
    finally:
        session.terminer()

    # -- relecture dans un processus neuf
    points_ligne = [(i, ligne) for i in range(debut - 1, fin + 2)]
    couleurs = _lire_pyxres(ressource, [(1, 1)] + points_ligne)

    assert couleurs[0] == COULEUR_CRAYON, (
        f"le clic isole n'a rien dessine (couleur {couleurs[0]}) : la position de la "
        "souris n'etait pas celle visee au moment du clic")
    print(f"OK  clic isole : pixel (1,1) = couleur {couleurs[0]}")

    trace = couleurs[1:]
    assert trace[0] == 0 and trace[-1] == 0, (
        f"le trace deborde de la zone glissee : {trace}")
    assert all(c == COULEUR_CRAYON for c in trace[1:-1]), (
        f"le glisser n'a pas trace une ligne continue : {trace} "
        "(des trous signifient que des positions intermediaires ont ete perdues)")
    print(f"OK  glisser : ligne continue des colonnes {debut} a {fin}, "
          f"sans debordement")
    print("OK  tout cela relu depuis le .pyxres par un processus NEUF")
    verifier_shm_propre()


# =============================================================================
# 3. Un jeu qui s'arrete doit vider son panneau
# =============================================================================

def test_un_jeu_arrete_libere_son_panneau():
    """Sinon la derniere image reste figee pour toujours.

    ⚠ Rien ne previent de la fin : Pyxel COUPE LE PROCESSUS depuis son coeur Rust, donc
    ScreenPublisher.close() n'est jamais appele et STATE_STOPPED n'est jamais ecrit. Le
    seul indice est le PID inscrit dans l'en-tete. Signale par l'utilisateur le
    21/07/2026 : "la fenetre dans le plugin Pyxel_Game peut-elle redevenir noire quand on
    stoppe le jeu ?"
    """
    session = Session(JEU_SONDE)
    try:
        session.attendre_demarrage()
        assert session.channel.state() == protocol.STATE_RUNNING
        assert session.channel.publisher_alive(), (
            "le jeu tourne, il devrait etre vu vivant")
        print("OK  jeu en cours : publieur vu vivant")

        # Comme pyxel.quit() : le processus disparait, le segment partage - qui
        # appartient au panneau - lui survit.
        session.tuer_le_programme()

        assert session.channel.state() == protocol.STATE_RUNNING, (
            "l'etat partage dit toujours RUNNING - c'est precisement pour cela qu'il ne "
            "suffit pas a detecter la fin, et qu'il faut regarder le PID")
        assert not session.channel.publisher_alive(), (
            "le publieur est vu vivant alors que son processus est mort : la derniere "
            "image resterait figee dans le panneau pour toujours")
        print("OK  jeu arrete : publieur vu mort, le panneau peut se vider")
    finally:
        session.channel.release()
    verifier_shm_propre()


def main():
    test_la_position_de_la_souris_survit_aux_images_suivantes()
    print()
    test_editeur_dessine_glisse_et_enregistre()
    print()
    test_un_jeu_arrete_libere_son_panneau()
    print("\nLA SOURIS ET L'EDITEUR DE RESSOURCES FONCTIONNENT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
