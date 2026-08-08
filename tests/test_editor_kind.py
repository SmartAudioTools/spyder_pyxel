# -*- coding: utf-8 -*-
"""
Verifie l'aiguillage vers le panneau "Pyxel Studio".

Tout part de la console : rien, dans une image, ne dit d'ou elle vient. L'editeur de
ressources de Pyxel etant lui-meme un programme Pyxel, seul le marqueur inscrit dans
l'en-tete partage permet de distinguer les deux panneaux. C'est ce marqueur qui remplace
le bouton "Ouvrir un fichier de ressources" de la version precedente : s'il se trompait,
l'editeur s'afficherait dans le panneau des jeux et le panneau Studio resterait vide.

Lancement : python tests/test_editor_kind.py
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spyder_pyxel.bridge import protocol, reader  # noqa: E402

KERNEL = '''
import sys
exec(compile(open(sys.argv[1]).read(), "<bootstrap>", "exec"), {})
import pyxel.editor
pyxel.editor.App(sys.argv[2], "image")
'''


def main():
    directory = Path(tempfile.mkdtemp(prefix="spyder_pyxel_editor_"))
    (directory / "kernel.py").write_text(KERNEL, encoding="utf-8")

    channel = reader.PyxelChannel()
    name = channel.create()
    (directory / "boot.py").write_text(
        reader.kernel_bootstrap_code(name), encoding="utf-8")

    process = subprocess.Popen(
        [sys.executable, str(directory / "kernel.py"), str(directory / "boot.py"),
         str(directory / "ressources.pyxres")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        cwd=str(directory))

    frame = None
    deadline = time.time() + 40
    while time.time() < deadline:
        frame = channel.read_frame()
        if frame is not None:
            break
        if process.poll() is not None:
            break
        time.sleep(0.02)

    if frame is None:
        print("ECHEC : aucune image de l'editeur")
        print(process.stdout.read()[:2000])
        return 1

    print(f"OK  editeur de ressources affiche : {frame.width}x{frame.height}")
    kind = channel.kind()
    assert kind == protocol.KIND_EDITOR, (
        f"marqueur {kind}, attendu KIND_EDITOR ({protocol.KIND_EDITOR}) : "
        "l'editeur s'afficherait dans le panneau des jeux")
    print("OK  marqueur = KIND_EDITOR -> aiguille vers le panneau Pyxel Studio")

    process.kill()
    process.wait(timeout=5)
    channel.release()
    leftovers = [n for n in os.listdir("/dev/shm") if n.startswith("spyder_pyxel_")]
    assert not leftovers, leftovers
    print("OK  /dev/shm est propre")
    print("\nL'AIGUILLAGE JEU / EDITEUR EST CORRECT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
