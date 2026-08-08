# -*- coding: utf-8 -*-
"""
Format de la memoire partagee entre le panneau Qt et le processus qui execute Pyxel.

Ce que le pont resout
---------------------
On veut qu'un jeu Pyxel lance normalement depuis Spyder (F5) s'execute VRAIMENT
normalement - sortie dans la console, points d'arret, explorateur de variables - et que
seule son image parte dans un panneau.

La solution "evidente" serait de recuperer la fenetre SDL du jeu et de la reparenter dans
un widget Qt (XEmbed / QWindow.fromWinId). Elle ne marche que sous X11 : la session KDE de
cette machine est Wayland, et sous Wayland un client ne peut pas reparenter la surface
d'un autre client - c'est un choix de conception du protocole, pas une lacune temporaire.

On ne transporte donc pas une fenetre, mais des *pixels*. Pyxel 2.9.x expose tout ce qu'il
faut : `pyxel.screen.data_ptr()` (framebuffer indexe, un octet par pixel), `pyxel.colors`
(la palette), et `set_btn()` / `set_btnv()` / `set_mouse_pos()` / `set_input_text()` pour
injecter les entrees. Le jeu tourne sans fenetre (SDL_VIDEODRIVER=offscreen) et le
panneau redessine lui-meme. C'est independant du serveur d'affichage.

Qui ecrit quoi
--------------
Le jeu s'execute dans le NOYAU IPYTHON, qui est deja un processus separe de l'interface de
Spyder - la memoire partagee tombe donc juste, sans qu'on ait rien a lancer nous-memes.
L'editeur de ressources passe par le meme chemin : c'est un programme Pyxel comme un autre,
lance lui aussi depuis la console. Un marqueur dans l'en-tete (KIND_*) dit auquel des deux
panneaux chaque image est destinee.

  zone IMAGE    ecrite par le jeu,     lue par le panneau
  zone ENTREES  ecrite par le panneau, lue par le jeu

Pourquoi un anneau pour les entrees, et pas un tuyau
-----------------------------------------------------
Les touches ne peuvent pas passer par stdin : celui d'un noyau IPython lui appartient. Elles passent donc par un anneau dans la
meme memoire partagee, ce qui a l'avantage de ramener le pont a UN seul canal.

L'anneau preserve l'ORDRE, ce qui est indispensable : un appui suivi d'un relachement ne
doit jamais etre reordonne, sinon une touche reste enfoncee pour toujours. Le panneau
incremente un compteur d'ecriture monotone ; le jeu retient son propre compteur de lecture
et consomme ce qui est arrive depuis la frame precedente. Avec 1024 emplacements et 60
images par seconde, il faudrait produire plus de 60 000 evenements par seconde pour
perdre quoi que ce soit.

Coherence de lecture des images : sequence lock (seqlock)
---------------------------------------------------------
Il n'y a pas de verrou entre les deux processus. L'ecrivain incremente SEQ avant d'ecrire
(valeur impaire = ecriture en cours) et apres avoir fini (valeur paire). Le lecteur lit
SEQ, copie, relit SEQ : si la valeur a change ou etait impaire, il a lu une image a moitie
ecrite et recommence. Le lecteur ne bloque donc jamais l'ecrivain - ce qui compte, car
l'ecrivain est le jeu et doit tenir ses 60 images par seconde.
"""

import os

# Taille maximale d'ecran prise en charge. Pyxel limite deja les ecrans a 256x256 ; on
# reserve le double pour ne pas avoir a changer ce format si la limite montait un jour.
MAX_SCREEN_SIZE = 512

MAGIC = 0x50594B4C  # "PYKL"

# --- Zone IMAGE (jeu -> panneau) ---------------------------------------------

OFF_MAGIC = 0
OFF_SEQ = 4
OFF_WIDTH = 8
OFF_HEIGHT = 12
OFF_NCOLORS = 16
OFF_STATE = 20
OFF_FRAME = 24
OFF_PUBLISHER_PID = 28
MAX_COLORS = 256
OFF_PALETTE = 32           # 256 * 4 octets -> occupe jusqu'a 1056

# Place APRES la palette : celle-ci est dimensionnee pour MAX_COLORS entrees, soit 1056
# octets, meme si Pyxel n'en utilise que 16 aujourd'hui. Le marqueur etait initialement a
# 1024, dans la zone reservee a la palette - sans consequence visible, mais une palette
# etendue l'aurait ecrase silencieusement. L'assertion en fin de module l'a rattrape.
OFF_KIND = 1088            # nature du programme qui publie (cf. KIND_* ci-dessous)

