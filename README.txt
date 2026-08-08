PLUGIN SPYDER "PYXEL" - le jeu s'execute normalement, seule son image va dans un panneau
==========================================================================================

Ce que ca ajoute
----------------
Deux panneaux dans Spyder, sans AUCUN bouton, qui n'executent rien :

  "Pyxel"         affiche l'ecran du jeu Pyxel lance depuis la console.
  "Pyxel Studio"  affiche l'ecran de l'editeur de ressources de Pyxel.

Menu Fenetre > Panneaux > Pyxel / Pyxel Studio. (En Spyder 6.1 le menu "View" a ete
fusionne dans "Window" - donc "Fenetre" en francais, et non "Affichage". Avec le patch
burger de ce depot, le menu est sous le bouton burger.) Les greffons tiers sont ajoutes EN
FIN de ce menu : les deux panneaux Pyxel se trouvent apres "Console interne".


Comment s'en servir
-------------------
1. Ouvrir un script Pyxel dans l'editeur. Un exemple est fourni : exemples/demo_pyxel.py
2. **F5**, comme n'importe quel script. Le jeu s'execute dans la console : ses `print`
   s'y affichent, les points d'arret fonctionnent, l'explorateur de variables voit ses
   variables. Seule sa FENETRE est remplacee par le panneau.
3. Le panneau prend le clavier TOUT SEUL au demarrage du jeu : il n'y a rien a cliquer.
   Si on l'a perdu (clic dans l'editeur), un clic dans l'ecran le redonne. Toutes les
   touches encore enfoncees sont relachees des qu'on clique ailleurs, sinon le personnage
   continuerait de courir.

Pour l'editeur de ressources : OUVRIR le fichier .pyxres suffit - double-clic dans le
panneau Fichiers ou dans un projet, menu Fichier > Ouvrir, ou depuis Dolphin. Il s'ouvre
dans le panneau "Pyxel Studio", dans une console dediee nommee "Pyxel Studio".

La commande equivalente reste utilisable, et c'est exactement celle que le greffon envoie :

    import pyxel.editor
    pyxel.editor.App("mes_ressources.pyxres", "image")

Le fichier peut ne pas exister encore : c'est ainsi qu'on en cree un - mais il faut alors
passer par la commande, puisqu'on ne peut pas "ouvrir" un fichier absent.


Pourquoi aucun bouton
---------------------
Une version precedente en avait neuf (executer, arreter, relancer, relancer a
l'enregistrement, afficher la sortie, ouvrir une ressource, recharger, fermer...). Aucun
ne rendait un service propre au jeu : ils reimplementaient tous, en double et en moins
bien, ce que la console fait deja - lancer, arreter, relancer, afficher la sortie. Ils
n'existaient que parce que le panneau possedait un sous-processus que Spyder ne
connaissait pas. Des que le jeu tourne dans le noyau de la console, ils perdent tous leur
raison d'etre.

Le seul confort reellement perdu : "relancer a chaque enregistrement" demande maintenant
deux gestes (Ctrl+S puis F5) au lieu d'un.


Comment ca marche
-----------------
Le jeu ne tourne pas dans le processus de Spyder, et sa fenetre n'est pas "encastree" dans
le panneau.

L'approche naturelle aurait ete de retrouver la fenetre SDL du jeu et de la reparenter
dans un widget Qt (XEmbed / QWindow.fromWinId). Elle ne fonctionne que sous X11. Or la
session KDE de cette machine est Wayland, et sous Wayland un client ne peut pas reparenter
la surface d'un autre client : c'est un choix de conception du protocole, pas une lacune
temporaire.

Le greffon ne transporte donc pas une fenetre, mais des pixels :

  - a la creation de chaque console, Spyder y execute silencieusement une ligne qui
    installe un crochet (spyder_pyxel/bridge/kernel.py) ;
  - quand un programme Pyxel demarre dans cette console, le crochet lui impose le rendu
    hors ecran (SDL_VIDEODRIVER=offscreen) et intercepte ses fins d'image ;
  - a chaque image, l'ecran (pyxel.screen.data_ptr(), un octet d'indice de palette par
    pixel) et la palette sont recopies dans une memoire partagee ;
  - le panneau Qt lit cette memoire a son rythme et redessine lui-meme ;
  - en retour, il depose touches et souris dans un anneau situe dans la MEME memoire
    partagee, que le jeu consomme a chaque image via pyxel.set_btn() / set_mouse_pos() /
    set_input_text().

