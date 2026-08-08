# -*- coding: utf-8 -*-
"""
Le pont, cote Spyder : un canal partage par console, et la distribution des images.

Pourquoi un objet commun aux deux greffons
-------------------------------------------
Il y a deux panneaux (jeu et editeur de ressources) mais UN SEUL canal par console : le
crochet pose dans un noyau y installe un unique publieur. Si chaque greffon creait son
propre canal, le second serait ignore et son panneau resterait vide pour toujours.

Spyder ne fournit pas de mecanisme de partage entre greffons tiers (les dependances entre
greffons ne visent que les greffons internes). On passe donc par un simple objet unique de
module, que les deux panneaux vont chercher. C'est volontairement banal : ce n'est pas un
greffon, juste un endroit ou poser un etat partage.

Comment chaque panneau sait ce qui le concerne
-----------------------------------------------
Tout part de la console : rien, dans une image recue, ne dit a priori si elle vient d'un
jeu ou de l'editeur de ressources - qui est lui-meme un programme Pyxel. Le publieur
inscrit donc dans l'en-tete partage un marqueur (protocol.KIND_*), pose au moment du
pyxel.init() selon que le module pyxel.editor a ete importe ou non. Chaque panneau ne
retient que les images qui portent son marqueur.

Plusieurs consoles peuvent publier en meme temps - editer ses ressources dans l'une pendant
qu'un jeu tourne dans l'autre est un cas d'usage reel, et c'est meme la seule facon d'avoir
les deux panneaux actifs a la fois : un noyau donne n'execute qu'un programme Pyxel a la
fois, puisque pyxel.run() le bloque jusqu'a la fin.
"""

from qtpy.QtCore import QObject, QSocketNotifier, QTimer, Signal

from spyder_pyxel.bridge import protocol, reader

# Cadence de relecture des canaux.
#
# Le probleme n'est PAS la perte d'images : a 15 ms on relit deja plus vite qu'un jeu a 60
# images par seconde ne publie (16,7 ms), et la mesure confirme zero perte
# (tests/test_frame_pacing.py). Le probleme est la REGULARITE. Une image publiee juste
# apres une relecture attend jusqu'a une periode complete avant d'etre vue : le panneau
# les recoit donc de facon irreguliere, certaines restent affichees deux rafraichissements
# d'ecran et d'autres un seul, et un defilement continu saccade.
#
# Mesure a 15 ms : gigue (ecart type) de 4,6 ms a 60 fps et 6,0 ms a 30 fps, avec des
# ecarts allant jusqu'a 14 ms. A 4 ms, cf. le tableau du README.
#
# CE SONDAGE N'EST PLUS LE CHEMIN NORMAL : c'est un filet de securite. Le jeu previent
# desormais le panneau par un tube nomme des qu'une image est publiee, et Qt reveille
# l'interface exactement a cet instant (QSocketNotifier) - plus besoin de deviner.
# Le sondage ne sert que si le tube n'a pas pu etre cree (systeme de fichiers sans FIFO,
# console distante) ; il reste donc, mais lent, pour ne pas gaspiller de reveils.
POLL_INTERVAL_MS = 4

# Cadence du filet de securite quand le signalement fonctionne. Assez rare pour ne rien
# couter, assez frequent pour que le panneau reparte tout seul si un signal se perd.
FALLBACK_INTERVAL_MS = 250


