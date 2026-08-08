# -*- coding: utf-8 -*-
"""
Construit les deux panneaux comme Spyder le fait, et exerce les crochets de greffon.

Spyder instancie un PluginMainWidget puis appelle `_setup()`, `setup()` et
`update_actions()` dans cet ordre (spyder/api/plugins/new_api.py). Beaucoup d'erreurs
d'API ne se voient qu'a ce moment-la, et se manifesteraient sinon par un panneau
simplement absent au demarrage, avec pour seul indice une ligne dans la console.

Ce test verifie AUSSI les attributs que les methodes `on_plugin_available` vont chercher.
Une version precedente utilisait `ToolsMenuSections.Tools`, qui n'existe plus en Spyder
6.1 : les deux greffons echouaient au demarrage, et l'ancien test ne l'avait pas vu parce
qu'il n'exercait que la construction du widget, jamais les crochets. On resout donc ici
les references de chaque decorateur.

Lancement :
    QT_QPA_PLATFORM=offscreen python tests/test_widgets_build.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qtpy.QtWidgets import QApplication  # noqa: E402


def check_conf_defaults(plugin_class):
    """Refuse une section de configuration VIDE.

    ⚠ Un greffon declare avec CONF_DEFAULTS = [(section, {})] fait echouer le chargement
    de la configuration de Spyder au demarrage : "Une erreur s'est produite lors du
    chargement des options de configuration de Spyder. Vous devez les reinitialiser."
    Et le seul bouton propose efface TOUTE la configuration de l'utilisateur, disposition
    des panneaux comprise. Constate en direct le 20/07/2026, apres la suppression des
    options du greffon en meme temps que ses boutons - CONF.register_plugin() seul ne le
    detecte pas, d'ou ce controle explicite.
    """
    defaults = plugin_class.CONF_DEFAULTS
    assert defaults, f"{plugin_class.NAME} : CONF_DEFAULTS vide"
    for section, options in defaults:
        assert options, (
            f"{plugin_class.NAME} : la section {section!r} n'a AUCUNE option. "
            "Spyder refusera de charger sa configuration au demarrage.")
    # La version doit etre un numero semantique lisible par Spyder.
    parts = plugin_class.CONF_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), \
        f"{plugin_class.NAME} : CONF_VERSION={plugin_class.CONF_VERSION!r} invalide"


def build(plugin_class):
    """Reproduit la sequence de construction de Spyder pour un greffon dockable."""
    from spyder.config.manager import CONF

    CONF.register_plugin(plugin_class)

    # Le widget herite normalement CONF_SECTION du greffon pendant son __init__
    # (SpyderWidgetMixin). Ici il n'y a pas de greffon reel : on passe par une
    # sous-classe pour que l'attribut soit deja en place a la construction.
    harness_class = type(
        f"Test{plugin_class.WIDGET_CLASS.__name__}",
        (plugin_class.WIDGET_CLASS,),
        {"CONF_SECTION": plugin_class.CONF_SECTION,
         "PLUGIN_NAME": plugin_class.NAME},
    )
    widget = harness_class(name=plugin_class.NAME, plugin=None, parent=None)
    widget._setup()
    widget.setup()
    widget.update_actions()
    # render_toolbars() fait partie de la sequence : SpyderDockablePlugin.__init__ l'appelle
    # apres setup(). L'omettre ici masquait un vrai defaut - cf. l'assertion sur les barres
    # d'outils dans main(), et le commentaire de PyxelPaneWidget.render_toolbars().
    widget.render_toolbars()
    return widget


def check_plugin_hooks(plugin_class):
    """Resout ce que les crochets `on_plugin_*` referencent, sans les executer.

    On ne peut pas appeler ces methodes sans un Spyder complet, mais on peut verifier
    que les plugins qu'elles surveillent sont bien declares - la condition que Spyder
    verifie lui-meme, et dont le non-respect leve une SpyderAPIError avalee au demarrage.
    """
    declared = set(plugin_class.REQUIRES) | set(plugin_class.OPTIONAL)
    watched = set()
    for name in dir(plugin_class):
        method = getattr(plugin_class, name, None)
        for attribute in ("_plugin_listen", "_plugin_teardown"):
            value = getattr(method, attribute, None)
            if isinstance(value, str):
                watched.add(value)
    missing = watched - declared
    assert not missing, (
        f"{plugin_class.NAME} surveille {sorted(missing)} sans le declarer dans "
        f"REQUIRES/OPTIONAL - Spyder leverait une SpyderAPIError")
    return watched


def test_raise_and_focus_redonne_le_clavier(widget, plugin_class):
    """Apres "agrandir ce panneau" (layout.plugin.maximize_dockwidget), le clavier
    doit suivre - signale par l'utilisateur le 31/07/2026 : "après agrandissement du
    panneau, le jeu ne répond plus aux touches".

    maximize_dockwidget() reparente le widget (setCentralWidget) puis appelle
    change_visibility(True) SANS force_focus explicite : PluginMainWidget ne redonne
    alors le clavier a get_focus_widget() que si RAISE_AND_FOCUS est vrai sur le widget -
    exactement ce que PyxelPanePlugin doit desormais propager (cf. plugin_base.py).
    Reproduit ici le VRAI appel de change_visibility(True), pas une lecture d'attribut :
    un dockwidget est necessaire (la methode rend tout de suite si absent).

    Prend un widget DEJA construit par `build()` dans la boucle de main() : reconstruire
    ici ferait echouer CONF.register_plugin() sur "already exists" (deja enregistre une
    premiere fois pour ce plugin_class).
    """
    from qtpy.QtCore import Qt as _Qt
    from qtpy.QtWidgets import QDockWidget, QMainWindow

    # Ce que SpyderDockablePlugin.create_widget() fait normalement (new_api.py) - le
    # harnais `build()` construit le WIDGET seul, sans passer par le greffon.
    widget.RAISE_AND_FOCUS = plugin_class.RAISE_AND_FOCUS

    main_win = QMainWindow()
    dock = QDockWidget()
    dock.setWidget(widget)
    main_win.addDockWidget(_Qt.RightDockWidgetArea, dock)
    widget.dockwidget = dock
    main_win.resize(400, 300)
    main_win.show()
    QApplication.instance().processEvents()

    cible = widget.get_focus_widget()
    widget.change_visibility(True)
    QApplication.instance().processEvents()

    assert QApplication.instance().focusWidget() is cible, (
        f"clavier sur {QApplication.instance().focusWidget()!r} apres "
        f"change_visibility(True), attendu l'ecran Pyxel {cible!r} : le jeu ne "
        f"repondrait plus au clavier apres 'agrandir ce panneau'")

    main_win.close()
    main_win.deleteLater()
    print("OK  RAISE_AND_FOCUS redonne le clavier a l'ecran apres change_visibility")


def main():
    app = QApplication.instance() or QApplication([])

    import qtpy

    from spyder_pyxel.bridge import protocol
    from spyder_pyxel.spyder.plugin import PyxelGame
    from spyder_pyxel.spyder.plugin_studio import PyxelStudio

    print(f"binding Qt : {qtpy.API_NAME}")

    kinds = {}
    for plugin_class in (PyxelGame, PyxelStudio):
        widget = build(plugin_class)

        title = widget.get_title()
        assert title, f"{plugin_class.NAME} : titre vide"

        # Aucun bouton : le panneau est un pur afficheur. Seules subsistent les actions
        # que PluginMainWidget cree lui-meme (ancrer, fermer, verrouiller...).
        own_actions = [name for name in widget.get_actions()
                       if name.startswith("pyxel")]
        assert not own_actions, f"boutons residuels : {own_actions}"

        # Les DEUX barres d'outils doivent etre masquees APRES render_toolbars() : la
        # principale (vide, elle volerait une bande de hauteur au jeu) et celle du coin
        # (le bouton "hamburger", dont le menu se reduit aux quatre actions de dock que
        # Spyder ajoute a tout le monde).
        # ⚠ Ce controle existe parce que le masquage a deja ete fait au mauvais endroit :
        # depuis setup(), il etait annule par render_toolbars(), QToolBar.addWidget()
        # remontrant le widget ajoute. Le bouton reapparaissait donc au demarrage reel,
        # alors que ce test passait. Verifier apres render_toolbars(), pas avant.
        # isHidden() et NON isVisible() : isVisible() est faux pour tout widget dont la
        # fenetre n'a jamais ete affichee - l'assertion passerait sans rien verifier. Un
        # isHidden() vrai, lui, veut bien dire "masque explicitement".
        assert widget.get_main_toolbar().isHidden(), (
            f"{plugin_class.NAME} : barre d'outils principale non masquee")
        assert widget._corner_toolbar.isHidden(), (
            f"{plugin_class.NAME} : barre du coin (bouton hamburger) non masquee")

        icon = plugin_class.get_icon()
        assert icon is not None and not icon.isNull()
        assert plugin_class.get_name() and plugin_class.get_description()

        watched = check_plugin_hooks(plugin_class)
        check_conf_defaults(plugin_class)

        kinds[plugin_class.NAME] = widget.KIND
        print(f"OK  {plugin_class.NAME}: titre={title!r}, aucun bouton, "
              f"marqueur={widget.KIND}, config OK, surveille={sorted(watched)}")

        test_raise_and_focus_redonne_le_clavier(widget, plugin_class)

        widget.deleteLater()

    # Les deux panneaux doivent filtrer sur des marqueurs DIFFERENTS : sinon chacun
    # afficherait les images de l'autre, jeu et editeur melanges.
    assert kinds["pyxel_game"] == protocol.KIND_GAME
    assert kinds["pyxel_studio"] == protocol.KIND_EDITOR
    assert kinds["pyxel_game"] != kinds["pyxel_studio"]
    print("OK  les deux panneaux filtrent sur des marqueurs distincts")

    # Les deux greffons doivent vivre dans des MODULES distincts : Spyder enregistre ses
    # dependances par nom de module et refuse les doublons, donc deux points d'entree
    # visant le meme module font echouer le second (constate en direct).
    assert PyxelGame.__module__ != PyxelStudio.__module__, (
        "les deux greffons partagent un module : le second ne se chargera pas")
    print(f"OK  modules distincts : {PyxelGame.__module__} / {PyxelStudio.__module__}")

    app.processEvents()
    print("\nLES DEUX PANNEAUX SE CONSTRUISENT CORRECTEMENT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
