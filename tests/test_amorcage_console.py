# -*- coding: utf-8 -*-
"""
Quand le crochet est-il pose dans une console ? Avant le jeu, TOUJOURS.

Le defaut vise : "le jeu ne se lance pas systematiquement dans le panneau Pyxel, mais
parfois dans sa propre fenetre" (26/07/2026). Trois causes, toutes trois couvertes ici.

  1. UNE COURSE. A la creation d'une console, deux evenements arrivent sans ordre garanti
     entre eux : la poignee de main du noyau Spyder (`sig_kernel_is_ready`) et l'affichage
     du premier invite (`sig_prompt_ready`). Lancer un fichier dans une console pas encore
     prete attend, lui, `sig_prompt_ready`. Si l'invite gagne, `runfile` part avant notre
     amorcage : le jeu importe pyxel sans crochet, ouvre sa fenetre, et sa boucle occupe le
     noyau pour toujours - notre amorcage ne s'executera jamais.
  2. LES CONSOLES DEJA OUVERTES. Seule la console COURANTE etait reprise a l'initialisation
     du greffon ; un jeu lance dans une autre s'affichait dans sa propre fenetre.
  3. UNE CONSOLE DEDIEE TOUTE NEUVE (signale par l'utilisateur le 31/07/2026, apres le
     correctif de la cause 1 : "il faut un deuxieme demarrage"). Pour une console creee au
     moment meme du F5 ("executer dans une console dediee"), Spyder connecte SA PROPRE
     execution a `sig_prompt_ready` de facon SYNCHRONE, dans IPythonConsoleWidget.
     run_script - donc AVANT que notre attach_console ne soit meme appele, qui ne part que
     du callback ASYNCHRONE de connexion au noyau. La cause 1 suppose que NOTRE connexion a
     sig_prompt_ready peut arriver en premier ; ici elle arrive TOUJOURS en second, et rien
     dans la cause 1 ne le couvre. D'ou le coup d'essai immediat, hors de toute attente d'un
     signal quelconque : cf. test_console_toute_neuve_le_coup_d_essai_gagne_la_course.

Ces tests portent sur l'ORDRE et sur le NOMBRE d'amorcages, pas sur ce qu'ils contiennent :
c'est exactement ce que la course fait varier.

Lancement :
    QT_QPA_PLATFORM=offscreen python tests/test_amorcage_console.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qtpy.QtCore import QObject, Signal  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

from spyder_pyxel.spyder import bridge_manager  # noqa: E402


class ConsoleFactice(QObject):
    """Une console reduite a ce dont le pont se sert : deux signaux et un execute."""

    sig_kernel_is_ready = Signal()
    sig_prompt_ready = Signal()

    def __init__(self):
        super().__init__()
        self.spyder_kernel_ready = False
        self.amorcages = []

    def silent_execute(self, code):
        self.amorcages.append(code)


def pont_neuf():
    """Le pont est un objet unique partage par toute la session : on le renouvelle."""
    bridge_manager._bridge = None
    return bridge_manager.get_bridge()


def test_l_invite_seul_suffit_a_poser_le_crochet():
    """Si l'invite gagne la course, l'amorcage part quand meme - et AVANT le jeu.

    `attach_console` amorce desormais tout de suite, en coup d'essai (cf. cause 3 de
    l'entete) : un premier amorcage part donc AVANT le moindre signal, et le premier
    invite en ajoute un second (l'etat officiel, _hooked, ne se pose que la).
    """
    bridge = pont_neuf()
    console = ConsoleFactice()
    bridge.attach_console(console)
    assert len(console.amorcages) == 1, (
        f"{len(console.amorcages)} amorcage(s) avant le moindre signal, attendu 1 : "
        "le coup d'essai immediat doit partir des attach_console")
    assert "spyder_pyxel.bridge.kernel" in console.amorcages[0]

    console.sig_prompt_ready.emit()
    assert len(console.amorcages) == 2, (
        f"{len(console.amorcages)} amorcage(s) apres le premier invite, attendu 2 "
        f"(coup d'essai + officiel) : le jeu lance sur cet invite partirait sans crochet")
    print("OK  le premier invite suffit a poser le crochet")


def test_le_slot_du_pont_passe_devant_celui_qui_lance_le_jeu():
    """Qt sert les slots dans l'ordre des connexions, et le notre est le plus ancien.

    C'est TOUT le correctif : le pont se connecte a la creation de la console, Spyder ne
    connecte son `_run` qu'au moment ou l'utilisateur demande l'execution. L'amorcage
    entre donc dans la file du noyau avant `runfile`.
    """
    bridge = pont_neuf()
    console = ConsoleFactice()
    bridge.attach_console(console)          # le pont se connecte ici...

    ordre = []
    console.silent_execute = lambda code: ordre.append("amorcage")
    # ... et "Spyder" seulement maintenant, quand l'utilisateur appuie sur F5.
    console.sig_prompt_ready.connect(lambda: ordre.append("runfile"))
    console.sig_prompt_ready.emit()

    assert ordre == ["amorcage", "runfile"], (
        f"ordre observe {ordre} : le jeu partirait avant le crochet")
    print("OK  l'amorcage passe devant le lancement du jeu")


def test_un_seul_amorcage_officiel_meme_apres_cent_invites():
    """`sig_prompt_ready` est emis a CHAQUE commande : pas question d'amorcer a chaque
    fois - ni de laisser grossir au-dela du coup d'essai (1) + l'officiel (1)."""
    bridge = pont_neuf()
    console = ConsoleFactice()
    bridge.attach_console(console)

    for _ in range(100):
        console.sig_prompt_ready.emit()
    assert len(console.amorcages) == 2, (
        f"{len(console.amorcages)} amorcages pour 100 invites (coup d'essai + officiel "
        f"attendus, soit 2) : le noyau recevrait une execution silencieuse a chaque "
        f"ligne tapee")
    print("OK  coup d'essai + un seul amorcage officiel, meme apres cent invites")


def test_le_redemarrage_du_noyau_repose_le_crochet():
    """Un noyau neuf n'a plus le crochet : `sig_kernel_is_ready` doit le reposer."""
    bridge = pont_neuf()
    console = ConsoleFactice()
    bridge.attach_console(console)

    console.sig_prompt_ready.emit()          # premier noyau
    console.sig_kernel_is_ready.emit()       # redemarrage
    assert len(console.amorcages) >= 2, (
        "aucun amorcage apres le redemarrage : le noyau neuf n'a pas de crochet, et le "
        "jeu suivant ouvrirait sa propre fenetre")
    print("OK  le redemarrage du noyau repose le crochet")


def test_console_toute_neuve_le_coup_d_essai_gagne_la_course():
    """Le cas reel du 31/07/2026 : Spyder se connecte a sig_prompt_ready AVANT que notre
    pont ne connaisse meme la console (console dediee toute neuve, creee au moment du F5 -
    cf. cause 3 de l'entete). La cause 1 (test_le_slot_du_pont_passe_devant_celui_qui_
    lance_le_jeu) suppose l'ordre inverse et ne l'aurait jamais attrape.
    """
    bridge = pont_neuf()
    console = ConsoleFactice()

    ordre = []
    # Spyder connecte SA PROPRE execution EN PREMIER, avant que le pont sache quoi que ce
    # soit de cette console - exactement ce qui se passe pour une console dediee neuve
    # (IPythonConsoleWidget.run_script se connecte de facon synchrone, notre attach_console
    # ne part que du callback asynchrone de connexion au noyau, plus tard).
    console.sig_prompt_ready.connect(lambda: ordre.append("runfile"))

    original = console.silent_execute

    def silent_execute_trace(code):
        ordre.append("amorcage")
        original(code)

    console.silent_execute = silent_execute_trace

    bridge.attach_console(console)
    assert ordre == ["amorcage"], (
        f"{ordre} : le coup d'essai doit partir de attach_console lui-meme, sans "
        f"attendre le moindre signal - c'est le seul moyen de devancer une connexion "
        f"que Spyder a deja posee avant nous")

    console.sig_prompt_ready.emit()      # le premier invite, celui que Spyder attendait
    assert ordre[0] == "amorcage", (
        f"ordre observe {ordre} : meme connecte apres Spyder, le coup d'essai doit avoir "
        f"amorce EN PREMIER - sinon le jeu partirait avant le crochet, comme signale par "
        f"l'utilisateur (\"il faut un deuxieme demarrage\")")
    print("OK  meme si Spyder se connecte avant nous, le coup d'essai gagne la course")


def test_toutes_les_consoles_deja_ouvertes_sont_reprises():
    """Pas seulement la courante : un jeu lance dans une autre s'y afficherait dehors."""
    from spyder_pyxel.spyder.plugin_base import PyxelPanePlugin

    class ClientFactice:
        def __init__(self, shellwidget):
            self.shellwidget = shellwidget

    consoles = [ConsoleFactice() for _ in range(3)]

    class GreffonConsoleFactice:
        def get_clients(self):
            return [ClientFactice(c) for c in consoles]

        def get_current_shellwidget(self):
            return consoles[0]

    reprises = PyxelPanePlugin._consoles_ouvertes(GreffonConsoleFactice())
    assert list(reprises) == consoles, (
        f"{len(reprises)} console(s) reprise(s) sur {len(consoles)} : celles qui manquent "
        f"lanceraient leur jeu dans leur propre fenetre")

    # Et si l'API ne rend rien, la courante reste rattrapee.
    class GreffonSansClients:
        def get_clients(self):
            return []

        def get_current_shellwidget(self):
            return consoles[1]

    assert PyxelPanePlugin._consoles_ouvertes(GreffonSansClients()) == [consoles[1]]
    print("OK  toutes les consoles deja ouvertes sont reprises")


def main():
    app = QApplication.instance() or QApplication([])
    test_l_invite_seul_suffit_a_poser_le_crochet()
    test_le_slot_du_pont_passe_devant_celui_qui_lance_le_jeu()
    test_un_seul_amorcage_officiel_meme_apres_cent_invites()
    test_le_redemarrage_du_noyau_repose_le_crochet()
    test_console_toute_neuve_le_coup_d_essai_gagne_la_course()
    test_toutes_les_consoles_deja_ouvertes_sont_reprises()
    # Chaque console attachee ouvre un segment de memoire partagee : sans cela, le
    # traqueur de ressources signale des fuites a la sortie.
    bridge_manager.get_bridge().release_all()
    bridge_manager._bridge = None
    del app
    print("\nLE CROCHET EST POSE AVANT LE JEU, QUEL QUE SOIT L'ORDRE DES SIGNAUX")


if __name__ == "__main__":
    main()
