# -*- coding: utf-8 -*-
"""
Cote panneau : creation du segment partage, lecture des images, envoi des entrees.

Ce module ne connait pas Qt. Il est donc testable sans interface graphique - ce qui a servi
a valider le protocole avant d'ecrire le widget.
"""

import os
import struct

from multiprocessing import shared_memory
from pathlib import Path

from spyder_pyxel.bridge import protocol


class Frame:
    """Une image lue dans la memoire partagee.

    `pixels` est un bloc d'octets d'indices de palette, une ligne apres l'autre, sans
    remplissage : la ligne fait exactement `width` octets.
    """

    __slots__ = ("width", "height", "pixels", "palette", "number")

    def __init__(self, width, height, pixels, palette, number):
        self.width = width
        self.height = height
        self.pixels = pixels
        self.palette = palette
        self.number = number


class PyxelChannel:
    """Un segment partage : images entrantes, entrees sortantes."""

    def __init__(self):
        self._shm = None
        self._last_seq = -1
        self._write_index = 0
        self._fifo_path = None
        self._notify_fd = None

    # --- Cycle de vie -------------------------------------------------------

    def create(self, suffix=""):
        name = protocol.make_shm_name(os.getpid(), suffix)
        self._shm = shared_memory.SharedMemory(
            name=name, create=True, size=protocol.SHM_SIZE
        )
        # Etat de depart : tant que personne n'a publie, le panneau doit savoir qu'il n'y a
        # rien a afficher plutot que de peindre le contenu aleatoire du segment.
        struct.pack_into("<I", self._shm.buf, protocol.OFF_MAGIC, 0)
        struct.pack_into("<I", self._shm.buf, protocol.OFF_SEQ, 0)
        struct.pack_into("<I", self._shm.buf, protocol.OFF_STATE, protocol.STATE_IDLE)
        struct.pack_into("<I", self._shm.buf, protocol.OFF_INPUT_WRITE, 0)
        self._last_seq = -1
        self._write_index = 0

        # Tube de signalement. On ouvre le cote LECTURE ici, avant meme que le jeu
        # existe : un tube nomme ouvert en ecriture seule echoue (ENXIO) tant qu'aucun
        # lecteur ne l'a ouvert. C'est donc au panneau d'ouvrir en premier, et de garder
        # ouvert. O_NONBLOCK des deux cotes : rien ne doit jamais bloquer sur ce canal,
        # qui n'est qu'une notification.
        self._fifo_path = protocol.fifo_path(name)
        try:
            if os.path.exists(self._fifo_path):
                os.unlink(self._fifo_path)
            os.mkfifo(self._fifo_path, 0o600)
            self._notify_fd = os.open(self._fifo_path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            # Sans tube, le panneau retombe sur son sondage de secours : degrade mais
            # fonctionnel. Mieux vaut ca qu'un panneau qui n'affiche rien.
            self._fifo_path = None
            self._notify_fd = None
        return name

    @property
    def notify_fd(self):
        """Descripteur a surveiller pour etre reveille des qu'une image est publiee."""
        return self._notify_fd

    def drain_notifications(self):
        """Vide le tube. Le nombre d'octets n'a aucune importance : seule compte la
        DERNIERE image, qui est de toute facon celle que read_frame() renverra."""
        if self._notify_fd is None:
            return
        try:
            while os.read(self._notify_fd, 4096):
                pass
        except (BlockingIOError, InterruptedError, OSError):
            pass

    def release(self):
        if self._notify_fd is not None:
            try:
                os.close(self._notify_fd)
            except OSError:
                pass
            self._notify_fd = None
        if self._fifo_path is not None:
            try:
                os.unlink(self._fifo_path)
            except OSError:
                pass
            self._fifo_path = None
        if self._shm is None:
            return
        try:
            self._shm.close()
        except Exception:
            pass
        try:
            self._shm.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
        self._shm = None

    @property
    def name(self):
        return self._shm.name if self._shm is not None else None

    @property
    def is_open(self):
        return self._shm is not None

    # --- Lecture des images --------------------------------------------------

    def publisher_alive(self):
        """Le programme qui publie sur ce canal tourne-t-il encore ?

        ⚠ C'est le SEUL moyen de l'apprendre. Pyxel COUPE LE PROCESSUS depuis son coeur
        Rust quand un jeu se termine (cf. README) : aucun code Python ne s'execute ensuite,
        donc ScreenPublisher.close() n'est jamais appele et STATE_STOPPED n'est jamais
        ecrit. Sans ce controle, la derniere image du jeu reste figee dans le panneau pour
        toujours - constate par l'utilisateur le 21/07/2026.

        Le PID est inscrit dans l'en-tete a la construction du publieur. On rend True tant
        que rien ne prouve le contraire : mieux vaut une image figee qu'un panneau vide a
        tort.
        """
        if self._shm is None:
            return False
        try:
            pid = struct.unpack_from("<I", self._shm.buf, protocol.OFF_PUBLISHER_PID)[0]
        except Exception:
            return True
        if not pid:
            return True
        try:
            # Signal 0 : ne fait rien, mais echoue si le processus n'existe plus.
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            # PermissionError et consorts : le processus existe, il ne nous appartient pas.
            return True
        return True

    def state(self):
        if self._shm is None:
            return protocol.STATE_STOPPED
        magic = struct.unpack_from("<I", self._shm.buf, protocol.OFF_MAGIC)[0]
        if magic != protocol.MAGIC:
            return protocol.STATE_IDLE
        return struct.unpack_from("<I", self._shm.buf, protocol.OFF_STATE)[0]

    def kind(self):
        """Marqueur du programme qui publie : jeu ou editeur de ressources.

        C'est lui, et non un bouton, qui dit auquel des deux panneaux l'image est
        destinee - l'editeur de ressources de Pyxel etant lui-meme un programme Pyxel,
        rien d'autre ne permettrait de les distinguer.
        """
        if self._shm is None:
            return protocol.KIND_GAME
        return struct.unpack_from("<I", self._shm.buf, protocol.OFF_KIND)[0]

    def read_frame(self, only_if_new=True):
        """Retourne la derniere image publiee, ou None.

        `only_if_new` evite de reconstruire une QImage quand rien n'a ete redessine depuis
        le dernier appel (jeu en pause, ou panneau rafraichi plus vite que le jeu).
        """
        if self._shm is None:
            return None
        buf = self._shm.buf

        if struct.unpack_from("<I", buf, protocol.OFF_MAGIC)[0] != protocol.MAGIC:
            return None

        # Cote lecteur du seqlock : on relit la sequence apres la copie, et on recommence
        # si l'ecrivain est passe par la entre-temps. Trois essais suffisent largement - a
        # 60 images par seconde, la fenetre d'ecriture est de l'ordre de la dizaine de
        # microsecondes - et l'echec se traduit par "pas de nouvelle image", donc au pire
        # une image reaffichee.
        for _ in range(3):
            seq_before = struct.unpack_from("<I", buf, protocol.OFF_SEQ)[0]
            if seq_before % 2 == 1:
                continue
            if only_if_new and seq_before == self._last_seq:
                return None

            width = struct.unpack_from("<I", buf, protocol.OFF_WIDTH)[0]
            height = struct.unpack_from("<I", buf, protocol.OFF_HEIGHT)[0]
            ncolors = struct.unpack_from("<I", buf, protocol.OFF_NCOLORS)[0]
            number = struct.unpack_from("<I", buf, protocol.OFF_FRAME)[0]

            if not (0 < width <= protocol.MAX_SCREEN_SIZE
                    and 0 < height <= protocol.MAX_SCREEN_SIZE
                    and 0 < ncolors <= protocol.MAX_COLORS):
                return None

            palette_bytes = bytes(
                buf[protocol.OFF_PALETTE:protocol.OFF_PALETTE + ncolors * 4])
            nbytes = width * height
            pixels = bytes(
                buf[protocol.OFF_FRAMEBUFFER:protocol.OFF_FRAMEBUFFER + nbytes])

            if struct.unpack_from("<I", buf, protocol.OFF_SEQ)[0] != seq_before:
                continue

            self._last_seq = seq_before
            palette = [struct.unpack_from("<I", palette_bytes, i * 4)[0]
                       for i in range(ncolors)]
            return Frame(width, height, pixels, palette, number)

        return None

    # --- Envoi des entrees ---------------------------------------------------

    def send_event(self, kind, a=0, b=0):
        """Depose un evenement dans l'anneau.

        L'emplacement est rempli AVANT de publier le nouveau compteur d'ecriture : dans le
        cas contraire, le jeu pourrait lire un emplacement pas encore ecrit.
        """
        if self._shm is None:
            return
        buf = self._shm.buf
        offset = (protocol.OFF_INPUT_RING
                  + (self._write_index % protocol.INPUT_SLOTS)
                  * protocol.INPUT_SLOT_SIZE)
        struct.pack_into("<Iiii", buf, offset, kind, int(a), int(b), 0)
        self._write_index += 1
        struct.pack_into("<I", buf, protocol.OFF_INPUT_WRITE, self._write_index)

    def send_key(self, code, pressed):
        self.send_event(protocol.EVENT_KEY, code, 1 if pressed else 0)

    def send_mouse(self, x, y):
        self.send_event(protocol.EVENT_MOUSE, int(x), int(y))

    def send_wheel(self, dx, dy):
        self.send_event(protocol.EVENT_WHEEL, dx, dy)

    def send_text(self, text):
        # Un evenement par caractere : les emplacements de l'anneau sont de taille fixe, ce
        # qui interdit d'y loger une chaine. La saisie de texte est rare et courte (elle
        # sert surtout aux champs de Pyxel Studio), le decoupage ne coute rien.
        for character in text:
            self.send_event(protocol.EVENT_TEXT, ord(character), 0)

    def send_release_all(self):
        self.send_event(protocol.EVENT_RELEASE_ALL)


def kernel_bootstrap_code(shm_name):
    """Ligne executee silencieusement dans le noyau IPython pour y poser le crochet.

    Le chemin du paquet est ajoute explicitement a sys.path : le noyau de la console n'est
    pas forcement le meme interpreteur que Spyder, et spyder_pyxel n'y est pas
    necessairement installe. Seul pyxel doit vraiment y etre present.

    L'echec est ATTRAPE mais pas efface : le message est conserve dans
    spyder_pyxel.bridge.kernel.status(), consultable depuis la console. Une version
    precedente faisait "except: pass", ce qui rendait toute panne indiagnostiquable - un
    panneau noir, et rien d'autre a se mettre sous la dent.
    """
    package_root = str(Path(__file__).resolve().parents[2])
    return (
        "import sys as _s\n"
        f"_p = {package_root!r}\n"
        "_s.path.insert(0, _p) if _p not in _s.path else None\n"
        "try:\n"
        "    import spyder_pyxel.bridge.kernel as _k\n"
        f"    _k.install({shm_name!r})\n"
        "except Exception as _e:\n"
        "    import traceback as _tb\n"
        "    _s.modules.setdefault('_spyder_pyxel_error', _tb.format_exc())\n"
        "del _s, _p\n"
    )
