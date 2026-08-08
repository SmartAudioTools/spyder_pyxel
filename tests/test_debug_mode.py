# -*- coding: utf-8 -*-
"""
Le greffon en MODE DEBOGAGE (Ctrl+F5 dans Spyder, `%debugfile` dans le noyau).

Deux etages independants, parce que le defaut n'etait pas la ou on l'attendait.

1. LE NOYAU (`%debugfile`)
   Il marchait deja : le pont publie les images a pleine cadence sous le debogueur, et
   les points d'arret s'atteignent normalement. Ce test le FIGE, parce que le crochet
   passe par `builtins.__import__` et que le debogueur, lui, pose un `sys.settrace` sur
   tout le programme - deux mecanismes qui pourraient se marcher dessus.

2. LE CLAVIER (l'aiguillage du focus)
   C'est la qu'etait le defaut, et il est entierement du cote de l'interface. Le panneau
   prend le clavier des la PREMIERE image, donc des `pyxel.init()`. En mode debogage,
   l'invite `ipdb>` s'affiche dans la console juste apres - mais chaque `n`, `s` ou `c`
   tape par l'utilisateur est intercepte par PyxelScreenWidget.keyPressEvent et expedie
   au jeu, qui est justement arrete. Le debogueur parait fige alors que rien n'est
   casse : seul le clavier est mal aiguille.

   Le correctif : le pont suit `sig_pdb_state_changed` de la console, et le panneau rend
   le clavier a la console des que le debogueur s'arrete - puis le reprend seulement
   quand le jeu produit reellement des images (FRAMES_BEFORE_REGRAB), ce qui distingue un
   `c` d'un `n` sur un point d'arret atteint a chaque image.

Lancement :
    QT_QPA_PLATFORM=offscreen python tests/test_debug_mode.py
"""

import os
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spyder_kernel_harness import start_kernel  # noqa: E402
from spyder_pyxel.bridge import protocol, reader  # noqa: E402

# Le numero de ligne du corps d'`update` sert de point d'arret : il doit suivre le texte.
GAME = '''
import pyxel
pyxel.init(40, 30, title="dbg", fps=30)
state = {"x": 0}
def update():
    state["x"] = (state["x"] + 1) % 30
def draw():
    pyxel.cls(5)
    pyxel.rect(state["x"], 3, 3, 3, 9)
pyxel.run(update, draw)
'''
BREAKPOINT_LINE = 6  # la ligne "state[...] = ..." dans update()

FPS = 30


# =============================================================================
# 1. Le noyau : %debugfile publie bien les images
# =============================================================================