Le noyau IPython etant deja un processus separe de l'interface de Spyder, la memoire
partagee tombe juste : il n'y a rien a lancer nous-memes.

Il n'y a AUCUNE contrainte sur l'ordre des imports : SDL choisit son pilote video a
SDL_Init, appele par pyxel.init(), et non a l'import du module (verifie en direct).


Pieges rencontres, et pourquoi le code en tient compte
-------------------------------------------------------
pyxel.init() CHANGE LE REPERTOIRE COURANT
    Un jeu qui fait load("ressources.pyxres") juste apres init() echoue avec
    "Failed to open file", alors que le fichier est bien a cote du script et que le
    repertoire courant etait correct AVANT l'init. Le crochet memorise donc le repertoire
    courant avant d'appeler init(), et resout les chemins relatifs de load()/save() par
    rapport a lui. Il ne corrige que le cas non ambigu (chemin relatif + fichier
    reellement present), pour ne jamais masquer une vraie erreur de chemin.

CONF_DEFAULTS NE DOIT JAMAIS ETRE VIDE
    Un greffon declare avec [(section, {})] fait echouer le chargement de la configuration
    de Spyder au demarrage, et le seul bouton propose efface TOUTE la configuration de
    l'utilisateur, disposition des panneaux comprise. tests/test_widgets_build.py le
    verifie desormais.

CHANGER UN DEFAUT NE SUFFIT PAS
    Spyder conserve les valeurs deja ecrites dans
    ~/.config/spyder-py3/plugins/<section>/spyder.ini. Modifier CONF_DEFAULTS sans monter
    CONF_VERSION laisse donc l'ancienne valeur active - constate avec integer_scaling.

DEUX POINTS D'ENTREE NE PEUVENT PAS VISER LE MEME MODULE
    Spyder enregistre ses dependances par nom de module et refuse les doublons : le second
    greffon ne se charge pas. D'ou plugin.py et plugin_studio.py separes.

MESURER SUR UNE CAPTURE D'ECRAN EST TROMPEUR
    L'affichage de cette machine est a l'echelle 1,3 : les pixels d'une capture ne sont pas
    ceux de Qt. Le widget sait journaliser sa geometrie reelle si le fichier temoin
    HGIGNORED/pyxel_debug existe (cf. _log_geometry dans screen.py).

    Trois pieges de MESURE se sont ajoutes le 21/07/2026, chacun ayant produit une
    conclusion fausse - "cette chose n'existe pas" - la ou la chose existait. Les recits
    detailles sont dans CachyOS - DONE.txt ; voici les regles reutilisables.

    1. UN ARC EST ANTIALIASE. Compter les pixels EXACTEMENT a la couleur de bordure fait
       conclure qu'aucun arc n'est dessine : ses teintes sont intermediaires. Compter les
       pixels PLUS PROCHES de la bordure que du fond.
           d_bordure = somme(|c - bordure|) ; d_fond = somme(|c - fond|)
           c'est un pixel d'arc si d_bordure < d_fond
       Cout de l'erreur : une chasse a un "bug de Qt" inexistant, et une solution a base de
       QFrame conteneur ecrite pour rien.

    2. SAISIR LE WIDGET DONT ON UTILISE LES COORDONNEES. tabRect() est en coordonnees de la
       BARRE d'onglets, qui est decalee a l'interieur du QTabWidget. Sonder l'image du
       widget d'onglets avec ces coordonnees echantillonne a cote. Soit grab() la barre
       elle-meme, soit convertir : barre.mapTo(onglets, r.bottomLeft()).
       Cout : deux conclusions ecrites que le lisere de l'onglet actif n'existait pas,
       alors qu'il fonctionnait depuis toujours.

    3. LES PIXELS D'UNE IMAGE grab() SONT PHYSIQUES, PAS LOGIQUES. A l'echelle 1,3, une
       coordonnee logique doit etre multipliee par img.devicePixelRatio() avant d'indexer
       l'image. Sans cela on echantillonne a 77 % de la position visee.

    Et un piege qui n'est pas de mesure mais de METHODE, paye le meme jour : ne pas conclure
    "ce mecanisme n'existe pas dans Spyder" apres avoir cherche dans UN SEUL registre. Le
    cadre bleu au focus n'est dans AUCUNE feuille de style - aucun ":focus" sur un dock ou
    un onglet, et sig_focus_status_changed n'est consomme nulle part. Il est pose en code
    ordinaire, a deux endroits (widgets/emptymessage.py, widgets/browser.py), sous un nom
    qui ne contient meme pas le mot "focus" :
        def _apply_stylesheet(self, focus):
            border_color = COLOR_ACCENT_3 if focus else COLOR_BACKGROUND_4
    C'est cette convention que _apply_tabs_stylesheet reprend dans panes.py.


