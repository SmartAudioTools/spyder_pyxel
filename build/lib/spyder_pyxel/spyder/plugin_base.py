# -*- coding: utf-8 -*-
"""
Ce que les deux greffons Pyxel ont en commun : suivre les consoles.

⚠ Ce module n'est le module d'AUCUN point d'entree, et ce n'est pas un hasard. Spyder
identifie chaque greffon externe par le nom de module de son point d'entree
(spyder/app/find_plugins.py pose `_spyder_module_name = entry_point.module`), que
plugin_registration/registry.py passe ensuite a dependencies.add(), lequel REFUSE tout
doublon. Deux points d'entree visant le meme module font donc echouer l'enregistrement du
second, quel que soit son NAME. D'ou plugin.py et plugin_studio.py separes - mais rien
n'interdit qu'ils partagent une classe de base, importee et non pointee.

Aucun des deux greffons n'execute quoi que ce soit : ils installent un crochet dans chaque
console et affichent ce que les noyaux publient. Un jeu se lance avec F5, comme n'importe
quel script - ses `print` vont dans la console, les points d'arret fonctionnent, seule sa
fenetre est remplacee par le panneau.
"""

from spyder.api.plugin_registration.decorators import (
    on_plugin_available, on_plugin_teardown)
from spyder.api.plugins import Plugins, SpyderDockablePlugin

from spyder_pyxel.spyder.bridge_manager import get_bridge


class PyxelPanePlugin(SpyderDockablePlugin):
    """Socle des deux greffons : abonnement aux consoles, liberation des canaux.

    Les deux s'abonnent aux memes signaux. Le pont partage ne cree qu'un canal par
    console et `attach_console` est idempotent : peu importe donc lequel des deux
    greffons est initialise en premier.
    """

    REQUIRES = [Plugins.IPythonConsole]
    OPTIONAL = []
    TABIFY = [Plugins.Help]
    CONF_FILE = True

    # Sans ceci, PluginMainWidget.change_visibility() ne redonne jamais le clavier a
    # get_focus_widget() (l'ecran Pyxel courant) quand Spyder REMONTRE ce panneau sans
    # que l'utilisateur y ait cliqué - notamment apres layout.plugin.maximize_dockwidget()
    # (bouton "agrandir ce panneau"), qui reparente le widget via setCentralWidget() SANS
    # rappeler get_focus_widget().setFocus() dans sa branche de maximisation (seule la
    # branche de restauration le fait). Signale par l'utilisateur le 31/07/2026 : "après
    # agrandissement du panneau, le jeu ne répond plus aux touches". Meme attribut, meme
    # raison, deja pose par les greffons Console, IPythonConsole et FindInFiles de Spyder.
    RAISE_AND_FOCUS = True

    def on_initialize(self):
        pass

    @on_plugin_available(plugin=Plugins.IPythonConsole)
    def on_console_available(self):
        console = self.get_plugin(Plugins.IPythonConsole)
        bridge = get_bridge()

        console.sig_shellwidget_created.connect(bridge.attach_console)
        console.sig_shellwidget_deleted.connect(bridge.detach_console)

        # Les consoles deja ouvertes quand le greffon s'initialise n'emettront jamais
        # sig_shellwidget_created : sans cette reprise, il faudrait ouvrir une nouvelle
        # console pour que le panneau serve a quelque chose.
        #
        # ⚠ TOUTES, pas seulement la courante. Une version precedente ne reprenait que
        # `get_current_shellwidget()` : un jeu lance dans une des AUTRES consoles deja
        # ouvertes s'affichait dans sa propre fenetre, sans que rien ne le dise. C'est
        # l'une des deux causes du "pas systematiquement" signale le 26/07/2026 (l'autre
        # est la course sur le premier invite, cf. bridge_manager.attach_console).
        for shellwidget in self._consoles_ouvertes(console):
            bridge.attach_console(shellwidget)

    @staticmethod
    def _consoles_ouvertes(console):
        """Les consoles deja ouvertes, la courante en dernier recours.

        `get_clients()` est l'API publique du greffon IPythonConsole ; on retombe sur la
        console courante si elle venait a disparaitre, plutot que de ne rien attacher.
        """
        shellwidgets = []
        try:
            for client in console.get_clients() or ():
                shellwidget = getattr(client, "shellwidget", None)
                if shellwidget is not None:
                    shellwidgets.append(shellwidget)
        except Exception:
            pass
        if not shellwidgets:
            current = console.get_current_shellwidget()
            if current is not None:
                shellwidgets.append(current)
        return shellwidgets

    @on_plugin_teardown(plugin=Plugins.IPythonConsole)
    def on_console_teardown(self):
        console = self.get_plugin(Plugins.IPythonConsole)
        bridge = get_bridge()
        for signal, slot in (
            (console.sig_shellwidget_created, bridge.attach_console),
            (console.sig_shellwidget_deleted, bridge.detach_console),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def on_close(self, cancelable=False):
        # Les segments partages survivraient dans /dev/shm si personne ne les liberait.
        # Appele par les deux greffons : release_all est sans effet la seconde fois.
        get_bridge().release_all()
        return True