class KernelSession:
    """Un noyau spyder-kernels + les fils qui repondent a ses invites."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.prompts = 0
        self.errors = []
        # ⚠ Le fil qui vide iopub est le SEUL a pouvoir lire ce canal : toute
        # verification passant par un `print` doit donc chercher ici, et non appeler
        # `client.get_iopub_msg` de son cote - les deux se voleraient les messages.
        self.lines = []
        self._stop = threading.Event()

    def __enter__(self):
        self.manager, self.client = start_kernel()
        for target in (self._pump_stdin, self._pump_iopub):
            threading.Thread(target=target, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        try:
            self.client.stop_channels()
        except Exception:
            pass
        self.manager.shutdown_kernel(now=True)

    def _pump_stdin(self):
        """Repond aux invites `ipdb>`. Sans ce fil, le noyau attendrait pour toujours."""
        while not self._stop.is_set():
            try:
                self.client.get_stdin_msg(timeout=0.5)
            except Exception:
                continue
            self.prompts += 1
            reply = self.answers.pop(0) if self.answers else "c"
            self.client.input(reply)

    def _pump_iopub(self):
        while not self._stop.is_set():
            try:
                message = self.client.get_iopub_msg(timeout=0.5)
            except Exception:
                continue
            if message["msg_type"] == "error":
                self.errors.append("\n".join(message["content"]["traceback"]))
            elif message["msg_type"] == "stream":
                self.lines.extend(message["content"]["text"].splitlines())

    def wait_for_line(self, prefix, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for line in list(self.lines):
                if line.startswith(prefix):
                    return line.strip()
            time.sleep(0.05)
        raise AssertionError(f"le noyau n'a rien affiche commencant par {prefix!r}")

    def wait_for_hook(self, timeout=60):
        """Attend que le crochet soit reellement pose dans le noyau.

        `status()` est le diagnostic prevu pour cela (bridge/kernel.py) : "installed"
        dit que le crochet est en place, "error" porte la trace s'il a echoue.
        """
        self.client.execute(
            "import spyder_pyxel.bridge.kernel as _k; print('HOOK', _k.status())")
        ligne = self.wait_for_line("HOOK", timeout)
        assert "'installed': True" in ligne, f"crochet non pose : {ligne}"
        assert "'error': None" in ligne, f"crochet en erreur : {ligne}"

    def assert_is_spyder_kernel(self):
        """Un ipykernel nu n'a pas les magies de Spyder - et ne l'annonce pas.

        Ce controle a deja rattrape un test qui croyait interroger Spyder (cf.
        spyder_kernel_harness.py).
        """
        self.client.execute(
            "print('MAGICS', 'runfile' in "
            "get_ipython().magics_manager.magics['line'])")
        line = self.wait_for_line("MAGICS")
        assert line == "MAGICS True", (
            "ce n'est PAS un noyau spyder-kernels : la magie %runfile est absente")


def frame_counter(channel):
    """Compteur d'images de l'en-tete partage : avance meme si personne ne lit."""
    return struct.unpack_from("<I", channel._shm.buf, protocol.OFF_FRAME)[0]


def run_under(magic, answers=(), measure_seconds=3.0):
    """Lance le jeu avec %runfile ou %debugfile, et rend la cadence observee."""
    directory = Path(tempfile.mkdtemp(prefix="spyder_pyxel_debug_"))
    game = directory / "game.py"
    game.write_text(GAME, encoding="utf-8")

    channel = reader.PyxelChannel()
    name = channel.create()
    try:
        with KernelSession(answers) as session:
            session.assert_is_spyder_kernel()
            session.client.execute(reader.kernel_bootstrap_code(name), silent=True)
            # ⚠ NE PAS remplacer par un time.sleep fixe. Le crochet est pose par un
            # execute SILENCIEUX, dont rien ne signale la fin. Une attente de deux
            # secondes suffisait sur une machine au repos et echouait des que d'autres
            # instances travaillaient en parallele (charge 7) : le jeu demarrait avant le
            # crochet, aucune image n'etait publiee, et le test accusait le mode debogage
            # d'un defaut qui n'existait pas. On interroge donc l'etat reel.
            session.wait_for_hook()
            session.client.execute(
                f"%{magic} {str(game)!r} --wdir {str(directory)!r}")

            deadline = time.time() + 40
            while time.time() < deadline and channel.read_frame() is None:
                time.sleep(0.05)
            assert channel.read_frame(only_if_new=False) is not None, (
                f"aucune image publiee sous %{magic} : "
                + ("\n".join(session.errors) or "aucune erreur remontee"))

            before = frame_counter(channel)
            time.sleep(measure_seconds)
            observed = (frame_counter(channel) - before) / measure_seconds
            return observed, session.prompts
    finally:
        channel.release()


def test_debugfile_publishes_at_full_speed():
    """Le pont doit fonctionner sous le debogueur, et sans ralentir le jeu.

    Le `sys.settrace` du debogueur passe sur chaque ligne d'`update` et de `draw` : une
    chute de cadence serait le defaut le plus plausible, et le seul que la mesure puisse
    trancher.
    """
    normal, _ = run_under("runfile")
    debug, prompts = run_under("debugfile")
    print(f"OK  %runfile   : {normal:.1f} images/s")
    print(f"OK  %debugfile : {debug:.1f} images/s "
          f"({prompts} invite(s) du debogueur)")
    assert prompts >= 1, "le debogueur ne s'est jamais arrete : ce n'etait pas un debug"
    assert debug >= FPS * 0.9, (
        f"le jeu tombe a {debug:.1f} images/s sous le debogueur (attendu ~{FPS})")


def test_breakpoint_inside_update_is_hit():
    """Un point d'arret pose DANS la boucle de jeu s'atteint a chaque image.

    C'est l'interet meme du greffon (README : "des points d'arret utilisables PENDANT que
    le jeu tourne"). On repond `c` a chaque invite : le jeu doit continuer d'avancer.
    """
    answers = [f"b {BREAKPOINT_LINE}"] + ["c"] * 400
    observed, prompts = run_under("debugfile", answers=answers,
                                  measure_seconds=2.0)
    print(f"OK  point d'arret dans update() : {prompts} arrets, "
          f"{observed:.1f} images/s")
    assert prompts > 5, (
        f"le point d'arret n'a ete atteint que {prompts} fois : il n'a pas pris")
    assert observed > 0, "le jeu ne produit plus rien apres un point d'arret"


# =============================================================================
# 2. L'interface : a qui va le clavier
# =============================================================================

class FakeChannel:
    """Un canal reduit a ce dont le pont a besoin pour arbitrer le clavier."""

    def __init__(self, kind):
        self._kind = kind
        self.notify_fd = None
        self.events = []

    def kind(self):
        return self._kind

    def create(self):
        return "fake"

    def read_frame(self, only_if_new=True):
        return None

    def release(self):
        pass

    # Le panneau envoie de vraies entrees des qu'il gagne ou perd le focus : on les
    # enregistre, un test verifiant que le relachement general part bien.
    def send_key(self, code, pressed):
        self.events.append(("key", code, pressed))

    def send_mouse(self, x, y):
        self.events.append(("mouse", x, y))

    def send_wheel(self, dx, dy):
        self.events.append(("wheel", dx, dy))

    def send_text(self, text):
        self.events.append(("text", text))

    def send_release_all(self):
        self.events.append(("release_all",))


class FakeShellWidget:
    """Une console reduite a son signal de debogage et a son widget de saisie."""

    def __init__(self, control):
        from qtpy.QtCore import QObject, Signal

        class _Signals(QObject):
            sig_pdb_state_changed = Signal(bool)

        self._signals = _Signals()
        self.sig_pdb_state_changed = self._signals.sig_pdb_state_changed
        self.spyder_kernel_ready = False
        self._control = control

    def silent_execute(self, code):
        pass


def make_frame(number, width=8, height=8):
    return reader.Frame(width, height, bytes(width * height), [0] * 16, number)


def test_keyboard_goes_back_to_the_console_when_the_debugger_stops():
    """Le scenario complet, dans l'ordre ou il se produit sous Ctrl+F5."""
    from qtpy.QtWidgets import QApplication, QLineEdit, QWidget

    from spyder_pyxel.spyder import bridge_manager
    from spyder_pyxel.spyder.plugin import PyxelGame
    from test_widgets_build import build

    app = QApplication.instance() or QApplication([])

    # Un pont neuf : celui du module est un objet unique, partage par toute la session.
    bridge_manager._bridge = None
    bridge = bridge_manager.get_bridge()

    widget = build(PyxelGame)

    # Une vraie fenetre : sans elle, aucun widget ne peut detenir le focus clavier.
    window = QWidget()
    console = QLineEdit(window)
    widget.setParent(window)
    window.show()
    app.processEvents()

    shellwidget = FakeShellWidget(console)
    channel = FakeChannel(protocol.KIND_GAME)
    bridge._channels[shellwidget] = channel
    bridge._shellwidgets[channel] = shellwidget
    bridge._active[protocol.KIND_GAME] = channel

    def on_pdb_state(waiting, ch=channel):
        bridge._on_pdb_state(ch, waiting)

    shellwidget.sig_pdb_state_changed.connect(on_pdb_state)

    def frame(number):
        # sig_frame porte le CANAL depuis le 21/07/2026 : c'est lui qui identifie le
        # programme, plusieurs pouvant tourner en meme temps sous le meme marqueur.
        bridge.sig_frame.emit(protocol.KIND_GAME, make_frame(number), channel)
        app.processEvents()

    # -- Le jeu demarre : le panneau prend le clavier, comme avec F5.
    frame(1)
    assert widget.screen.hasFocus(), "le panneau n'a pas pris le clavier au demarrage"
    print("OK  demarrage : le clavier va au jeu")

    # -- Le debogueur s'arrete : le clavier doit RETOURNER a la console.
    channel.events.clear()
    shellwidget.sig_pdb_state_changed.emit(True)
    app.processEvents()
    assert console.hasFocus(), (
        "le clavier est reste au jeu pendant l'arret du debogueur : "
        "les commandes `n`/`s`/`c` partiraient dans le jeu")
    assert not widget.screen.hasFocus()
    print("OK  arret du debogueur : le clavier revient a la console")

    # ⚠ CONSEQUENCE DU DEPLACEMENT DE FOCUS, a ne pas confondre avec une correction.
    # Sans le correctif, une touche maintenue pendant un arret ne posait aucun probleme :
    # le panneau gardait le focus, donc le relachement physique lui parvenait
    # normalement. En rendant le clavier a la console, on cree le risque : le relachement
    # part desormais dans la console, et la touche resterait enfoncee COTE JEU pour
    # toujours - le personnage courrait indefiniment a la reprise.
    # Ce qui l'evite est deja la : deplacer le focus declenche focusOutEvent, qui emet un
    # relachement general. On le verifie ici, sans quoi le correctif introduirait un
    # defaut pire que celui qu'il repare.
    assert ("release_all",) in channel.events, (
        "aucun relachement general envoye au jeu quand le clavier quitte le panneau : "
        "une touche maintenue resterait enfoncee cote jeu")
    print("OK  les touches maintenues sont relachees en quittant le panneau")

    # -- Pas a pas : chaque `n` produit au plus une image, puis rearret. Le clavier ne
    #    doit PAS repartir dans le jeu, sinon la commande suivante y serait avalee.
    for step in range(6):
        shellwidget.sig_pdb_state_changed.emit(False)
        app.processEvents()
        frame(10 + step)
        shellwidget.sig_pdb_state_changed.emit(True)
        app.processEvents()
        assert console.hasFocus(), (
            f"le clavier est parti dans le jeu au pas {step + 1} du pas a pas")
    print("OK  pas a pas : le clavier reste a la console")

    # -- `c` : le jeu repart pour de bon, le clavier lui revient.
    shellwidget.sig_pdb_state_changed.emit(False)
    app.processEvents()
    for number in range(20, 20 + widget.FRAMES_BEFORE_REGRAB):
        frame(number)
    assert widget.screen.hasFocus(), (
        "apres `c`, le clavier n'est jamais revenu au jeu : injouable")
    print(f"OK  reprise : le clavier revient au jeu apres "
          f"{widget.FRAMES_BEFORE_REGRAB} images")

    # -- Clic dans l'editeur PENDANT l'arret : le jeu ne doit pas reprendre le clavier
    #    a la reprise (demande explicite de l'utilisateur, 21/07/2026). Sans ce controle,
    #    `c` arracherait le focus a l'editeur ou l'on venait de relire du code.
    editor = QLineEdit(window)
    editor.show()
    widget.screen.setFocus()
    app.processEvents()
    assert widget.screen.hasFocus()
    shellwidget.sig_pdb_state_changed.emit(True)
    app.processEvents()
    assert console.hasFocus(), "l'arret n'a pas rendu le clavier a la console"
    editor.setFocus()                      # l'utilisateur va relire son code
    app.processEvents()
    shellwidget.sig_pdb_state_changed.emit(False)
    app.processEvents()
    for number in range(60, 60 + widget.FRAMES_BEFORE_REGRAB + 3):
        frame(number)
    assert editor.hasFocus(), (
        "le jeu a repris le clavier alors que l'utilisateur avait clique dans l'editeur "
        "pendant l'arret du debogueur")
    print("OK  clic ailleurs pendant l'arret : le jeu ne reprend pas le clavier")

    # -- Mais s'il revient dans la console avant de reprendre, le jeu retrouve bien le
    #    clavier : le controle porte sur l'instant de la reprise, pas sur un souvenir.
    widget.screen.setFocus()
    app.processEvents()
    shellwidget.sig_pdb_state_changed.emit(True)
    app.processEvents()
    editor.setFocus()
    app.processEvents()
    console.setFocus()                     # retour dans la console pour taper `c`
    app.processEvents()
    shellwidget.sig_pdb_state_changed.emit(False)
    app.processEvents()
    for number in range(80, 80 + widget.FRAMES_BEFORE_REGRAB):
        frame(number)
    assert widget.screen.hasFocus(), (
        "retour dans la console avant `c` : le jeu aurait du retrouver le clavier")
    print("OK  retour dans la console avant `c` : le jeu retrouve le clavier")

    # -- Un focus pose par l'utilisateur lui-meme ne doit pas etre deplace.
    console.setFocus()
    app.processEvents()
    shellwidget.sig_pdb_state_changed.emit(True)
    shellwidget.sig_pdb_state_changed.emit(False)
    app.processEvents()
    # ⚠ Numeros CROISSANTS : un numero inferieur au precedent signifie "nouveau jeu"
    # (le compteur d'images repart de 1), et declencherait la prise de clavier du
    # demarrage - ce que ce bloc ne cherche justement pas a tester.
    for number in range(100, 100 + widget.FRAMES_BEFORE_REGRAB + 2):
        frame(number)
    assert console.hasFocus(), (
        "le panneau a vole un focus que l'utilisateur avait pose sur la console")
    print("OK  un focus pose par l'utilisateur n'est pas vole")

    bridge.detach_console(shellwidget)
    assert channel not in bridge._debug_waiting
    assert channel not in bridge._shellwidgets
    print("OK  detach_console nettoie l'etat du debogueur")

    window.close()
    widget.deleteLater()


def main():
    test_keyboard_goes_back_to_the_console_when_the_debugger_stops()
    print()
    test_debugfile_publishes_at_full_speed()
    print()
    test_breakpoint_inside_update_is_hit()
    print("\nLE GREFFON FONCTIONNE EN MODE DEBOGAGE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