Ouvrir un .pyxres lance l'editeur, et dans SA PROPRE console
-------------------------------------------------------------
Spyder prevoit ce cas, il n'y a rien a detourner : Application.open_file_in_plugin
parcourt les greffons, retient le premier dont FILE_EXTENSIONS contient l'extension du
fichier, appelle son switch_to_plugin() puis son open_file(). PyxelStudio declare donc
FILE_EXTENSIONS = [".pyxres"] et implemente open_file(). Sans cela, un .pyxres s'ouvrait
dans l'editeur de texte, qui affichait du binaire.

⚠ MAIS LES TROIS CHEMINS D'OUVERTURE N'Y MENENT PAS TOUS. Verifie en direct le 21/07/2026,
apres avoir affirme a tort qu'ils convergeaient tous - le distributeur avait ete verifie,
pas ce qui l'atteint :

  Dolphin / ligne de commande   MARCHE. mainwindow.open_external_file delegue directement a
                                open_file_in_plugin, sans aucun filtre. C'est le chemin le
                                plus sur, et celui que l'association KDE emprunte
                                (installation_KDE_parametrage.sh definit le type MIME
                                application/x-pyxel-resource).

  Fichier > Ouvrir              MARCHE, mais le fichier est INVISIBLE tant qu'on ne bascule
                                pas le filtre sur "Tous les fichiers (*)". La liste des
                                filtres vient de spyder.config.utils.get_edit_filters(),
                                qui ne consulte PAS les FILE_EXTENSIONS des greffons.

  Panneau Fichiers (double-clic) NE MARCHE PAS. ExplorerTreeWidget.open() ne route vers le
                                distributeur que si encoding.is_text_file(fname) est vrai.
                                Un .pyxres est une archive zip, donc binaire : il part dans
                                open_outside_spyder(), c'est-a-dire xdg-open, hors de
                                Spyder. Avec l'association KDE en place, cela relance
                                Spyder par le premier chemin - ce qui fonctionne, mais par
                                un detour, et pas dans l'instance ouverte si le verrou est
                                perime (cf. plus bas).

⚠ POURQUOI UNE CONSOLE DEDIEE, ET NON LA CONSOLE COURANTE
pyxel.run() BLOQUE le noyau jusqu'a la fin, et Pyxel COUPE LE PROCESSUS en sortant (cf.
plus bas) : fermer l'editeur redemarre donc la console. Lancer l'editeur dans la console de
travail de l'utilisateur la lui confisquerait tant que l'editeur est ouvert, puis lui ferait
perdre toutes ses variables a la fermeture. La console dediee, nommee "Pyxel Studio",
cantonne les deux effets. Elle est REUTILISEE tant qu'aucun programme Pyxel n'y tourne,
pour ne pas empiler une console par fichier ouvert.

Et le lancement ATTEND que le crochet soit pose (sig_console_hooked) : demarrer l'editeur
avant lui ferait ouvrir sa propre fenetre au lieu du panneau, et le panneau resterait vide
sans le moindre message, puisque rien n'aurait echoue.


Un onglet par programme, et pourquoi le canal ne suffisait pas au marqueur
---------------------------------------------------------------------------
Plusieurs programmes du MEME genre peuvent tourner en meme temps, un par console : deux
editeurs de ressources ouverts sur deux fichiers publient tous deux avec KIND_EDITOR.

