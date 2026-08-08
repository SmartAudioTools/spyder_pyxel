# -*- coding: utf-8 -*-
"""Le greffon du panneau "Pyxel Studio" : l'editeur de ressources de Pyxel.

⚠ POURQUOI CE FICHIER EXISTE, alors que les deux greffons tiendraient dans plugin.py :
Spyder identifie chaque greffon externe par le NOM DE MODULE de son point d'entree, pas
par son NAME. spyder/app/find_plugins.py pose
`plugin_class._spyder_module_name = entry_point.module`, que
plugin_registration/registry.py passe a dependencies.add() - lequel REFUSE tout doublon
("ValueError: Dependency has already been registered"). Deux points d'entree visant le
meme module font donc echouer l'enregistrement du second (constate le 20/07/2026 :
"pyxel_studio" ne se chargeait pas). La logique commune est dans plugin_base.py, importee
et non pointee par un point d'entree.
"""

import os

import qtawesome as qta

from spyder.api.plugins import Plugins
from spyder.utils.icon_manager import ima

from spyder_pyxel.spyder.bridge_manager import get_bridge
from spyder_pyxel.spyder.config import (
    CONF_VERSION, STUDIO_CONF_DEFAULTS, STUDIO_CONF_SECTION)
from spyder_pyxel.spyder.plugin_base import PyxelPanePlugin
from spyder_pyxel.spyder.translations import _
from spyder_pyxel.spyder.widgets.panes import PyxelStudioWidget

#: Nom donne a la console dediee. Reconnaissable dans l'onglet, et c'est ce qui permet
#: de la retrouver pour la reutiliser plutot que d'en empiler une par fichier ouvert.
STUDIO_CONSOLE_NAME = "Pyxel Studio"


def editor_command(path, editor_kind="image"):
    """La ligne a executer dans la console pour ouvrir ce fichier de ressources.

    Isolee de toute dependance a Spyder pour rester testable seule : c'est la seule
    chose que l'utilisateur avait a taper a la main jusqu'ici.
    """
    return (f"import pyxel.editor; "
            f"pyxel.editor.App({str(path)!r}, {editor_kind!r})")


