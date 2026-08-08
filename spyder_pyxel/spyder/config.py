# -*- coding: utf-8 -*-
"""Configuration des deux greffons Pyxel.

Il n'y a rien a regler : les panneaux ne sont que des afficheurs, tout se lance depuis la
console. Les sections restent declarees parce que Spyder en exige une par greffon quand
CONF_FILE vaut True (spyder/config/manager.py, register_plugin), et parce qu'elles
accueillent l'option "<greffon>/enable" par laquelle on desactive un greffon tiers depuis
Preferences > Plugins.
"""

GAME_CONF_SECTION = "pyxel_game"
STUDIO_CONF_SECTION = "pyxel_studio"

# ⚠ NE JAMAIS laisser le dictionnaire d'options VIDE. Un greffon declare avec
# [(section, {})] fait echouer le chargement de la configuration de Spyder au demarrage,
# avec la boite "Une erreur s'est produite lors du chargement des options de configuration
# de Spyder. Vous devez les reinitialiser" - et le seul bouton propose efface TOUTE la
# configuration de l'utilisateur, disposition des panneaux comprise. Constate en direct le
# 20/07/2026 apres la suppression des options du greffon en meme temps que ses boutons.
# On garde donc une option, reellement lue par le panneau : restreindre l'agrandissement
# a un facteur entier (pixels rigoureusement identiques, mais marges perdues) au lieu
# d'occuper tout le panneau, qui est le comportement par defaut.
GAME_CONF_DEFAULTS = [(GAME_CONF_SECTION, {"integer_scaling": False})]
STUDIO_CONF_DEFAULTS = [(STUDIO_CONF_SECTION, {"integer_scaling": False})]

# Regles de numerotation (identiques a celles des greffons livres avec Spyder) : changer
# la valeur par defaut d'une option => version MINEURE ; supprimer ou renommer une option
# => version MAJEURE ; ajouter une option => rien a faire.
# 2.0.0 : les options "run_on_save" et le raccourci F7 ont disparu avec les boutons.
# 2.1.0 : integer_scaling passe de True a False (l'image occupe tout le panneau).
#         ⚠ Sans cette montee de version, Spyder GARDE la valeur deja enregistree
#         dans ~/.config/spyder-py3/plugins/<section>/spyder.ini et le nouveau
#         defaut reste sans effet - constate en direct le 21/07/2026.
# ⚠ Le numero ne revient JAMAIS en arriere : Spyder compare la version stockee a celle-ci
# et une version plus ancienne que celle deja enregistree le fait echouer au chargement.
CONF_VERSION = "2.1.0"