Tant que le pont n'emettait que (marqueur, image), le panneau les peignait sur un ecran
UNIQUE : l'affichage alternait entre les deux fichiers a chaque image. Constate par
l'utilisateur le 21/07/2026 - "il s'ouvre dans la meme fenetre et ca clignote". Le
marqueur dit a QUEL PANNEAU une image est destinee ; il ne dit pas DE QUEL PROGRAMME elle
vient. Seul le canal le dit.

sig_frame porte donc desormais (marqueur, image, CANAL), et chaque panneau tient un ecran
par canal, dans un onglet. sig_publisher_gone porte (marqueur, canal) et retire l'onglet
correspondant - emis meme si ce canal n'etait pas le dernier a publier, sinon l'onglet
d'un programme arrete en arriere-plan resterait indefiniment.

Trois consequences a ne pas manquer :

  - LES ENTREES SUIVENT L'ONGLET. Elles repartaient vers "le canal actif du marqueur",
    c'est-a-dire le dernier a avoir publie. Avec plusieurs onglets, les touches tapees
    dans l'un seraient parties dans le programme d'un autre. Chaque ecran emet donc son
    identite, et _send() remonte au canal de CET onglet.
  - IL RESTE TOUJOURS UN ONGLET, celui d'accueil : un QTabWidget vide n'afficherait rien,
    pas meme le message d'invite. Le dernier onglet redevient l'accueil au lieu de
    disparaitre.
  - LA BARRE D'ONGLETS N'APPARAIT PAS TOUJOURS (ALWAYS_SHOW_TABS). Vrai pour l'editeur :
    on y travaille sur des fichiers, voir le nom vaut la bande de hauteur. Faux pour les
    jeux : un jeu veut tous ses pixels, et un seul jeu n'a aucune ambiguite a lever. Des
    qu'il y en a deux, la barre apparait dans les deux cas - c'est justement quand il faut
    les distinguer.

L'intitule vient du greffon (bridge.set_title), seul a savoir quel fichier il ouvre ; le
pont ne fait que le transporter. Il est pose AVANT le lancement : la premiere image arrive
vite, et l'onglet doit deja porter son nom quand elle arrive.


Comment chaque panneau sait ce qui le concerne
-----------------------------------------------
Tout partant de la console, rien dans une image ne dit d'ou elle vient - et l'editeur de
ressources est lui-meme un programme Pyxel. Le crochet inscrit donc un marqueur dans
l'en-tete partage au moment du pyxel.init(), selon que le module pyxel.editor a ete
importe ou non. C'est ce marqueur, et non un bouton, qui aiguille l'image vers l'un ou
l'autre panneau (test : tests/test_editor_kind.py).

Un noyau donne n'execute qu'un programme Pyxel a la fois, puisque pyxel.run() le bloque.
Avoir les deux panneaux actifs simultanement suppose donc deux consoles - editer ses
ressources dans l'une pendant qu'un jeu tourne dans l'autre, ce qui fonctionne.


Ce qu'il faut savoir sur les limites de Pyxel
----------------------------------------------
Verifie en direct, et non contournable depuis Python : Pyxel COUPE LE PROCESSUS depuis son
coeur Rust, aussi bien a la fin normale d'un jeu (pyxel.quit()) que sur une erreur dans
update()/draw(). Aucune exception n'est propagee, aucun code apres pyxel.run() ne
s'execute.

Consequences, qui ne sont PAS dues au greffon (elles existent deja aujourd'hui, puisque
F5 execute deja le jeu dans le noyau) :

  - fermer un jeu redemarre la console ;
  - une erreur dans un jeu tue le noyau : pas de %debug post-mortem, les variables sont
    perdues ;
  - F5 deux fois de suite passe par un redemarrage de noyau.

Ce que le greffon apporte reellement : l'image dans un panneau plutot que dans une fenetre
flottante, et des points d'arret utilisables PENDANT que le jeu tourne.


Le mode debogage (Ctrl+F5), et le piege du clavier
---------------------------------------------------
Ctrl+F5 fonctionne comme F5 : le jeu s'affiche dans le panneau, a pleine cadence, et un
point d'arret pose DANS `update()` ou `draw()` s'atteint a chaque image. Mesure
(tests/test_debug_mode.py) : 30,0 images/s sous %runfile comme sous %debugfile, le
`sys.settrace` du debogueur ne coute rien de mesurable a cette echelle.

