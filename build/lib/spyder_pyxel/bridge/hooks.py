# -*- coding: utf-8 -*-
"""
Cote jeu : publication de l'ecran et application des entrees.

Ce module est le seul endroit qui sache modifier le comportement de Pyxel. Il s'execute
toujours dans le NOYAU IPYTHON (cf. kernel.py) : tout part de la console, jeux comme
editeur de ressources, et les panneaux ne sont que des afficheurs.

Il ne depend ni de Qt ni de Spyder : il tourne du cote du jeu, et doit rester importable
dans n'importe quel interpreteur ou pyxel est installe.
"""

import os
import signal
import struct
import sys

from spyder_pyxel.bridge import protocol


class _ArretJeuVolontaire(Exception):
    """Sentinelle interne, jamais destinee a sortir de patched_run() (cf. hooks.install).

    Levee par patched_quit() a la place de la vraie sortie native de pyxel.run() ; attrapee
    par la boucle maison de patched_run(), qui rend alors la main normalement au lieu de
    terminer tout le processus.
    """


class ScreenPublisher:
    """Ecrit l'ecran de Pyxel dans la memoire partagee, une image a la fois."""

    def __init__(self, buffer, notify_fd=None):
        self._buf = buffer
        # Descripteur du tube nomme, ouvert en ecriture NON BLOQUANTE. Non bloquante est
        # essentiel : si le panneau est masque ou en retard, le tube se remplit, et un
        # jeu qui bloquerait sur cette ecriture perdrait des images pour une raison
        # purement decorative. On ignore alors l'erreur - le panneau a de toute facon
        # deja un signal en attente, un de plus ne lui apprendrait rien.
        self._notify_fd = notify_fd
        self._seq = 0
        self._frame = 0
        struct.pack_into("<I", self._buf, protocol.OFF_MAGIC, protocol.MAGIC)
        struct.pack_into("<I", self._buf, protocol.OFF_PUBLISHER_PID, os.getpid())
        self.set_kind(protocol.KIND_GAME)
        self._set_state(protocol.STATE_IDLE)

    def set_kind(self, kind):
        """Dit auquel des deux panneaux ces images sont destinees.

        Determine au moment de pyxel.init(), pas a la construction : on ne sait qu'a ce
        moment-la si c'est un jeu ou l'editeur de ressources qui demarre.
        """
        if self._buf is not None:
            struct.pack_into("<I", self._buf, protocol.OFF_KIND, kind)

    def _set_state(self, state):
        if self._buf is not None:
            struct.pack_into("<I", self._buf, protocol.OFF_STATE, state)

    def publish(self, pyxel):
        if self._buf is None:  # deja ferme : plus rien a publier
            return
        width, height = pyxel.width, pyxel.height
        if not (0 < width <= protocol.MAX_SCREEN_SIZE
                and 0 < height <= protocol.MAX_SCREEN_SIZE):
            return

        try:
            # `data_ptr()` est rappele a chaque image, sans cache. Il reconstruit un
            # tableau ctypes a partir de l'adresse du tampon de Pyxel, ce qui coute
            # quelques microsecondes - negligeable (mesure : 4 us, cf. README). Garder ce
            # tableau d'une image sur l'autre economiserait ces microsecondes mais ferait
            # pointer sur de la memoire liberee si Pyxel reallouait son ecran : on lirait
            # alors, silencieusement, n'importe quoi.
            source = pyxel.screen.data_ptr()
        except Exception:
            # pyxel.screen n'existe pas encore (init() pas termine) : rien a publier.
            return

        colors = pyxel.colors
        ncolors = min(len(colors), protocol.MAX_COLORS)
        palette = bytearray(ncolors * 4)
        for index in range(ncolors):
            struct.pack_into("<I", palette, index * 4, colors[index] & 0xFFFFFF)

        # Fenetre d'ecriture du seqlock : SEQ impair = donnees en cours de modification.
        self._seq += 1
        struct.pack_into("<I", self._buf, protocol.OFF_SEQ, self._seq)

        struct.pack_into("<I", self._buf, protocol.OFF_WIDTH, width)
        struct.pack_into("<I", self._buf, protocol.OFF_HEIGHT, height)
        struct.pack_into("<I", self._buf, protocol.OFF_NCOLORS, ncolors)
        self._buf[protocol.OFF_PALETTE:protocol.OFF_PALETTE + len(palette)] = palette

        nbytes = width * height
        self._buf[protocol.OFF_FRAMEBUFFER:protocol.OFF_FRAMEBUFFER + nbytes] = \
            bytes(memoryview(source)[:nbytes])

        self._frame += 1
        struct.pack_into("<I", self._buf, protocol.OFF_FRAME, self._frame)

        self._seq += 1
        struct.pack_into("<I", self._buf, protocol.OFF_SEQ, self._seq)
        self._set_state(protocol.STATE_RUNNING)

        # Signalement APRES la fermeture du seqlock : le panneau reveille par cet octet
        # doit trouver une image complete, jamais une ecriture en cours.
        if self._notify_fd is not None:
            try:
                os.write(self._notify_fd, b"\x01")
            except OSError:
                pass

    def close(self, state=protocol.STATE_STOPPED):
        if self._buf is None:
            return
        try:
            self._set_state(state)
        except Exception:
            pass
        self._buf = None


