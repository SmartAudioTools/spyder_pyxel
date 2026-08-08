# -*- coding: utf-8 -*-
"""Demarrage d'un VRAI noyau spyder-kernels, partage par les tests qui en ont besoin.

⚠ POURQUOI CE MODULE EXISTE
jupyter_client 8 a SUPPRIME l'attribut `KernelManager.kernel_cmd`, present jusqu'a la
v5. La recette repandue :

    manager = KernelManager()
    manager.kernel_cmd = [sys.executable, "-m", "spyder_kernels.console", ...]
    manager.start_kernel()

ne fait plus qu'ajouter un attribut Python inerte sur l'objet. `start_kernel()` resout
alors le kernelspec par defaut et lance un **ipykernel nu**. Aucune erreur, aucun
avertissement : le test croit interroger un noyau Spyder alors qu'il interroge IPython.

Le symptome qui l'a revele : `%runfile` et `%debugfile`, qui sont des magies apportees
par spyder_kernels, repondaient "Line magic function `%debugfile` not found". Tout ce que
les tests validaient jusque-la (crochet pose, images publiees) passe aussi bien dans un
ipykernel, d'ou le silence.

On passe donc par un gestionnaire de kernelspec qui fournit l'argv voulue - le seul
mecanisme que jupyter_client 8 respecte encore.
"""

import sys

from jupyter_client.kernelspec import KernelSpec, KernelSpecManager
from jupyter_client.manager import KernelManager

KERNEL_NAME = "spyder-kernels-test"


class SpyderKernelSpecManager(KernelSpecManager):
    """Fournit un kernelspec unique, pointant sur spyder_kernels.console."""

    def get_kernel_spec(self, kernel_name):
        return KernelSpec(
            argv=[sys.executable, "-m", "spyder_kernels.console",
                  "-f", "{connection_file}"],
            display_name="spyder-kernels (test)",
            language="python",
        )


def start_kernel(timeout=90):
    """Rend (manager, client) pour un noyau spyder-kernels pret a executer."""
    manager = KernelManager(kernel_name=KERNEL_NAME,
                            kernel_spec_manager=SpyderKernelSpecManager())
    manager.start_kernel()
    client = manager.client()
    client.start_channels()
    client.wait_for_ready(timeout=timeout)
    return manager, client


def assert_is_spyder_kernel(client, timeout=30):
    """Verifie que le noyau est bien celui de Spyder, et non un ipykernel nu.

    Sans ce garde-fou, une regression de la resolution du kernelspec ferait retomber
    silencieusement les tests sur un ipykernel - c'est exactement ce qui s'etait produit.
    On teste la presence de `%runfile`, qui n'existe que dans spyder_kernels.
    """
    import time

    client.execute(
        "print('MAGICS', 'runfile' in get_ipython().magics_manager.magics['line'])")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            message = client.get_iopub_msg(timeout=1)
        except Exception:
            continue
        if message["msg_type"] == "stream":
            for line in message["content"]["text"].splitlines():
                if line.startswith("MAGICS"):
                    assert line.strip() == "MAGICS True", (
                        "ce n'est PAS un noyau spyder-kernels : "
                        "la magie %runfile est absente")
                    return
    raise AssertionError("le noyau n'a pas repondu au controle de type")
