# -*- coding: utf-8 -*-
"""
Cote noyau IPython : detourne l'image de Pyxel vers le panneau, et rien d'autre.

Ce module est charge DANS le noyau de la console, par une ligne executee silencieusement
au moment ou Spyder cree la console :

    import spyder_pyxel.bridge.kernel as k; k.install("<nom du segment>")

A partir de la, un jeu lance avec F5 s'execute exactement comme avant - ses `print` vont
dans la console, les points d'arret fonctionnent, l'explorateur de variables voit ses
variables, `%debug` marche apres une erreur - a ceci pres que sa fenetre n'apparait plus :
son ecran est publie dans la memoire partagee, et le panneau Pyxel le dessine.

Pourquoi ca peut s'installer AVANT que pyxel soit importe
----------------------------------------------------------
Au moment ou Spyder cree la console, l'utilisateur n'a evidemment encore rien importe. Il
faut donc poser le crochet sur un module qui n'existe pas. Deux cas :

  - pyxel est deja dans sys.modules (une partie a deja tourne dans ce noyau) : on le
    patche immediatement ;
  - sinon on installe un chercheur dans sys.meta_path qui patchera le module juste apres
    son chargement, quel que soit le moment.

Il n'y a AUCUNE contrainte sur l'ordre des imports, parce que le choix du pilote video de
SDL se fait a SDL_Init - appele par pyxel.init() - et non a l'import du module. Verifie en
direct : importer pyxel, poser SDL_VIDEODRIVER ensuite, puis appeler init(), fonctionne.
"""

import sys
import traceback

from spyder_pyxel.bridge import hooks, protocol

_state = {"installed": False, "shm": None, "publisher": None,
          "error": None, "patched": False,
          # ⚠ Garde de reentrance, sans laquelle le noyau SE FIGE sur "import pyxel".
          # Le guetteur d'import ci-dessous s'execute a chaque import ; s'il fait lui-meme
          # le moindre import, il se rappelle, retrouve pyxel encore non marque, et repart
          # - recursion sans fin. C'etait la cause du "l'ecran reste noir" : le jeu ne
          # demarrait meme pas.
          "patching": False, "notify_fd": None}


def _patch_module(pyxel_module):
    """Pose les crochets sur un module pyxel deja charge."""
    if getattr(pyxel_module, "_spyder_pyxel_hooked", False):
        return
    # ⚠ Le module peut etre PARTIELLEMENT initialise : pyxel/__init__.py fait
    # "from .pyxel_binding import *", et pendant cet import interne sys.modules contient
    # deja "pyxel" sans aucune de ses fonctions. Patcher a ce moment-la echoue sur
    # "partially initialized module 'pyxel' has no attribute 'run'". On attend donc que
    # les fonctions visees existent ; l'appel exterieur, lui, trouvera le module complet.
    if not all(hasattr(pyxel_module, name)
               for name in ("init", "run", "flip", "show", "resize")):
        return
    publisher = _state["publisher"]
    if publisher is None:
        return

    consumer_holder = {}
    hooks.install(pyxel_module, publisher, consumer_holder)
    pyxel_module._spyder_pyxel_hooked = True
    _state["patched"] = True


class _PyxelImportHook:
    """Chercheur qui patche pyxel juste apres son chargement.

    On ne fournit pas de chargeur : `find_module`/`find_spec` rend None, donc l'import
    suit son cours normal. Le chercheur sert uniquement de point d'observation - c'est le
    moyen le plus simple de reagir a un import sans se substituer au mecanisme d'import.
    """

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pyxel":
            # On ne peut pas patcher ici : le module n'est pas encore charge. On s'inscrit
            # pour repasser juste apres, via le crochet pose sur sys.modules ci-dessous.
            _state["pending"] = True
        return None