CE QUI NE MARCHAIT PAS, ET POURQUOI CE N'ETAIT PAS OU ON CROYAIT
Le pont, lui, n'avait aucun probleme sous le debogueur - verifie par la mesure avant de
toucher au code. Le defaut etait entierement dans l'aiguillage du CLAVIER.

Le panneau prend le clavier des la premiere image, donc des `pyxel.init()`, pour qu'on
puisse jouer sans avoir a cliquer dedans. En mode debogage, l'invite `ipdb>` s'affiche
dans la console juste apres - mais `PyxelScreenWidget.keyPressEvent` intercepte a peu
pres toute touche et l'expedie au jeu. Les `n`, `s`, `c` tapes par l'utilisateur
partaient donc dans un jeu justement arrete. Le debogueur PARAISSAIT fige alors que rien
n'etait casse : seul le clavier etait mal aiguille. C'est le genre de defaut qu'aucun
test du pont ne pouvait voir, puisque le pont marchait.

CE QUE FAIT LE CORRECTIF
Le pont suit `sig_pdb_state_changed` de chaque console (True = l'invite attend une
commande, False = la commande est soumise). Le panneau :
  - rend le clavier a la console des que le debogueur s'arrete - et seulement s'il le
    detenait, pour ne jamais deplacer un focus pose par l'utilisateur lui-meme ;
  - le rend a la CONSOLE explicitement (son `_control`), pas par un simple clearFocus()
    qui laisserait le clavier a la fenetre principale, ou taper `n` ne fait rien ;
  - ne le reprend qu'apres FRAMES_BEFORE_REGRAB images consecutives sans nouvel arret ;
  - et seulement si le clavier est ENCORE la ou il l'avait pose.

Le seuil d'images est ce qui distingue un `c` (le jeu repart pour de bon) d'un `n` sur un
point d'arret atteint a chaque image (une image, puis nouvel arret). Rendre le clavier
des la reprise ferait clignoter le focus a chaque pas, et la commande suivante serait
avalee par le jeu. Cinq images font 0,17 s a 30 images/s : imperceptible quand le jeu
repart, jamais atteint quand on avance pas a pas. La barre d'outils du debogueur passe
par le meme chemin que la frappe (`pdb_execute`), donc les fleches se comportent comme
`c` et `n` - il n'y a rien de specifique au clavier.

Le dernier point traite le cas ou l'utilisateur clique dans l'editeur pendant l'arret
pour relire son code : reprendre le clavier a ce moment-la lui arracherait un focus qu'il
vient de choisir (demande explicite, 21/07/2026). Le controle se fait a l'instant de la
reprise, en comparant `QApplication.focusWidget()` au widget de la console - et non par
un suivi des changements de focus. C'est plus simple, et surtout auto-correcteur : s'il
revient dans la console avant de taper `c`, le jeu retrouve le clavier normalement.

⚠ CE QUI REND CE CORRECTIF SUR, ET QU'IL NE FAUT PAS PRENDRE POUR UN BONUS
Deplacer le focus declenche `focusOutEvent`, qui relache toutes les touches enfoncees.
Ce n'est pas une amelioration apportee au passage, c'est la contrepartie obligatoire :
SANS le correctif, une touche maintenue pendant un arret ne posait aucun probleme - le
panneau gardait le focus, donc le relachement physique lui parvenait normalement. En
rendant le clavier a la console on CREE le risque, puisque le relachement part desormais
dans la console et que la touche resterait enfoncee cote jeu pour toujours (le personnage
courrait indefiniment a la reprise). C'est `focusOutEvent` qui l'annule, et
test_debug_mode.py le verifie explicitement - sans quoi le correctif introduirait un
defaut pire que celui qu'il repare.


Ce que coute la recopie des pixels (mesure, pas estimation)
------------------------------------------------------------
Mesure par tests/bench_pipeline.py, panneau de 960x720, mediane sur 300 appels :

     ecran     publier      lire   peindre     total   % du budget d'une image
   128x128     0.004ms   0.003ms   0.932ms   0.939ms                      5.6 %
   160x120     0.004ms   0.003ms   1.396ms   1.403ms                      8.4 %
   256x256     0.005ms   0.004ms   0.601ms   0.610ms                      3.7 %

