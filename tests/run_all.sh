#!/bin/bash
# Lance tous les tests du greffon Pyxel, sans serveur d'affichage.
#
# Qt tourne en QT_QPA_PLATFORM=offscreen et Pyxel en SDL_VIDEODRIVER=offscreen (pose par
# le crochet) : la suite passe donc aussi bien dans une session graphique qu'en ligne de
# commande sur une machine sans ecran.
set -e
cd "$(dirname "$0")/.."

PYTHON="${SPYDER_PYXEL_PYTHON:-/DATA/Python/SmartPython/CachyOS/versions/SmartPythonEditor/bin/python}"

export QT_QPA_PLATFORM=offscreen
export PYTHONPATH="$PWD:$PYTHONPATH"

echo "=== Correspondance des codes de touches avec pyxel ==="
"$PYTHON" -c "
from tests.test_keymap_matches_pyxel import test_all_copied_constants_match_pyxel as t
t(); print('OK  keymap.py est aligne sur le pyxel installe')
"

echo
echo "=== Construction des deux panneaux ==="
"$PYTHON" tests/test_widgets_build.py

echo
echo "=== Pont complet : noyau -> memoire partagee -> pixels peints -> clavier ==="
"$PYTHON" tests/test_end_to_end_qt.py

echo
echo "=== Aiguillage jeu / editeur de ressources ==="
"$PYTHON" tests/test_editor_kind.py

echo
echo "=== Regularite d'arrivee des images (gigue) ==="
"$PYTHON" tests/test_frame_pacing.py

echo
echo "=== Vrai noyau spyder-kernels (le plus proche du reel) ==="
"$PYTHON" tests/test_real_kernel.py

echo
echo "=== Mode debogage : %debugfile, points d'arret, et a qui va le clavier ==="
"$PYTHON" tests/test_debug_mode.py

echo
echo "=== Souris, et editeur de ressources reellement pilote ==="
"$PYTHON" tests/test_mouse_and_editor.py

echo
echo "=== Ouvrir un .pyxres lance l'editeur (aiguillage + console dediee) ==="
"$PYTHON" tests/test_open_pyxres.py

echo
echo "=== Bandes autour de l'image : fond de Spyder ou pixels de bord etires ==="
"$PYTHON" tests/test_bords_etires.py

echo
echo "=== Le crochet est pose avant le jeu, quel que soit l'ordre des signaux ==="
"$PYTHON" tests/test_amorcage_console.py

echo
echo "=== Redirection Pyxel du profileur (sous-processus independant, hors console) ==="
"$PYTHON" tests/test_profiler_launcher.py

echo
echo "=== pyxel.quit() ne tue plus le noyau/processus appelant ==="
"$PYTHON" tests/test_quit_rend_la_main.py

echo
echo "=== Interrompre un jeu Pyxel de l'exterieur (Stop) ne tue plus le noyau ==="
"$PYTHON" tests/test_sigint_pendant_jeu.py

echo
echo "TOUS LES TESTS DU GREFFON PYXEL SONT PASSES"