class InputConsumer:
    """Lit l'anneau d'entrees rempli par le panneau et l'applique a Pyxel.

    Pyxel maintient l'etat des touches dans une table alimentee par les evenements SDL. En
    mode offscreen aucun evenement n'arrive : l'etat qu'on injecte via set_btn() reste donc
    en place jusqu'a ce qu'on le change nous-memes, ce qui est exactement ce qu'il faut
    pour reproduire un appui maintenu.

    Deux entrees font exception et doivent etre remises a zero a chaque image, parce que
    SDL les livre normalement comme des evenements ponctuels et non comme un etat : la
    molette et le texte saisi. Sans cela, un cran de molette serait vu comme un defilement
    continu.

    ⚠ ET LA POSITION DE LA SOURIS FAIT EXCEPTION EN SENS INVERSE : elle doit etre
    REAFFIRMEE a chaque image. Contrairement a l'etat des touches, Pyxel la relit du
    systeme a chaque tour de boucle, meme en mode offscreen ou aucun evenement n'arrive :
    set_mouse_pos() n'est donc respecte que pour l'image ou on l'appelle, et des l'image
    suivante la position retombe sur celle du curseur physique. Mesure en direct
    (tests/test_mouse_input.py) : position injectee (20, 30) vue une seule image, puis
    (-4, 19) fige pour toujours - une valeur qui n'a aucun rapport avec le panneau.

    Consequence, et c'est ce qui rendait l'editeur de ressources inutilisable : les
    widgets de Pyxel testent l'appartenance du curseur a leur rectangle (is_hit) au moment
    du CLIC. Le clic arrivant toujours au moins une image apres le deplacement, il etait
    systematiquement teste contre la mauvaise position - donc jamais sur le widget vise.
    Le jeu, lui, ne s'en apercevait pas : la plupart lisent pyxel.mouse_x en continu, ou
    n'utilisent pas la souris du tout.
    """

    def __init__(self, buffer, pyxel):
        self._buf = buffer
        self._pyxel = pyxel
        # On demarre au niveau actuel du compteur d'ecriture : les evenements produits
        # avant le lancement du jeu (le clic qui a donne le focus au panneau, par exemple)
        # ne le concernent pas.
        self._read_index = self._write_index()
        # Suivi des touches enfoncees, pour toutes les relacher d'un coup quand le panneau
        # perd le focus. Sans ce suivi il faudrait relacher les ~250 touches de Pyxel.
        self._pressed = set()
        self._wheel_was_set = False
        self._text_was_set = False
        # Derniere position recue du panneau, reaffirmee a chaque image (cf. la docstring).
        # Reste None tant que le panneau n'a rien envoye : sans cela on epinglerait le
        # curseur en (0, 0) avant meme que l'utilisateur ait survole le panneau.
        self._mouse_pos = None

    def _write_index(self):
        return struct.unpack_from("<I", self._buf, protocol.OFF_INPUT_WRITE)[0]

    def _apply(self, kind, a, b):
        pyxel = self._pyxel
        if kind == protocol.EVENT_KEY:
            pressed = bool(b)
            pyxel.set_btn(a, pressed)
            if pressed:
                self._pressed.add(a)
            else:
                self._pressed.discard(a)
        elif kind == protocol.EVENT_MOUSE:
            self._mouse_pos = (float(a), float(b))
            pyxel.set_mouse_pos(*self._mouse_pos)
        elif kind == protocol.EVENT_WHEEL:
            pyxel.set_btnv(pyxel.MOUSE_WHEEL_X, a)
            pyxel.set_btnv(pyxel.MOUSE_WHEEL_Y, b)
            self._wheel_was_set = True
        elif kind == protocol.EVENT_TEXT:
            pyxel.set_input_text(chr(a))
            self._text_was_set = True
        elif kind == protocol.EVENT_RELEASE_ALL:
            for code in self._pressed:
                pyxel.set_btn(code, False)
            self._pressed.clear()

    def pump(self):
        """A appeler une fois par image, juste avant l'update du jeu."""
        pyxel = self._pyxel

        # Reaffirmation de la position de la souris. A FAIRE AVANT de vider l'anneau :
        # si celui-ci contient un nouveau deplacement, il doit ecraser cette valeur, pas
        # l'inverse. Pyxel l'ayant relue du systeme entre-temps, ne rien faire ici la
        # laisserait sur la position du curseur physique (cf. la docstring de la classe).
        if self._mouse_pos is not None:
            pyxel.set_mouse_pos(*self._mouse_pos)

        # Retombee des entrees "evenementielles" injectees a l'image precedente.
        if self._wheel_was_set:
            pyxel.set_btnv(pyxel.MOUSE_WHEEL_X, 0)
            pyxel.set_btnv(pyxel.MOUSE_WHEEL_Y, 0)
            self._wheel_was_set = False
        if self._text_was_set:
            pyxel.set_input_text("")
            self._text_was_set = False

        write_index = self._write_index()
        if write_index == self._read_index:
            return

        # Debordement : le panneau a produit plus d'evenements que l'anneau n'en tient
        # depuis la derniere image. On repart du plus ancien encore present plutot que de
        # rejouer des emplacements deja ecrases.
        if write_index - self._read_index > protocol.INPUT_SLOTS:
            self._read_index = write_index - protocol.INPUT_SLOTS

        while self._read_index < write_index:
            offset = (protocol.OFF_INPUT_RING
                      + (self._read_index % protocol.INPUT_SLOTS)
                      * protocol.INPUT_SLOT_SIZE)
            kind, a, b, _reserved = struct.unpack_from("<Iiii", self._buf, offset)
            self._read_index += 1
            try:
                self._apply(kind, a, b)
            except Exception:
                # Un evenement aberrant ne doit pas interrompre la partie.
                pass