def _install_import_watch():
    """Surveille l'apparition de pyxel dans sys.modules.

    Plutot qu'un chargeur de substitution (fragile : il faudrait reimplementer le
    chargement d'une extension native), on enveloppe __import__ pour repasser juste apres
    l'import du module. C'est un point d'accroche stable et sans effet de bord : on
    delegue integralement a l'implementation d'origine, on regarde seulement le resultat.
    """
    import builtins

    original_import = builtins.__import__

    def watching_import(name, globals=None, locals=None, fromlist=(), level=0):
        module = original_import(name, globals, locals, fromlist, level)
        if not _state["installed"]:
            return module
        if _state["patching"]:
            # Deja en train de poser le crochet : ne pas repartir dans _patch_module,
            # sinon recursion sans fin (cf. le commentaire sur "patching" plus haut).
            return module
        pyxel_module = sys.modules.get("pyxel")
        if pyxel_module is not None and not getattr(
                pyxel_module, "_spyder_pyxel_hooked", False):
            _state["patching"] = True
            try:
                _patch_module(pyxel_module)
            except Exception:
                # Le crochet n'est qu'un confort d'affichage : s'il echoue, le jeu doit
                # continuer de fonctionner normalement, avec sa fenetre. Mais on garde de
                # quoi comprendre pourquoi.
                _state["error"] = traceback.format_exc()
            finally:
                _state["patching"] = False
        return module

    watching_import._spyder_pyxel_wrapper = True
    if not getattr(builtins.__import__, "_spyder_pyxel_wrapper", False):
        builtins.__import__ = watching_import


def install(shm_name):
    """Point d'entree appele dans le noyau. Idempotent."""
    if _state["installed"]:
        return True

    try:
        from multiprocessing import shared_memory

        shm = shared_memory.SharedMemory(name=shm_name)
        # Le segment appartient au panneau, qui le detruira. Sans ce desenregistrement, le
        # "resource tracker" de multiprocessing croirait que ce noyau en est proprietaire
        # et signalerait une fuite a chaque arret.
        try:
            from multiprocessing import resource_tracker

            resource_tracker.unregister(shm._name, "shared_memory")
        except Exception:
            pass

        _state["shm"] = shm

        # Tube de signalement. Ouverture NON BLOQUANTE : elle echoue (ENXIO) si le panneau
        # n'a pas son cote lecture ouvert, ce qui doit rester sans consequence - le
        # panneau retombe alors sur son sondage de secours.
        notify_fd = None
        try:
            import os as _os

            path = protocol.fifo_path(shm_name)
            if _os.path.exists(path):
                notify_fd = _os.open(path, _os.O_WRONLY | _os.O_NONBLOCK)
        except OSError:
            notify_fd = None
        _state["notify_fd"] = notify_fd

        _state["publisher"] = hooks.ScreenPublisher(shm.buf, notify_fd)
        _state["installed"] = True

        _install_import_watch()

        pyxel_module = sys.modules.get("pyxel")
        if pyxel_module is not None:
            _patch_module(pyxel_module)
        return True
    except Exception:
        # Conserve, pas efface : c'est le seul moyen de diagnostiquer un panneau noir.
        _state["error"] = traceback.format_exc()
        _state["installed"] = False
        return False


def uninstall():
    """Rend la main a Pyxel (fenetre normale). Utilise a la fermeture de la console."""
    publisher = _state.get("publisher")
    if publisher is not None:
        publisher.close()
    fd = _state.get("notify_fd")
    if fd is not None:
        try:
            import os as _os

            _os.close(fd)
        except OSError:
            pass
    shm = _state.get("shm")
    if shm is not None:
        try:
            shm.close()
        except Exception:
            pass
    _state.update({"installed": False, "shm": None, "publisher": None,
                   "notify_fd": None})


def status():
    """Etat du crochet, a consulter depuis la console pour diagnostiquer un panneau noir.

        import spyder_pyxel.bridge.kernel as k; print(k.status())

    "installed" : le crochet a bien ete pose dans ce noyau.
    "patched"   : le module pyxel a effectivement ete detourne (donc pyxel a ete importe).
    "error"     : la trace de l'echec, le cas echeant.
    """
    return {
        "installed": _state["installed"],
        "patched": _state["patched"],
        "shm": _state["shm"].name if _state["shm"] is not None else None,
        "signalement": _state["notify_fd"] is not None,
        "error": _state["error"],
    }