class PyxelStudio(PyxelPanePlugin):
    """Panneau affichant l'editeur de ressources de Pyxel."""

    NAME = "pyxel_studio"  # doit etre identique au nom du point d'entree
    # Le greffon du repertoire de travail sert au dialogue "nouveau fichier" : il
    # propose le dossier courant de Spyder. Optionnel — sans lui on retombe sur os.getcwd.
    OPTIONAL = [Plugins.WorkingDirectory]
    WIDGET_CLASS = PyxelStudioWidget
    CONF_SECTION = STUDIO_CONF_SECTION
    CONF_DEFAULTS = STUDIO_CONF_DEFAULTS
    CONF_VERSION = CONF_VERSION

    FILE_EXTENSIONS = [".pyxres"]
    """Ouvrir un .pyxres l'envoie ici, et non dans l'editeur de texte.

    C'est un point d'extension prevu par Spyder, et non un detournement :
    Application.open_file_in_plugin parcourt les greffons, retient le premier dont
    FILE_EXTENSIONS contient l'extension, appelle son switch_to_plugin() puis son
    open_file(). Tout y converge - double-clic dans le panneau Fichiers ou dans un
    projet, menu Fichier > Ouvrir, et fichier passe en ligne de commande (donc depuis
    Dolphin). Il n'y a rien a intercepter nous-memes.

    Sans cela, un .pyxres s'ouvrait dans l'editeur de texte, qui affichait du binaire.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Console dediee a l'editeur, creee a la demande et reutilisee ensuite.
        self._studio_shellwidget = None
        # Fichier a ouvrir des que le crochet sera pose dans cette console.
        self._pending = None

    # --- Ouverture d'un fichier de ressources --------------------------------

    def on_initialize(self):
        """Branche le « + » du panneau : lui demande, nous ouvrons."""
        super().on_initialize()
        self.get_widget().sig_nouveau_fichier.connect(self.nouveau_fichier)
        self.get_widget().sig_fermer_editeur.connect(self.arreter_editeur)

    def arreter_editeur(self, canal):
        """Arrete l'editeur qui publie sur ce canal, en interrompant SA console.

        C'est ce qui manquait pour que fermer un onglet ferme vraiment le fichier :
        l'editeur continuait de publier et son onglet reapparaissait a l'image suivante.

        On interrompt la console PRECISE qui le fait tourner, pas « la console courante » :
        l'utilisateur peut en regarder une autre. Et seulement si elle execute quelque
        chose — interrompre un noyau au repos ecrit une KeyboardInterrupt pour rien et fait
        remonter la Console IPython au premier plan.
        """
        shellwidget = get_bridge().shellwidget_for(canal)
        if shellwidget is None:
            return
        try:
            if shellwidget.is_running():
                shellwidget.interrupt_kernel()
        except AttributeError:
            # API de Spyder differente : mieux vaut ne rien faire que planter le panneau.
            pass

    def nouveau_fichier(self):
        """Demande un nom de fichier .pyxres et l'ouvre dans l'editeur.

        Le fichier n'a pas besoin d'exister : l'editeur de Pyxel le CREE au premier
        enregistrement, et c'est meme la maniere normale d'en fabriquer un (cf. le
        message d'accueil du panneau). On ne cree donc rien nous-memes — pas de fichier
        vide a moitie forme si l'utilisateur renonce.

        Le dossier propose est le REPERTOIRE COURANT de Spyder, comme pour le terminal :
        c'est la que l'utilisateur travaille.
        """
        import os

        from qtpy.QtWidgets import QFileDialog

        depart = os.getcwd()
        travail = self.get_plugin(Plugins.WorkingDirectory, error=False)
        if travail is not None:
            try:
                chemin = travail.get_workdir()
            except AttributeError:
                chemin = None
            if chemin and os.path.isdir(chemin):
                depart = chemin

        nom, _filtre = QFileDialog.getSaveFileName(
            self.get_widget(), _("Nouveau fichier de ressources Pyxel"),
            os.path.join(depart, "ressources.pyxres"),
            _("Ressources Pyxel (*.pyxres)"),
            options=QFileDialog.DontConfirmOverwrite)
        if not nom:
            return
        if not nom.endswith(".pyxres"):
            nom += ".pyxres"
        self.open_file(nom)

    def open_file(self, filename):
        """Ouvre ce .pyxres dans l'editeur de ressources, sans rien taper.

        ⚠ POURQUOI UNE CONSOLE DEDIEE, ET NON LA CONSOLE COURANTE
        pyxel.run() BLOQUE le noyau jusqu'a la fin, et Pyxel COUPE LE PROCESSUS en
        sortant (cf. README) : fermer l'editeur redemarre donc la console. Lancer
        l'editeur dans la console de travail de l'utilisateur la lui confisquerait tant
        que l'editeur est ouvert, puis lui ferait perdre toutes ses variables a la
        fermeture. La console dediee cantonne les deux effets.

        Elle est REUTILISEE tant qu'aucun programme Pyxel n'y tourne, pour ne pas empiler
        une console par fichier ouvert.
        """
        console = self.get_plugin(Plugins.IPythonConsole, error=False)
        if console is None:
            return
        bridge = get_bridge()

        shellwidget = self._studio_shellwidget
        reutilisable = (
            shellwidget is not None
            and shellwidget in bridge.channels()
            and not bridge.is_busy_with_pyxel(shellwidget)
        )
        if reutilisable:
            self._run_when_hooked(shellwidget, filename)
            return

        # Nouvelle console : on ne recupere pas son shellwidget en retour
        # (create_new_client ne rend rien), on l'attend par le signal du pont.
        self._pending = filename
        self._studio_shellwidget = None
        bridge.sig_console_hooked.connect(self._on_console_hooked)
        console.create_new_client(give_focus=False,
                                  given_name=STUDIO_CONSOLE_NAME)

    def _on_console_hooked(self, shellwidget):
        """Le crochet vient d'etre pose : c'est le moment ou l'editeur peut demarrer."""
        if self._pending is None:
            return
        filename, self._pending = self._pending, None
        self._studio_shellwidget = shellwidget
        try:
            get_bridge().sig_console_hooked.disconnect(self._on_console_hooked)
        except (TypeError, RuntimeError):
            pass
        self._execute(shellwidget, filename)

    def _run_when_hooked(self, shellwidget, filename):
        bridge = get_bridge()
        if bridge.is_hooked(shellwidget):
            self._execute(shellwidget, filename)
        else:
            self._pending = filename
            bridge.sig_console_hooked.connect(self._on_console_hooked)

    def _execute(self, shellwidget, filename):
        """Envoie la commande, VISIBLE dans la console.

        Visible et non silencieuse, volontairement : c'est exactement la ligne que
        l'utilisateur tapait a la main, et la voir passer explique ce qui se produit -
        y compris quand ca echoue (fichier illisible, pyxel absent du noyau).
        """
        # Le nom de l'onglet, pose AVANT le lancement : la premiere image arrive vite, et
        # l'onglet doit deja porter son nom quand elle arrive. Seul le greffon sait quel
        # fichier il ouvre - le pont ne fait que transporter l'intitule jusqu'au panneau.
        get_bridge().set_title(shellwidget, os.path.basename(str(filename)),
                               document=str(filename))
        shellwidget.execute(editor_command(filename))
        self.switch_to_plugin()

    @staticmethod
    def get_name():
        return _("Pyxel Studio")

    @staticmethod
    def get_description():
        return _("Editeur d'images, de tuiles, de sons et de musiques de Pyxel.")

    @classmethod
    def get_icon(cls):
        return qta.icon("mdi.palette", color=ima.MAIN_FG_COLOR)