def install(pyxel, publisher, consumer_holder):
    """Greffe les crochets sur les fonctions de Pyxel qui delimitent une image.

    Pyxel offre trois facons de faire tourner une boucle de jeu, et une application reelle
    en utilise une seule, mais on ne sait pas laquelle a l'avance :
      - `pyxel.run(update, draw)` : la boucle geree par Pyxel (cas courant) ;
      - `pyxel.flip()`            : boucle ecrite a la main ;
      - `pyxel.show()`            : affiche l'ecran et attend la touche de sortie.
    Les trois sont donc instrumentees.

    `consumer_holder` est un dictionnaire, et non un objet : le consommateur d'entrees ne
    peut etre construit qu'apres pyxel.init() (il lui faut le module initialise), alors que
    les crochets sont poses avant. Le dictionnaire sert de case partagee entre les deux
    moments.
    """
    original_run = pyxel.run
    original_flip = pyxel.flip
    original_init = pyxel.init
    original_resize = pyxel.resize
    original_load = pyxel.load
    original_quit = pyxel.quit
    # Memorise le repertoire courant vu avant pyxel.init() (cf. _resolve).
    state = {"cwd_at_init": None}
    original_save = getattr(pyxel, "save", None)

    def _resolve(filename):
        """Rend absolu un chemin de ressource relatif, en partant du repertoire courant.

        ⚠ Pyxel ne resout PAS ses ressources par rapport au repertoire courant, mais par
        rapport au SCRIPT PRINCIPAL (symboles `exec_path` / `orig_argv` de son binaire).
        Lance depuis une console IPython, sys.argv[0] designe le lanceur du noyau : Pyxel
        cherche alors le .pyxres a cote de spyder_kernels, et echoue avec
        "Failed to open file '<nom>'" - alors que le fichier est bien la, a cote du jeu,
        et que le repertoire courant est correct. Constate en direct le 20/07/2026 sur un
        projet reel.

        On ne corrige que le cas non ambigu : chemin relatif, et fichier reellement
        present dans le repertoire courant. Sinon on laisse passer tel quel, pour ne
        jamais masquer une vraie erreur de chemin ni changer un comportement qui marche.
        """
        try:
            if isinstance(filename, str) and not os.path.isabs(filename):
                # Deux bases d'essai, dans cet ordre :
                #   1. le repertoire courant AU MOMENT DE L'INIT. pyxel.init() modifie le
                #      repertoire courant (constate en direct : une sonde qui se place dans
                #      le dossier du jeu s'y trouve encore juste avant init, mais plus au
                #      moment du load qui suit) - il faut donc l'avoir memorise avant.
                #   2. le repertoire courant actuel, pour les cas ou rien n'a bouge.
                for base in (state.get("cwd_at_init"), os.getcwd()):
                    if not base:
                        continue
                    candidate = os.path.abspath(os.path.join(base, filename))
                    if os.path.exists(candidate):
                        return candidate
        except Exception:
            pass
        return filename

    def patched_load(filename, *args, **kwargs):
        return original_load(_resolve(filename), *args, **kwargs)

    def patched_save(filename, *args, **kwargs):
        return original_save(_resolve(filename), *args, **kwargs)


    def patched_init(*args, **kwargs):
        # SDL choisit son pilote video a SDL_Init, appele par pyxel.init() - et non a
        # l'import du module (verifie en direct). On peut donc imposer le rendu hors ecran
        # ICI, ce qui rend le crochet installable meme dans un noyau qui a deja importe
        # pyxel, par exemple parce qu'un jeu y a deja tourne.
        try:
            state["cwd_at_init"] = os.getcwd()
        except Exception:
            state["cwd_at_init"] = None
        os.environ["SDL_VIDEODRIVER"] = "offscreen"
        # Le pilote offscreen ne fournit pas de contexte GLX ; EGL est ce que sa variante
        # surfaceless sait utiliser.
        os.environ.setdefault("SDL_VIDEO_GL_DRIVER", "libEGL.so.1")

        # Gestionnaire SIGINT en place AVANT l'appel natif, a restaurer juste apres (cf.
        # le bloc de restauration ci-dessous pour le POURQUOI complet).
        sigint_avant = signal.getsignal(signal.SIGINT)

        result = original_init(*args, **kwargs)

        # pyxel.init() installe SON PROPRE gestionnaire SIGINT natif (Rust,
        # pyxel::platform::facade::sigint_handler / SIGINT_RECEIVED - verifie par lecture
        # directe du VRAI sigaction() du processus, pas du cache signal.getsignal() qui
        # reste trompeusement inchange : pyxel appelle sigaction() en C, pas le module
        # signal de Python, donc Python ne voit jamais le remplacement). Consequence :
        # un Ctrl+C externe (bouton Stop de Spyder, interruption du noyau) ne leve plus
        # JAMAIS de KeyboardInterrupt Python - il declenche la sortie native de pyxel
        # (meme famille que patched_quit/l'exception dans update() : le code Python
        # appelant, finally compris, ne reprend jamais la main), qui plante le noyau
        # IPython entier au lieu de se contenter d'interrompre la commande en cours.
        # Restaurer ICI, une seule fois, le gestionnaire qui etait en place juste avant
        # cet appel (celui d'IPython/spyder_kernels en temps normal, pas force a
        # default_int_handler) suffit : verifie en direct que pyxel ne reinstalle PAS le
        # sien a chaque image (adresse sigaction() identique avant et apres plusieurs
        # flip()), et qu'un SIGINT envoye ensuite est bien recu comme un KeyboardInterrupt
        # Python normal, gere par la boucle maison de patched_run comme n'importe quelle
        # autre exception.
        try:
            signal.signal(signal.SIGINT, sigint_avant)
        except (TypeError, ValueError):
            # ValueError : pas le thread principal, on ne peut pas installer de
            # gestionnaire - le noyau IPython tourne toujours cote thread principal en
            # pratique, mais rester silencieux ici plutot que de faire echouer init().
            # TypeError : sigint_avant n'etait pas un gestionnaire installable (None
            # renvoye par exemple si SIGINT etait deja gere par du code natif avant meme
            # cet appel) - rien de plus a faire dans ce cas.
            pass
        # L'editeur de ressources de Pyxel est un programme Pyxel comme un autre : seul
        # le fait que son module ait ete importe permet de le reconnaitre, et donc
        # d'envoyer ses images au panneau "Pyxel Studio" plutot qu'a celui des jeux.
        publisher.set_kind(
            protocol.KIND_EDITOR if "pyxel.editor" in sys.modules
            else protocol.KIND_GAME)
        consumer_holder["consumer"] = InputConsumer(publisher._buf, pyxel)
        # Publier tout de suite : le panneau affiche ainsi l'ecran vide - donc la bonne
        # taille - des l'init, sans attendre la premiere image dessinee.
        publisher.publish(pyxel)
        return result

    def patched_resize(*args, **kwargs):
        result = original_resize(*args, **kwargs)
        publisher.publish(pyxel)
        return result

    def patched_quit():
        # Ne termine PAS le processus (ajout SmartOS) : leve une sentinelle interne que
        # patched_run() attrape pour rendre la main normalement. cf. patched_run pour le
        # POURQUOI complet - en bref, pyxel.run() natif ne rend jamais la main a Python de
        # toute facon (verifie), donc appeler original_quit() ici serait sans effet visible
        # different d'une exception non geree ; c'est la boucle maison de patched_run, plus
        # bas, qui rend ce changement utile.
        raise _ArretJeuVolontaire()

    def patched_run(update, draw):
        def wrapped_update():
            consumer = consumer_holder.get("consumer")
            if consumer is not None:
                consumer.pump()
            update()

        def wrapped_draw():
            draw()
            publisher.publish(pyxel)

        # Boucle ecrite a la main (ajout SmartOS), plutot que original_run(wrapped_update,
        # wrapped_draw) : mesure du 01/08/2026, pyxel.run() natif (Rust/PyO3) NE REND JAMAIS
        # LA MAIN A PYTHON, quelle que soit la facon dont le jeu se termine - ni sur une
        # exception ORDINAIRE issue de update()/draw() (le traceback qui semble s'afficher
        # normalement est en realite imprime par pyxel LUI-MEME, juste avant une sortie
        # native), ni sur pyxel.quit(), ni sur la touche de sortie. Consequence concrete :
        # un profilage (lp_launcher.py) interrompu ne peut jamais ecrire ses mesures pour un
        # jeu Pyxel (contrairement a un script ordinaire, ou une interruption normale du
        # noyau produit un KeyboardInterrupt que Python sait gerer) - et un F5 sur un jeu
        # qui appelle pyxel.quit() lui-meme tuerait le noyau ENTIER de la console, jamais
        # remarque parce que la plupart des jeux comptent sur un arret EXTERNE (Stop,
        # fermeture de fenetre) plutot que sur un pyxel.quit() explicite.
        # pyxel.flip() (original_flip, PAS le patch : celui-ci publie et pompe les entrees
        # DEJA faits ci-dessus, l'appeler doublerait la cadence du compteur d'images cote
        # panneau) EST le mecanisme documente par pyxel pour ecrire sa propre boucle - deja
        # utilise telle quelle par patched_show ci-dessous. Seule la SORTIE change de
        # comportement (patched_quit, au-dessus) ; cadence et entrees restent au natif.
        try:
            while True:
                wrapped_update()
                wrapped_draw()
                original_flip()
        except _ArretJeuVolontaire:
            return

    def patched_flip():
        # Dans une boucle ecrite a la main, l'utilisateur dessine puis appelle flip() :
        # l'ecran est donc pret juste avant l'appel, et les entrees doivent etre a jour
        # juste apres, pour le tour suivant.
        publisher.publish(pyxel)
        result = original_flip()
        consumer = consumer_holder.get("consumer")
        if consumer is not None:
            consumer.pump()
        return result

    def patched_show():
        # `show()` d'origine attend un evenement clavier SDL qui n'arrivera jamais en mode
        # offscreen : on le remplace par une boucle d'images vides, que le panneau
        # interrompt en demandant l'arret.
        while True:
            patched_flip()

    pyxel.load = patched_load
    if original_save is not None:
        pyxel.save = patched_save
    pyxel.init = patched_init
    pyxel.resize = patched_resize
    pyxel.run = patched_run
    pyxel.flip = patched_flip
    pyxel.show = patched_show
    pyxel.quit = patched_quit

    return {
        "init": original_init,
        "resize": original_resize,
        "run": original_run,
        "flip": original_flip,
        "quit": original_quit,
    }