La recopie coute 3 a 5 MICROsecondes, soit 0,03 % du budget d'une image a 60 par seconde.
Un ecran Pyxel fait 16 a 64 Ko - un octet par pixel, pas quatre, puisque c'est une image
INDEXEE - donc 1 a 4 Mo/s, a comparer aux dizaines de Go/s de la memoire. C'est du bruit.

Tout le cout est dans le DESSIN, et il depend de la taille du PANNEAU, pas de celle du jeu :
le 160x120 est le plus lent des trois parce qu'avec un agrandissement x6 il remplit les
960x720 du panneau (691 000 pixels a ecrire), la ou le 256x256 agrandi x2 n'en couvre que
262 000. Ce cout-la, n'importe quelle solution le paie, y compris une fenetre SDL native.

Consequence tiree de cette mesure : plutot que d'optimiser la recopie (deja gratuite), la
relecture s'arrete des qu'aucun panneau n'est visible (showEvent / hideEvent ->
subscribe / unsubscribe). Le jeu, lui, continue de tourner.


Regularite d'affichage (gigue)
-------------------------------
Trois cadences independantes coexistent : le jeu publie a son rythme, le panneau relit la
memoire partagee sur une minuterie Qt, l'ecran se rafraichit a sa frequence. Le defaut
n'est PAS la perte d'images - mesure a zero perte des que la relecture est plus rapide que
la publication - mais leur REGULARITE : une image publiee juste apres une relecture attend
jusqu'a une periode complete avant d'etre vue, donc certaines restent affichees deux
rafraichissements d'ecran et d'autres un seul. Sur un defilement continu, cela saccade.

Mesure par tests/test_frame_pacing.py (ecart entre l'intervalle d'arrivee observe et
l'intervalle theorique du jeu) :

   cadence jeu   relecture   images perdues   gigue (ecart type)   pire ecart
      30 fps       15 ms           0                6,03 ms         12,46 ms
      30 fps        4 ms           0                1,86 ms          4,61 ms
      60 fps       15 ms           0                4,49 ms         13,90 ms
      60 fps        4 ms           0                1,77 ms          4,60 ms

D'ou POLL_INTERVAL_MS = 4 (spyder/bridge_manager.py), soit un quart de periode d'ecran a
60 Hz. Le cout est negligeable : le chemin "rien de nouveau" ne fait que deux lectures
d'entier dans la memoire partagee, mesure a 0,25 microseconde, soit 0,006 % d'un coeur a
250 relectures par seconde.

Ce qui reste : la gigue ne peut pas tomber a zero sans caler l'affichage sur le signal de
rafraichissement de l'ecran, que Qt n'expose pas pour un QWidget. 1,8 ms sur une periode
de 16,7 ms est en dessous du seuil ou une image bascule sur un rafraichissement voisin.
Le test echoue au-dela de 4 ms, ce qui protege ce reglage d'une regression.


Les autres approches, et pourquoi elles ont ete ecartees
--------------------------------------------------------
Reparenter la fenetre SDL (XEmbed)
    La plus propre sur le papier : zero recopie. Impossible sous Wayland. On pourrait la
    reactiver en forcant TOUT Spyder sur XWayland - degrader l'IDE entier (HiDPI, mise a
    l'echelle fractionnaire, methodes de saisie) pour un seul panneau est un mauvais
    marche, et il faudrait retrouver la fenetre du jeu par heuristique.

Un sous-processus dedie par jeu (la version precedente)
    Protegeait le noyau : ni la fin du jeu ni une erreur ne touchaient la console. Mais
    plus de sortie dans la console, plus de points d'arret, plus d'explorateur de
    variables - et neuf boutons pour reimplementer ce que la console offre nativement.

Partage de texture GPU (dma-buf)
    Reellement zero copie. Demande d'acceder au contexte OpenGL de Pyxel, que son coeur
    Rust n'expose pas. Complexite considerable pour un cout mesure a 4 microsecondes.

Envoyer les images dans un tuyau plutot qu'en memoire partagee
    A 1-4 Mo/s le debit passerait. Mais un tuyau conserve tout ce qu'on y ecrit : si
    l'interface de Spyder se fige une demi-seconde, les images s'accumulent et le jeu
    affiche ensuite du retard au lieu du present. La memoire partagee donne le
    comportement voulu - un panneau en retard saute des images.


La souris doit etre REAFFIRMEE a chaque image (et pas le clavier)
-----------------------------------------------------------------
Les deux entrees ne se comportent pas pareil, et rien dans le code ne le laisse deviner.

L'etat des TOUCHES survit tout seul : c'est une table que Pyxel alimente depuis les
evenements SDL, et en mode offscreen aucun evenement n'arrive. Ce qu'on injecte par
set_btn() reste donc en place jusqu'a ce qu'on le change - exactement ce qu'il faut pour
un appui maintenu.

La POSITION DE LA SOURIS, elle, est relue du systeme a chaque tour de boucle, offscreen ou
non. set_mouse_pos() n'est donc respecte que pour l'image ou on l'appelle. Mesure d'origine
(tests/test_mouse_and_editor.py) : position injectee (20, 30) vue UNE image, puis (-4, 19)
figee pour toujours - la position du curseur physique, sans aucun rapport avec le panneau.

Ce que ca cassait, et pourquoi personne ne l'avait vu : les widgets de Pyxel testent
l'appartenance du curseur a leur rectangle au moment du CLIC. Le clic arrivant toujours au
moins une image apres le deplacement, il etait teste contre la mauvaise position - donc
jamais sur le widget vise. L'editeur de ressources, qui se pilote presque entierement a la
souris, etait donc inutilisable, alors que les jeux ne s'en apercevaient pas : la plupart
lisent pyxel.mouse_x en continu, ou n'utilisent pas la souris. Et AUCUN test n'exercait la
souris - tout portait sur le clavier.

InputConsumer.pump() reaffirme donc la derniere position connue a chaque image, AVANT de
vider l'anneau (un nouveau deplacement doit ecraser cette valeur, pas l'inverse). Tant que
le panneau n'a rien envoye, on ne force rien : sinon on epinglerait le curseur en (0, 0)
avant meme que l'utilisateur ait survole le panneau.


