# -*- coding: utf-8 -*-
"""
Fonction de traduction du greffon.

`spyder.api.translations.get_translation("spyder_pyxel")` marcherait aussi, mais tant
qu'aucun catalogue .mo n'est fourni elle affiche a chaque import "Could not load
translations for fr ... No translation file found for domain: 'spyder_pyxel'" - soit
trois lignes de bruit dans la console a chaque demarrage de Spyder (c'est ce que fait
spyder_line_profiler, et cela se voit).

Les libelles de ce greffon sont ecrits directement en francais, la langue de cette
installation. On garde donc l'habillage `_(...)`, qui permettra d'ajouter un catalogue
plus tard sans toucher au reste du code, mais sans en promettre un aujourd'hui.
"""


def _(message):
    return message
