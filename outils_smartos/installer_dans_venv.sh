#!/bin/bash
# Installation de CE greffon dans le venv Spyder d'une machine SmartOS (mecanisme .pth
# "editable" : le greffon reste dans ce depot, seul un pointeur part dans site-packages).
# Sorti d'installation_SmartPythonEditor.sh le 08/08/2026 (demande utilisateur : les notes et
# verifications de chaque greffon vivent dans SON depot) - le script SmartOS n'est plus qu'un
# appel d'une ligne vers ce fichier. L'installation DISTRIBUEE (install.sh du fork
# SmartPythonEditor) n'utilise PAS ce script : elle passe par pip.
#
# Usage : installer_dans_venv.sh <python du venv Spyder> <sans_tests true|false> \
#                                <install_spyder_plugin.py> <spyder_config_set.py> <spyder.ini>
set -u
SPYDER_PYTHON="${1:?python du venv Spyder}"
SANS_TESTS="${2:-true}"
OUTIL_INSTALL="${3:?chemin de install_spyder_plugin.py}"
OUTIL_CONFIG="${4:?chemin de spyder_config_set.py}"
SPYDER_INI="${5:?chemin du spyder.ini}"
PLUGIN_DIR="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/.." && pwd)"

# =============================================================================
# Plugin Spyder "Pyxel" (TODO - Spyder.txt, section "Integration Pyxel")
# =============================================================================
# Installe dans l'environnement pyenv de Spyder le plugin versionne dans
# ce depot (spyder_pyxel/, qui ajoute DEUX panneaux :
#   - "Pyxel"        : l'ecran du jeu Pyxel lance depuis la console ;
#   - "Pyxel Studio" : l'ecran de l'editeur de ressources de Pyxel.
#
# CE QUE FAIT LE GREFFON
#   Deux panneaux, "Pyxel" et "Pyxel Studio", qui n'executent RIEN : ce sont de purs
#   afficheurs, sans aucun bouton. Un jeu se lance avec F5 comme n'importe quel script -
#   ses print vont dans la console, les points d'arret fonctionnent, l'explorateur de
#   variables voit ses variables - et seule sa FENETRE est remplacee par le panneau.
#   L'editeur de ressources se lance de la meme facon, depuis la console.
#
# POURQUOI LE JEU N'EST PAS UNE FENETRE SDL "ENCASTREE" DANS LE PANNEAU
#   L'approche naturelle serait de retrouver la fenetre du jeu et de la reparenter dans un
#   QWidget (XEmbed / QWindow.fromWinId). Elle ne fonctionne que sous X11. Or la session
#   KDE de cette machine est Wayland, et sous Wayland un client ne PEUT PAS reparenter la
#   surface d'un autre client : c'est un choix de conception du protocole, pas une lacune
#   temporaire.
#
#   Le greffon ne transporte donc pas une fenetre mais des PIXELS. Spyder pose un crochet
#   dans chaque console ; quand un programme Pyxel y demarre, il tourne sans fenetre
#   (SDL_VIDEODRIVER=offscreen), publie son ecran dans une memoire partagee, et le panneau
#   Qt le redessine. En retour, le panneau injecte touches et souris par un anneau dans la
#   meme memoire partagee (stdin est exclu : il appartient au noyau IPython).
#   C'est independant du serveur d'affichage, et l'agrandissement se fait au plus proche
#   voisin, donc en pixels nets.
#
# DEPENDANCE
#   pyxel (2.9.x) doit etre present dans le venv de Spyder ; il est declare dans
#   derives/requirements_Spyder-<version>_py<x.y>.txt du generateur et donc installe
#   par installation_SmartPythonEditor.sh. Ce script le verifie et l'installe au besoin, pour rester
#   utilisable seul.
#
# CE QUI EST VERIFIE AVANT INSTALLATION
#   Les neuf suites de tests du plugin sont jouees : correspondance des codes de
#   touches avec le pyxel reellement installe, construction des deux panneaux comme
#   Spyder le fait (y compris la resolution des crochets on_plugin_available, dont
#   une erreur empechait les deux greffons de se charger sans autre indice qu'une
#   ligne dans la console), le pont complet (faux noyau -> memoire partagee ->
#   pixels reellement peints -> clavier redescendu jusqu'au jeu), l'aiguillage
#   jeu / editeur, et le mode debogage (Ctrl+F5 : cadence sous %debugfile, point
#   d'arret dans la boucle de jeu, et surtout a qui va le clavier quand l'invite
#   `ipdb>` s'affiche). Elles tournent sans serveur d'affichage.
#
# Invocation : installation_SmartPythonEditor.sh --greffon pyxel
# =============================================================================

