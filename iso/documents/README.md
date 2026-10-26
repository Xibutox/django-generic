# Policies and procedures / Politiques et procédures

The documents an ISO/IEC 27001 auditor asks for where the software is
involved, written from what django-generic and the ISO apps actually
do: who manages accounts and how, what is logged, how backups and
changes work. Each is in English (`en/`) and French (`fr/`), with the
same file name.

Les documents qu'un auditeur ISO/IEC 27001 demande là où le logiciel
intervient, écrits d'après ce que font réellement django-generic et les
applications ISO : qui gère les comptes et comment, ce qui est
journalisé, comment fonctionnent les sauvegardes et les changements.
Chacun existe en anglais (`en/`) et en français (`fr/`), sous le même
nom de fichier.

| Code | File / Fichier | English | Français | Annex A |
| --- | --- | --- | --- | --- |
| POL-03 | `access-control.md` | Access control policy and user access management procedure | Politique de contrôle d'accès et procédure de gestion des accès utilisateurs | 5.15-5.18, 8.2, 8.3, 8.5 |
| POL-04 | `backup.md` | Backup and restore policy | Politique de sauvegarde et de restauration | 8.13, 8.14, 5.29, 5.30 |
| POL-06 | `logging-and-monitoring.md` | Logging and monitoring policy | Politique de journalisation et de surveillance | 8.15, 8.16, 8.17, 8.10 |
| POL-07 | `change-management.md` | Change management procedure | Procédure de gestion des changements | 8.32, 5.3, 8.9, 8.31 |
| POL-08 | `incident-management.md` | Information security incident management procedure | Procédure de gestion des incidents de sécurité de l'information | 5.24-5.28, 6.8 |
| POL-09 | `vulnerability-management.md` | Technical vulnerability management procedure | Procédure de gestion des vulnérabilités techniques | 8.8, 8.19 |

## Using them / Les utiliser

- They are **templates**: text in [brackets] - names, periods,
  addresses - is the organisation's to fill in, then the document is
  approved and versioned in *Policies* (`iso.isms`).
- Ce sont des **modèles** : le texte entre [crochets] - noms, durées,
  adresses - est à compléter par l'organisme, puis le document est
  approuvé et versionné dans *Politiques* (`iso.isms`).
- `python manage.py seed_iso` attaches them to the demo policies
  POL-03, POL-04 and POL-06 to POL-09, in English; `seed_iso --language
  fr` in French. A policy that already has a document keeps it.
- `python manage.py seed_iso` les joint aux politiques de démonstration
  POL-03, POL-04 et POL-06 à POL-09, en anglais ; `seed_iso --language
  fr` en français. Une politique qui a déjà un document le garde.

## Keeping them true / Les garder exacts

They quote settings, permissions and screens. A change to one of those
in the framework or in a project changes the document in the same
commit; `tests/test_iso.py` checks that every permission they name
exists and that both languages hold the same documents.

Ils citent des réglages, des permissions et des écrans. Modifier l'un
d'eux, dans le framework ou dans un projet, modifie le document dans le
même commit ; `tests/test_iso.py` vérifie que chaque permission citée
existe et que les deux langues ont les mêmes documents.