# Valeurs du champ STATE.
STATE_IDLE = 0       # personne ne publie (pyxel.init() pas encore appele)
STATE_RUNNING = 1    # au moins une image publiee
STATE_STOPPED = 2    # le jeu s'est arrete

# Valeurs du champ KIND. Tout part desormais de la console : c'est ce marqueur, et non un
# bouton, qui dit auquel des deux panneaux l'image est destinee. L'editeur de ressources de
# Pyxel etant lui-meme un programme Pyxel, rien d'autre ne permettrait de les distinguer.
KIND_GAME = 0
KIND_EDITOR = 1

# --- Zone ENTREES (panneau -> jeu) -------------------------------------------

# 1536 : ancien champ "demande d'arret", supprime. Il n'a plus d'objet depuis que les
# panneaux n'ont plus de bouton : on arrete un jeu depuis la console, comme n'importe quel
# script. Et il etait de toute facon inoperant - Pyxel coupe le processus depuis son coeur
# Rust, donc lever une exception pour sortir de pyxel.run() tuait le noyau au lieu de
# rendre la main. L'offset reste libre plutot que reutilise, pour qu'un ancien publieur et
# un nouveau panneau ne se marchent pas dessus.
OFF_INPUT_WRITE = 1540     # compteur monotone d'evenements ecrits par le panneau

INPUT_SLOTS = 1024
INPUT_SLOT_SIZE = 16       # kind (u32) + trois entiers signes
OFF_INPUT_RING = 1600

# Types d'evenements d'entree.
EVENT_KEY = 1        # a = code Pyxel, b = 1 enfonce / 0 relache
EVENT_MOUSE = 2      # a = x, b = y (coordonnees ecran du jeu)
EVENT_WHEEL = 3      # a = crans horizontaux, b = crans verticaux
EVENT_TEXT = 4       # a = point de code Unicode (un evenement par caractere)
EVENT_RELEASE_ALL = 5  # relacher toutes les touches encore enfoncees

# --- Zone PIXELS -------------------------------------------------------------

# Alignee sur une frontiere ronde : memmove est plus rapide sur des adresses alignees, et
# un vidage hexadecimal reste lisible pendant un debogage.
# 20480 et non 4096 : l'anneau d'entrees occupe a lui seul 16 Ko (1024 x 16 octets) a
# partir de 1600. L'assertion en fin de module verifie ce calcul - elle a deja rattrape la
# valeur trop basse.
OFF_FRAMEBUFFER = 20480
FRAMEBUFFER_BYTES = MAX_SCREEN_SIZE * MAX_SCREEN_SIZE

SHM_SIZE = OFF_FRAMEBUFFER + FRAMEBUFFER_BYTES

# Verification a l'import : une modification maladroite des offsets ci-dessus ferait
# silencieusement chevaucher deux zones, et le jeu ecraserait ses propres entrees.
assert OFF_PALETTE + MAX_COLORS * 4 <= OFF_KIND, "palette et marqueur se chevauchent"
assert OFF_KIND < OFF_INPUT_WRITE, "marqueur et zone d'entrees se chevauchent"
assert OFF_INPUT_RING + INPUT_SLOTS * INPUT_SLOT_SIZE <= OFF_FRAMEBUFFER, \
    "anneau d'entrees et framebuffer se chevauchent"

# Variable d'environnement demandant des traces sur stderr.
DEBUG_ENV = "SPYDER_PYXEL_DEBUG"


def fifo_path(shm_name):
    """Chemin du tube nomme signalant qu'une image vient d'etre publiee.

    Le sondage seul ne peut pas faire mieux que la moitie de sa periode en gigue : le
    panneau ne sait pas QUAND une image est prete, il regarde a intervalle fixe. Un tube
    nomme renverse la charge - le jeu ecrit un octet apres chaque publication, et Qt
    reveille le panneau exactement a cet instant (QSocketNotifier).

    Un tube nomme, et non un descripteur herite : le jeu tourne dans un noyau IPython
    demarre par Spyder bien avant, on ne peut rien lui transmettre d'autre qu'un chemin.
    Il se deduit du nom du segment, deja transmis, pour n'avoir qu'une seule information a
    faire circuler.
    """
    import tempfile

    return os.path.join(tempfile.gettempdir(), shm_name + ".fifo")


def make_shm_name(pid, suffix=""):
    """Nom de segment unique et reconnaissable dans /dev/shm."""
    import uuid

    return f"spyder_pyxel_{pid}{suffix}_{uuid.uuid4().hex[:8]}"