# PAS de "set -e" : error_handler.sh installe un trap ERR interactif, incompatible
# avec errexit (cf. l'explication detaillee en tete de installation_SmartPythonEditor.sh).

if [ ! -f "$PLUGIN_DIR/pyproject.toml" ]; then
  echo "ERREUR : plugin introuvable dans $PLUGIN_DIR - abandon." >&2
  exit 1
fi

if [ ! -x "$SPYDER_PYTHON" ]; then
  echo "ERREUR : $SPYDER_PYTHON introuvable." >&2
  echo "         Installez d'abord Spyder (./installation_SmartPythonEditor.sh)." >&2
  exit 1
fi
echo "Environnement Spyder cible : $SPYDER_PYTHON"

# --- Dependance pyxel --------------------------------------------------------
if ! "$SPYDER_PYTHON" -c "import pyxel" >/dev/null 2>&1; then
  echo "pyxel absent du venv Spyder : installation."
  # --cache-dir explicite : meme raison que dans installation_SmartPythonEditor.sh (un pip.conf
  # pose par NVIDIA PyIndex force no-cache-dir=true globalement).
  "$SPYDER_PYTHON" -m pip install ${PIP_CACHE_ARGS:-} "pyxel==2.9.8" || {
    echo "ERREUR : impossible d'installer pyxel (acces internet ?)." >&2; exit 1; }
else
  echo "pyxel present : $("$SPYDER_PYTHON" -c 'import pyxel; print(pyxel.VERSION)')"
fi

# Le pilote video "offscreen" de SDL rend en OpenGL sans fenetre, donc via EGL.
# Si libEGL manque, pyxel.init() echoue par une panique Rust peu parlante
# ("Failed to create window: OpenGL support is either not configured...") : mieux
# vaut le dire ici, clairement, que laisser l'utilisateur le decouvrir au premier
# lancement d'un jeu.
if ! ldconfig -p 2>/dev/null | grep -q "libEGL\.so"; then
  echo "AVERTISSEMENT : libEGL introuvable. Le rendu hors-ecran de Pyxel en a besoin." >&2
  echo "                Installez le paquet fournissant libEGL (mesa) avant d'utiliser le dock." >&2
fi

# --- Tests -------------------------------------------------------------------
if [ "$SANS_TESTS" = false ]; then
  echo
  echo "--- Codes de touches : keymap.py contre le pyxel installe ---"
  PYTHONPATH="$PLUGIN_DIR" "$SPYDER_PYTHON" -c "