class PyxelBridge(QObject):
    """Detient un canal par console et distribue les images aux panneaux."""

    sig_frame = Signal(int, object, object)
    """(marqueur, image, canal) - un panneau ne garde que son propre marqueur.

    ⚠ LE CANAL FAIT PARTIE DU SIGNAL, et ce n'est pas un detail : plusieurs programmes du
    MEME genre peuvent tourner en meme temps, un par console. Deux editeurs de ressources
    ouverts sur deux fichiers publient tous deux avec KIND_EDITOR. Tant que le panneau ne
    recevait que (marqueur, image), il les peignait tous les deux sur le meme ecran et
    l'affichage CLIGNOTAIT entre les deux fichiers - constate par l'utilisateur le
    21/07/2026. C'est le canal, et lui seul, qui identifie un programme.
    """

    sig_publisher_gone = Signal(int, object)
    """(marqueur, canal) - ce canal-la ne publie plus. Son onglet peut disparaitre."""

    sig_console_hooked = Signal(object)
    """(shellwidget) - le crochet vient d'etre pose dans ce noyau.

    Rien d'autre ne le dit : le crochet est installe par un execute SILENCIEUX, et
    `silent_execute` ne rend rien. Or lancer l'editeur de ressources AVANT que le crochet
    soit en place lui ferait ouvrir sa propre fenetre au lieu du panneau. C'est le meme
    piege que celui documente dans attach_console, vu du cote de celui qui attend.
    """

    sig_debug_waiting = Signal(int, bool)
    """(marqueur, le debogueur attend une commande).

    Emis quand la console qui fait tourner ce jeu entre dans une invite `ipdb>` ou en
    ressort. Le panneau s'en sert pour ne PAS voler le clavier a ce moment-la : sans quoi
    les `n`, `s`, `c` du debogueur partiraient dans le jeu (cf. panes.py).
    """

    def __init__(self):
        super().__init__()
        self._channels = {}          # shellwidget -> PyxelChannel
        self._shellwidgets = {}      # PyxelChannel -> shellwidget
        self._active = {}            # marqueur -> canal qui publie
        self._hooked = set()         # shellwidgets ou le crochet est pose
        self._pdb_handlers = {}      # shellwidget -> slot connecte
        self._debug_waiting = {}     # PyxelChannel -> bool
        self._titles = {}            # PyxelChannel -> intitule d'onglet
        self._documents = {}         # PyxelChannel -> chemin complet edite
        self._announced_gone = set()  # canaux dont la fin a deja ete annoncee
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._notifiers = {}
        self._subscribers = 0

    # --- Consoles ------------------------------------------------------------

    def attach_console(self, shellwidget):
        """Cree un canal pour cette console et y installe le crochet. Idempotent."""
        if shellwidget in self._channels:
            return
        channel = reader.PyxelChannel()
        try:
            name = channel.create()
        except Exception:
            return
        self._channels[shellwidget] = channel
        self._shellwidgets[channel] = shellwidget

        # Etat du debogueur de cette console. `sig_pdb_state_changed` porte True quand
        # l'invite `ipdb>` s'affiche (le noyau attend une commande) et False quand la
        # commande est soumise (l'execution repart) - exactement les deux instants ou le
        # clavier doit changer de main. Le signal n'existe que sur une console Spyder :
        # un shellwidget de test ne l'a pas, et son absence doit rester sans consequence.
        signal = getattr(shellwidget, "sig_pdb_state_changed", None)
        if signal is not None:
            def on_pdb_state(waiting, ch=channel):
                self._on_pdb_state(ch, waiting)

            try:
                signal.connect(on_pdb_state)
                self._pdb_handlers[shellwidget] = on_pdb_state
            except (TypeError, RuntimeError):
                pass

        # Reveil sur signalement plutot que sondage : le panneau apprend l'existence
        # d'une image au moment ou elle est publiee, et non au prochain tic d'horloge.
        fd = channel.notify_fd
        if fd is not None:
            notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
            notifier.activated.connect(
                lambda *_args, ch=channel: self._on_notified(ch))
            notifier.setEnabled(True)
            self._notifiers[channel] = notifier

        # ⚠ COUP D'ESSAI IMMEDIAT, EN PLUS DU RESTE CI-DESSOUS - JAMAIS A LA PLACE.
        # Defaut signale par l'utilisateur le 31/07/2026 : sur une console TOUTE NEUVE,
        # creee par Spyder au moment meme d'un F5 ("executer dans une console dediee"),
        # Spyder connecte SA PROPRE execution (`_run`, dans IPythonConsoleWidget.
        # run_script) a `sig_prompt_ready` de facon SYNCHRONE, DANS run_script() -
        # donc AVANT que `sig_shellwidget_created` (et par la, cette methode) n'ait la
        # moindre chance de s'executer : cette derniere ne part que du callback
        # ASYNCHRONE qui connecte reellement le noyau (shell.py, connect_kernel), lance
        # bien apres que run_script() a deja pose sa propre connexion. Notre propre
        # connexion a sig_prompt_ready, plus bas, arrive donc STRUCTURELLEMENT apres
        # celle de Spyder pour ce cas precis, et perd la course A CHAQUE FOIS - d'ou "il
        # faut un deuxieme demarrage" (le second run reutilise la meme console, deja
        # crochetee entre-temps par le premier invite).
        # Or `self.kernel_client` (shell.py) est deja pose AVANT l'emission de
        # sig_shellwidget_created, dans connect_kernel() : contrairement a ce qu'affirme
        # le commentaire plus bas - vrai pour un evenement plus precoce, pas pour
        # celui-ci - `silent_execute` a donc de bonnes chances de fonctionner ICI.
        # Idempotent des deux cotes (kernel.install(), et cet essai ne touche pas
        # `_hooked`/`sig_console_hooked` : la suite reste l'unique source de verite) :
        # ce coup d'essai ne peut donc rien casser s'il echoue ou fait double emploi.
        try:
            shellwidget.silent_execute(reader.kernel_bootstrap_code(name))
        except Exception:
            pass

        # ⚠ sig_shellwidget_created se declenche a la CREATION DU WIDGET, bien avant que
        # le noyau soit connecte. Injecter le crochet a ce moment-la ne fait rien du tout,
        # et sans le moindre message : silent_execute avale l'AttributeError levee quand
        # kernel_client n'existe pas encore (spyder/plugins/ipythonconsole/widgets/
        # shell.py, silent_execute). C'etait la cause du "l'ecran reste noir" - le jeu
        # tournait, mais rien ne le detournait vers le panneau.
        # On attend donc, pour l'etat OFFICIEL (_hooked/sig_console_hooked), que le
        # noyau soit pret - le coup d'essai ci-dessus n'en dispense pas.
        if getattr(shellwidget, "spyder_kernel_ready", False):
            self._inject(shellwidget, name)
        else:
            shellwidget.sig_kernel_is_ready.connect(
                lambda sw=shellwidget, n=name: self._inject(sw, n))

        # ⚠ ET AUSSI SUR LE PREMIER INVITE, sans quoi le jeu s'ouvre PARFOIS dans sa
        # propre fenetre (signale par l'utilisateur le 26/07/2026 : "le jeu ne se lance
        # pas systematiquement dans le panneau, mais parfois dans sa propre fenetre").
        #
        # LA COURSE. Deux evenements sans ordre garanti entre eux arrivent a la creation
        # d'une console : la poignee de main du noyau Spyder, qui emet
        # `sig_kernel_is_ready` (shell.py, handle_kernel_is_ready), et l'affichage du
        # premier invite, qui emet `sig_prompt_ready` (_prompt_started_hook). Ils viennent
        # de deux messages differents du noyau ; RIEN dans Spyder ne les ordonne.
        # Or lancer un fichier dans une console pas encore prete (console dediee, ou F5
        # juste apres le demarrage) attend, LUI, `sig_prompt_ready` : si l'invite gagne la
        # course, `runfile` part AVANT notre amorcage. Le jeu importe alors pyxel sans
        # crochet, ouvre sa fenetre, et sa boucle occupe le noyau pour toujours - notre
        # amorcage, mis en file derriere, ne s'executera jamais.
        #
        # POURQUOI CETTE CONNEXION-CI PASSE DEVANT. Qt appelle les slots dans l'ordre ou
        # ils ont ete connectes. Le notre l'est a la CREATION de la console ; celui de
        # Spyder ne l'est qu'au moment ou l'utilisateur demande l'execution, donc plus
        # tard. Sur ce signal, nous sommes toujours servis en premier, et notre execution
        # silencieuse entre dans la file du noyau avant `runfile`.
        prompt = getattr(shellwidget, "sig_prompt_ready", None)
        if prompt is not None:
            try:
                prompt.connect(
                    lambda sw=shellwidget, n=name: self._inject_if_needed(sw, n))
            except (TypeError, RuntimeError):
                pass

    # --- Sous-processus externes (profileur) ----------------------------------

    def attach_process(self, key):
        """Cree un canal pour un sous-processus externe, sans crochet cote noyau.

        A la difference d'attach_console, rien ici n'installe le crochet : il n'y a pas de
        noyau IPython a atteindre par silent_execute. C'est le sous-processus LUI-MEME qui
        le posera, via spyder_pyxel.bridge.kernel.install(nom) - a lui communiquer (ligne de
        commande) AVANT de le demarrer. Sert au profileur (spyder_line_profiler_targets, qui
        lance le script dans un QProcess independant via lp_launcher.py, hors de toute
        console) mais n'a rien de specifique a lui : `key` est juste une cle stable pour la
        duree de vie du canal, exactement comme un shellwidget pour attach_console -
        n'importe quel objet convient (le widget appelant, par exemple).

        Renvoie le nom du segment a transmettre au sous-processus, ou None si la creation a
        echoue ou qu'un canal existe deja pour cette cle.
        """
        if key in self._channels:
            return None
        channel = reader.PyxelChannel()
        try:
            name = channel.create()
        except Exception:
            return None
        self._channels[key] = channel
        self._shellwidgets[channel] = key

        fd = channel.notify_fd
        if fd is not None:
            notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
            notifier.activated.connect(
                lambda *_args, ch=channel: self._on_notified(ch))
            notifier.setEnabled(True)
            self._notifiers[channel] = notifier

        return name

    def _inject_if_needed(self, shellwidget, shm_name):
        """Amorcage sur le premier invite, et sur lui seul.

        `sig_prompt_ready` est emis a CHAQUE invite, donc apres chaque commande de
        l'utilisateur : sans ce garde, on enverrait une execution silencieuse a chaque
        ligne tapee. Le redemarrage du noyau, lui, reste couvert par
        `sig_kernel_is_ready`, qui repasse par `_inject` sans garde - un noyau neuf n'a
        plus le crochet, il faut le reposer.
        """
        if shellwidget in self._hooked:
            return
        self._inject(shellwidget, shm_name)

    def _inject(self, shellwidget, shm_name):
        """Installe le crochet dans un noyau desormais pret."""
        if shellwidget not in self._channels:
            return  # console fermee entre-temps
        # Execute sans que ca apparaisse dans la console : l'utilisateur n'a pas a voir la
        # tuyauterie du greffon dans son historique.
        shellwidget.silent_execute(reader.kernel_bootstrap_code(shm_name))
        self._hooked.add(shellwidget)
        self.sig_console_hooked.emit(shellwidget)

    def _on_notified(self, channel):
        """Le jeu vient de publier : on lit tout de suite."""
        channel.drain_notifications()
        self._deliver(channel)

    # --- Debogueur -----------------------------------------------------------

    def _on_pdb_state(self, channel, waiting):
        """La console de ce canal vient d'entrer dans une invite pdb, ou d'en sortir."""
        waiting = bool(waiting)
        if self._debug_waiting.get(channel) == waiting:
            return
        self._debug_waiting[channel] = waiting
        try:
            kind = channel.kind()
        except Exception:
            # Canal deja libere : plus personne a prevenir.
            return
        self.sig_debug_waiting.emit(kind, waiting)

    def shellwidget_for(self, channel):
        """La console qui publie sur ce canal, ou None. Sert a l'arreter."""
        return self._shellwidgets.get(channel)

    def channels(self):
        """Les consoles suivies. Sert a savoir si une console existe encore."""
        return dict(self._channels)

    def set_title(self, shellwidget, title, document=None):
        """Donne un intitule au canal de cette console, et le fichier qu'il edite.

        Pose par le greffon au lancement, lui seul sachant quel fichier il ouvre. Le pont
        ne fait que le transporter jusqu'au panneau.

        `title` est court (nom de fichier) et sert d'intitule d'ONGLET ; `document` est le
        chemin COMPLET et sert au titre de la FENETRE, comme Spyder le fait deja pour les
        fichiers ouverts dans son editeur (Commun/scripts_installation/spyder_patch/patch_spyder_window_title.py).
        """
        channel = self._channels.get(shellwidget)
        if channel is not None:
            self._titles[channel] = title
            if document is not None:
                self._documents[channel] = document

    def title(self, channel):
        """L'intitule de ce canal, ou None si personne ne lui en a donne."""
        return self._titles.get(channel)

    def document(self, channel):
        """Le chemin complet du fichier edite sur ce canal, ou None."""
        return self._documents.get(channel)

    def is_hooked(self, shellwidget):
        """Le crochet est-il deja pose dans ce noyau ?"""
        return shellwidget in self._hooked

    def is_busy_with_pyxel(self, shellwidget):
        """Un programme Pyxel occupe-t-il deja ce noyau ?

        ⚠ Un noyau n'en execute qu'UN a la fois : pyxel.run() bloque jusqu'a la fin.
        Envoyer l'editeur de ressources dans une console ou un jeu tourne ne ferait donc
        rien du tout - la ligne resterait en attente derriere la boucle du jeu, sans le
        moindre message.
        """
        channel = self._channels.get(shellwidget)
        if channel is None:
            return False
        try:
            return channel.state() == protocol.STATE_RUNNING
        except Exception:
            return False

    def is_debug_waiting(self, kind):
        """Le jeu de ce marqueur est-il arrete sur une invite du debogueur ?"""
        channel = self._active.get(kind)
        if channel is None:
            return False
        return self._debug_waiting.get(channel, False)

    def console_control_for_kind(self, kind):
        """Le widget de saisie de la console qui fait tourner ce jeu, ou None.

        Sert a RENDRE le clavier a la console quand le debogueur s'arrete. Le rendre
        explicitement, et non simplement le retirer au panneau : un clearFocus() seul
        laisse le clavier a la fenetre principale, ou taper `n` ne fait rien.
        """
        channel = self._active.get(kind)
        shellwidget = self._shellwidgets.get(channel)
        if shellwidget is None:
            return None
        return getattr(shellwidget, "_control", None)

    def detach_console(self, shellwidget):
        """Libere le canal associe a `shellwidget` (ou a toute cle posee par attach_process :
        la structure est generique, rien ici n'est specifique a une console)."""
        channel = self._channels.pop(shellwidget, None)
        notifier = self._notifiers.pop(channel, None)
        if notifier is not None:
            notifier.setEnabled(False)
            notifier.deleteLater()
        self._hooked.discard(shellwidget)
        handler = self._pdb_handlers.pop(shellwidget, None)
        if handler is not None:
            try:
                shellwidget.sig_pdb_state_changed.disconnect(handler)
            except (AttributeError, TypeError, RuntimeError):
                pass
        if channel is None:
            return
        self._shellwidgets.pop(channel, None)
        self._debug_waiting.pop(channel, None)
        kind = protocol.KIND_GAME
        try:
            kind = channel.kind()
        except Exception:
            pass
        for active_kind, active in list(self._active.items()):
            if active is channel:
                del self._active[active_kind]
                kind = active_kind
        self._titles.pop(channel, None)
        self._documents.pop(channel, None)
        self._announced_gone.discard(channel)
        # Emis DANS TOUS LES CAS, meme si ce canal n'etait pas le dernier a publier : son
        # onglet doit disparaitre du panneau, qu'il ait ete au premier plan ou non.
        self.sig_publisher_gone.emit(kind, channel)
        channel.release()

    def release_all(self):
        for shellwidget in list(self._channels):
            self.detach_console(shellwidget)

    # --- Abonnement ----------------------------------------------------------

    def subscribe(self):
        """Un panneau devient visible : la relecture ne tourne que s'il y a un lecteur."""
        self._subscribers += 1
        if self._subscribers > 0 and not self._timer.isActive():
            self._timer.setInterval(self._timer_interval())
            self._timer.start()

    def unsubscribe(self):
        self._subscribers = max(0, self._subscribers - 1)
        if self._subscribers == 0:
            self._timer.stop()

    # --- Boucle de relecture --------------------------------------------------

    def _deliver(self, channel):
        """Lit l'image disponible sur ce canal et la distribue aux panneaux."""
        frame = channel.read_frame()
        if frame is None:
            return
        kind = channel.kind()
        self._announced_gone.discard(channel)
        # `_active` reste le DERNIER canal a avoir publie pour ce marqueur. Il ne sert plus
        # a choisir ou peindre - c'est le canal transmis avec l'image qui le dit - mais
        # uniquement de repli quand personne ne demande un canal precis.
        self._active[kind] = channel
        self.sig_frame.emit(kind, frame, channel)

    def _poll(self):
        for channel in list(self._channels.values()):
            self._deliver(channel)
            self._check_still_alive(channel)

    def _check_still_alive(self, channel):
        """Un programme qui a publie puis disparu doit vider son panneau.

        ⚠ Pyxel COUPE LE PROCESSUS quand un jeu se termine : rien ne previent, et la
        derniere image resterait figee pour toujours. On surveille donc le PID inscrit
        dans l'en-tete. Le controle vit dans la boucle de repli (250 ms quand le
        signalement fonctionne), ce qui suffit largement : personne ne remarque un quart
        de seconde a la fin d'un jeu.

        `_announced_gone` evite de reannoncer la meme fin a chaque tour. Il est remis a
        zero des qu'une nouvelle image arrive, pour qu'un jeu relance dans la MEME console
        retrouve son panneau (la console redemarre son noyau, mais le canal, lui, survit).
        """
        if channel not in self._announced_gone:
            try:
                published = channel.state() == protocol.STATE_RUNNING
            except Exception:
                return
            if published and not channel.publisher_alive():
                self._announced_gone.add(channel)
                try:
                    kind = channel.kind()
                except Exception:
                    kind = protocol.KIND_GAME
                self.sig_publisher_gone.emit(kind, channel)

    def _timer_interval(self):
        """Lent si tous les canaux savent signaler, rapide sinon.

        Un canal sans tube (creation impossible) impose de revenir au sondage serre pour
        lui ; on ne peut pas melanger deux cadences sur une seule minuterie, donc c'est la
        plus contraignante qui gagne.
        """
        if self._channels and all(
                channel.notify_fd is not None for channel in self._channels.values()):
            return FALLBACK_INTERVAL_MS
        return POLL_INTERVAL_MS


_bridge = None


def get_bridge():
    """L'unique pont de la session Spyder."""
    global _bridge
    if _bridge is None:
        _bridge = PyxelBridge()
    return _bridge