Les manettes ne passent pas par le pont
----------------------------------------
Le pont ne traduit que le clavier et la souris. Ce n'est pas un oubli : le sous-systeme
joystick de SDL s'initialise normalement en mode offscreen (verifie : SDL_WasInit rend
vrai pour JOYSTICK et GAMECONTROLLER), parce que le pilote VIDEO n'a rien a voir avec la
lecture des manettes, que SDL prend directement sur /dev/input. Une manette branchee est
donc lue par Pyxel nativement.
A verifier avec du vrai materiel : rien n'etait branche au moment du developpement.


Fichiers
--------
  spyder_pyxel/bridge/protocol.py   Format de la memoire partagee (images + anneau
                                    d'entrees). Ses assertions d'import ont deja rattrape
                                    deux chevauchements de zones.
  spyder_pyxel/bridge/hooks.py      Cote jeu : publication de l'ecran, consommation des
                                    entrees, crochets sur pyxel.init/run/flip/show.
  spyder_pyxel/bridge/kernel.py     Ce qui s'installe dans le noyau IPython.
  spyder_pyxel/bridge/reader.py     Cote panneau, sans Qt : creation du segment, lecture
                                    des images, ecriture des entrees.
  spyder_pyxel/spyder/bridge_manager.py  Un canal par console, partage par les deux
                                    panneaux, et la distribution des images.
  spyder_pyxel/spyder/plugin_base.py  Le socle commun aux deux greffons (suivi des
                                    consoles). Volontairement vise par AUCUN point
                                    d'entree, cf. ci-dessous.
  spyder_pyxel/spyder/widgets/screen.py  Le rendu et les entrees.
  spyder_pyxel/spyder/widgets/panes.py   Les deux panneaux, sans aucun bouton.
  spyder_pyxel/spyder/plugin.py     Le greffon "Pyxel".
  spyder_pyxel/spyder/plugin_studio.py  Le greffon "Pyxel Studio". ⚠ Module SEPARE
                                    obligatoirement : Spyder enregistre ses dependances
                                    par nom de module et refuse les doublons, donc deux
                                    points d'entree visant le meme module font echouer le
                                    second (constate en direct).
  exemples/demo_pyxel.py            Petit jeu pour verifier que tout marche.


Tests
-----
  ./tests/run_all.sh        (sans serveur d'affichage, QT_QPA_PLATFORM=offscreen)

  test_keymap_matches_pyxel.py  keymap.py recopie une trentaine de constantes de Pyxel
                                pour que Spyder n'ait pas a importer pyxel (donc a charger
                                libSDL2) juste pour lire des numeros de touches. Ce test
                                est le garde-fou de cette duplication ; il a deja rattrape
                                un KEY_MENU recopie de travers.

  test_widgets_build.py         Reproduit la sequence de construction de Spyder, verifie
                                qu'il ne reste AUCUN bouton, que les deux panneaux
                                filtrent sur des marqueurs distincts, qu'ils vivent dans
                                des modules distincts, et resout les references des
                                crochets on_plugin_available - une erreur a cet endroit
                                (ToolsMenuSections.Tools, disparu en 6.1) empechait les
                                deux greffons de se charger, sans autre indice qu'une
                                ligne dans la console.

  test_end_to_end_qt.py         Le chemin complet avec un faux noyau et un vrai jeu :
                                images recues, PIXELS REELLEMENT PEINTS relus dans le
                                rendu du widget, evenement clavier Qt qui deplace quelque
                                chose dans le jeu, relachement qui l'arrete, sortie du jeu
                                bien remontee cote noyau, /dev/shm laisse propre.

  test_editor_kind.py           Lance le vrai editeur de ressources et verifie qu'il porte
                                le marqueur EDITOR - donc qu'il s'affiche dans le bon
                                panneau. C'est ce mecanisme qui remplace le bouton
                                "Ouvrir un fichier de ressources".

  test_real_kernel.py           Le chemin complet dans un VRAI noyau spyder-kernels.
                                ⚠ Il n'en lancait pas un jusqu'au 21/07/2026 :
                                `KernelManager.kernel_cmd` a disparu en jupyter_client 8,
                                et lui affecter une liste n'ajoute plus qu'un attribut
                                inerte - le gestionnaire lancait donc un ipykernel NU,
                                sans le moindre avertissement. Le demarrage est desormais
                                dans tests/spyder_kernel_harness.py, et le test verifie
                                d'abord que %runfile existe.

  test_debug_mode.py            Ctrl+F5 : cadence sous %debugfile, point d'arret dans la
                                boucle de jeu, et surtout l'aiguillage du clavier entre
                                le panneau et l'invite `ipdb>` (cf. la section sur le
                                mode debogage plus haut).

  test_mouse_and_editor.py      La SOURIS (jamais exercee avant le 21/07/2026) et
                                l'editeur de ressources reellement pilote : clic, glisser,
                                Ctrl+S, puis relecture du .pyxres par un processus NEUF -
                                seule facon de prouver que la sauvegarde a atteint le
                                disque. C'est ce test qui a revele que la position de la
                                souris etait perdue des l'image suivante.

  test_open_pyxres.py           L'aiguillage d'un .pyxres vers ce greffon (avec la MEME
                                regle que open_file_in_plugin, recopiee pour que le
                                contrat casse bruyamment s'il change) et l'orchestration :
                                console dediee creee sans voler le focus, reutilisee si
                                libre, jamais reutilisee si un programme Pyxel y tourne, et
                                editeur lance seulement une fois le crochet pose. Verifie
                                aussi que les chemins traversent repr() - un dossier avec
                                une apostrophe casserait sinon la ligne envoyee.

  bench_pipeline.py             Le banc de mesure dont sort le tableau ci-dessus.


Installation
------------
  CachyOS/Installation/installation_Spyder_plugin_pyxel.sh

Appele automatiquement par installation_Spyder.sh, pour que le plugin soit remis en place apres
une reinstallation complete de Spyder. Le plugin n'est pas copie dans le venv : un .pth
pointe vers ce dossier du depot Mercurial, donc une correction ici est active au prochain
lancement de Spyder, sans reinstallation.

Dependance : pyxel, declare dans
Commun/requirements/requirements_Spyder-<version>_py<x.y>.txt.

Valide sous Spyder 6.1.5 avec qtpy -> PyQt6.