from tests.test_keymap_matches_pyxel import test_all_copied_constants_match_pyxel as t
t(); print('OK  keymap.py est aligne sur le pyxel installe')
" || { echo "ERREUR : les codes de touches ont diverge - installation annulee." >&2; exit 1; }

  echo
  echo "--- Construction des deux docks (sequence d'appels de Spyder) ---"
  # QT_QPA_PLATFORM=offscreen : les tests creent de vrais widgets Qt mais ne
  # doivent pas exiger d'affichage (utilisable depuis une console ou en SSH).
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_widgets_build.py" || {
    echo "ERREUR : les docks ne se construisent pas - installation annulee." >&2; exit 1; }

  echo
  echo "--- Pont complet : noyau -> memoire partagee -> pixels peints -> clavier ---"
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_end_to_end_qt.py" || {
    echo "ERREUR : le pont ne fonctionne pas - installation annulee." >&2; exit 1; }

  echo
  echo "--- Aiguillage jeu / editeur de ressources ---"
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_editor_kind.py" || {
    echo "ERREUR : l'aiguillage des panneaux est casse - installation annulee." >&2; exit 1; }

  echo
  echo "--- Regularite d'arrivee des images (gigue) ---"
  # Mesure l'ecart entre l'intervalle d'arrivee des images et celui du jeu. Echoue si la
  # gigue depasse 4 ms, seuil au-dela duquel un defilement continu saccade visiblement.
  "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_frame_pacing.py" || {
    echo "ERREUR : les images arrivent trop irregulierement - installation annulee." >&2
    exit 1; }

  echo
  echo "--- Vrai noyau spyder-kernels (le plus proche du reel) ---"
  # Demarre le MEME noyau que la console de Spyder et lui envoie le code d'amorcage par le
  # meme chemin (execute silencieux). C'est le test le plus fidele possible sans serveur
  # d'affichage : les autres utilisent un faux noyau, qui n'avait pas vu que le crochet
  # etait injecte avant que le noyau soit pret.
  "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_real_kernel.py" || {
    echo "ERREUR : le pont ne fonctionne pas dans un vrai noyau - installation annulee." >&2
    exit 1; }

  echo
  echo "--- Mode debogage (Ctrl+F5) ---"
  # Le pont fonctionnait deja sous le debogueur ; ce qui ne fonctionnait pas, c'est le
  # CLAVIER : le panneau le prenait des la premiere image et ne le rendait jamais, donc
  # les `n`/`s`/`c` tapes a l'invite `ipdb>` partaient dans un jeu justement arrete. Ce
  # test verifie la cadence sous %debugfile, un point d'arret dans la boucle de jeu, et
  # l'aiguillage du focus entre le panneau et la console.
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_debug_mode.py" || {
    echo "ERREUR : le greffon ne fonctionne pas en mode debogage - installation annulee." >&2
    exit 1; }

  echo
  echo "--- Souris et editeur de ressources ---"
  # La souris n'etait exercee par AUCUN test avant le 21/07/2026, et elle etait cassee :
  # Pyxel relit la position du curseur au systeme a chaque image, donc set_mouse_pos()
  # n'etait respecte que pour une seule image. L'editeur, qui se pilote a la souris, en
  # etait inutilisable. Ce test pilote l'editeur pour de vrai (clic, glisser, Ctrl+S) et
  # relit le .pyxres ecrit depuis un processus neuf.
  "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_mouse_and_editor.py" || {
    echo "ERREUR : la souris ou l'editeur de ressources ne fonctionne pas - installation annulee." >&2
    exit 1; }

  echo
  echo "--- Ouverture d'un .pyxres ---"
  # Ouvrir un .pyxres depuis Dolphin, le menu Fichier ou le panneau Fichiers doit lancer
  # l'editeur de ressources, dans une console DEDIEE : pyxel.run() bloque le noyau et
  # Pyxel coupe le processus en sortant, donc la console de travail serait confisquee
  # puis perdue. Ce test verifie l'aiguillage et le choix de la console.
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_open_pyxres.py" || {
    echo "ERREUR : l'ouverture d'un .pyxres ne fonctionne pas - installation annulee." >&2
    exit 1; }

  echo
  echo "--- Bandes autour de l'image (fond de Spyder ou pixels de bord etires) ---"
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_bords_etires.py" || {
    echo "ERREUR : le remplissage des bandes autour de l'image est casse - installation annulee." >&2
    exit 1; }

  echo
  echo "--- Le crochet est pose avant le jeu, quel que soit l'ordre des signaux ---"
  # Couvre la course de demarrage signalee le 26/07/2026 : "le jeu ne se lance pas
  # systematiquement dans le panneau, mais parfois dans sa propre fenetre". Absent de ce
  # script jusqu'ici alors que le correctif et son test existaient deja (cf.
  # tests/run_all.sh) - seule l'installation ne le verifiait pas.
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_amorcage_console.py" || {
    echo "ERREUR : le crochet peut arriver apres le jeu - installation annulee." >&2
    exit 1; }

  echo
  echo "--- Redirection Pyxel du profileur (sous-processus independant, hors console) ---"
  # Signale par l'utilisateur le 31/07/2026 : lancer le PROFILER (pas F5) sur un jeu Pyxel
  # l'ouvrait dans sa propre fenetre - le profileur lance le script dans un QProcess
  # independant (lp_launcher.py), hors de toute console/noyau, jamais atteint par le crochet
  # habituel. Cf. spyder_pyxel/spyder/bridge_manager.attach_process et lp_launcher.py
  # --pyxel-shm/--pyxel-bridge-path.
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_profiler_launcher.py" || {
    echo "ERREUR : la redirection Pyxel du profileur ne fonctionne plus - installation annulee." >&2
    exit 1; }

  echo
  echo "--- pyxel.quit() ne tue plus le noyau/processus appelant ---"
  # Signale par l'utilisateur le 01/08/2026 : pyxel.run() natif ne rend JAMAIS la main a
  # Python, quelle que soit la facon dont le jeu se termine - meme pyxel.quit() appele par
  # le jeu lui-meme tuait tout le noyau IPYTHON qui l'hebergeait. Cf. hooks.py, patched_quit
  # et la boucle ecrite a la main dans patched_run.
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_quit_rend_la_main.py" || {
    echo "ERREUR : pyxel.quit() tue encore le noyau/processus - installation annulee." >&2
    exit 1; }

  echo
  echo "--- Interrompre un jeu Pyxel de l'exterieur (Stop) ne tue plus le noyau ---"
  # pyxel.init() installe SON PROPRE gestionnaire SIGINT natif (Rust,
  # pyxel::platform::facade::sigint_handler), invisible depuis signal.getsignal() : un
  # Ctrl+C externe (bouton Stop, interruption du noyau) tuait tout le noyau IPYTHON en
  # ~0.2s, silencieusement, au lieu de lever un KeyboardInterrupt Python normal. Cf.
  # hooks.py, patched_init (restauration du gestionnaire juste apres l'appel natif).
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_sigint_pendant_jeu.py" || {
    echo "ERREUR : interrompre un jeu Pyxel de l'exterieur tue encore le noyau - installation annulee." >&2
    exit 1; }
fi

# --- Installation ------------------------------------------------------------
echo
# ⚠ PAS de "pip install" ici : le venv pyenv de Spyder est construit a partir d'un
# requirements fige qui NE CONTIENT PAS setuptools, donc "pip install <projet
# source>" echoue a importer le backend declare dans pyproject.toml
# (setuptools.build_meta), et l'isolation de build irait le chercher sur PyPI.
# install_spyder_plugin.py ecrit directement ce que produirait une installation
# "editable" : un .pth vers le dossier du depot + un .dist-info portant les points
# d'entree - exactement ce que lit spyder/app/find_plugins.py. Le plugin reste dans
# le depot Mercurial : une correction y est active au prochain lancement de Spyder,
# sans reinstallation. Cf. l'en-tete de install_spyder_plugin.py.
python3 "$OUTIL_INSTALL" \
    "$PLUGIN_DIR" "$SPYDER_PYTHON" || {
  echo "ERREUR : l'installation du plugin a echoue." >&2; exit 1; }

echo
echo "Plugin 'Pyxel' installe (deux panneaux)."
echo "Dans Spyder : menu Fenetre > Panneaux > Pyxel, et > Pyxel Studio."
echo "Ouvrez $PLUGIN_DIR/exemples/demo_pyxel.py et lancez-le avec F5."
echo "Documentation : $PLUGIN_DIR/README.txt"
