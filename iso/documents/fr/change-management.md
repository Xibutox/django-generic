# POL-07 Procédure de gestion des changements

| | |
| --- | --- |
| Code | POL-07 |
| Version | 1.0 |
| Propriétaire | Responsable informatique |
| Approuvée par | [Nom, fonction, date] |
| Revue | Tous les 12 mois |
| ISO/IEC 27001:2022 | 8.32, 5.3, 8.9, 8.25, 8.29, 8.31 ; clause 6.3 |
| S'applique à | Les changements des applications construites sur django-generic, de leur configuration, de leurs serveurs et de leur modèle de données |

> **Mode d'emploi.** Ce document décrit comment les changements sont
> demandés, approuvés, réalisés et revus, avec `iso.changes` et les
> outils que fournit le dépôt. Le texte entre [crochets] est à compléter
> par l'organisme.

## 1. Objet

Aucun changement n'arrive en production sans avoir été décrit, évalué,
testé, approuvé par quelqu'un d'autre que son auteur, et revu ensuite -
et chaque étape laisse une trace.

## 2. Qu'est-ce qu'un changement

| Type | Exemples | Approbation |
| --- | --- | --- |
| **Normal** | Une nouvelle version de l'application, une nouvelle application installée, un changement de réglage, une migration de la base, un nouveau serveur | Un titulaire de `changes.approve_changerequest`, jamais le demandeur |
| **Standard** (pré-approuvé) | [Appliquer les correctifs de sécurité des images de base (`build --pull`), ajouter un utilisateur à un groupe selon POL-03] | Listés ici ; enregistrés comme demande de changement de type *Standard*. L'application ne saute pas l'étape d'approbation pour eux : l'approbateur approuve sur simple lecture |
| **Urgence** | Le correctif d'une vulnérabilité exploitée, la remise en service | Approuvé [par le RSSI ou le responsable informatique, par téléphone au besoin], enregistré aussitôt, revu ensuite |

Les changements de **droits** (comptes, groupes, permissions) suivent
POL-03, pas cette procédure : ils sont enregistrés dans l'historique du
compte ou du groupe.

## 3. Les étapes, dans `iso.changes`

| Étape | Qui | Dans l'application |
| --- | --- | --- |
| 1. Demande | Le demandeur | Une demande de changement (CHG-0001...) : titre, type, catégorie, description, raison, les actifs concernés, le risque (faible, moyen, élevé) et l'impact, le **plan de test** et le **plan de retour arrière**, l'exécutant et les dates prévues. Le demandeur est enregistré par l'application |
| 2. Soumettre | Le demandeur | *Soumettre* : la demande attend dans la vue *En attente d'approbation* |
| 3. Approuver ou rejeter | Un approbateur, pas le demandeur | *Approuver* ou *Rejeter*, qui gardent le nom de l'approbateur et l'heure. Le bouton n'est pas proposé au demandeur, et le serveur le refuse |
| 4. Réaliser | L'exécutant | Le travail, dans le créneau prévu (*Calendrier des changements*), puis *Mise en œuvre*, qui enregistre l'heure |
| 4'. Revenir en arrière | L'exécutant | En cas d'échec : le plan de retour arrière, puis *Échec, retour arrière* |
| 5. Revue | Le demandeur ou l'approbateur | Le champ revue : cela a-t-il marché, qu'en retient-on ; puis *Clôturer* |

Le statut n'avance que par ces boutons : il ne se saisit pas dans le
formulaire. Chaque étape figure dans l'historique de la demande.

## 4. Une nouvelle version de l'application

Le code est dans git ; le modifier, c'est un commit, relu et testé avant
d'être déployé.

1. **Développer** sur une branche, dans l'environnement de développement
   (`example_project.settings.dev`, `docker/docker-compose.dev.yml`),
   jamais sur des données de production.
2. **Relire** : une pull request, lue par [quelqu'un d'autre que son
   auteur].
3. **Tester** : l'intégration continue tourne à chaque envoi. Celle de
   django-generic (`.github/workflows/ci.yml`) passe black, isort,
   flake8, bandit, pip-audit, mypy, les tests avec un seuil de
   couverture de 80 %, l'intégration PostgreSQL et Redis, les tests dans
   le navigateur, la construction du paquet et les piles Docker ; celle
   d'un projet passe au moins ses tests et les mêmes linters.
   [La protection de branche exige une intégration continue au vert
   pour fusionner.]
4. **Demande de changement** : une par déploiement, avec le lien des
   pull requests et les notes de version (`CHANGELOG.md`).
5. **Sauvegarder** juste avant (POL-04) quand la version migre la base.
6. **Annoncer** l'interruption : *Planifier un redémarrage* dans le menu
   du compte (`generic.add_restartannouncement`) prévient chaque personne
   connectée, dans sa langue, et redémarre le serveur à l'heure dite sauf
   si le redémarrage est manuel.
7. **Déployer** :

   ```bash
   docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env up -d --build
   ```

   Les images sont reconstruites, `migrate` tourne une fois, et le
   serveur web, le worker et le planificateur ne sont remplacés qu'une
   fois qu'elle a réussi.
8. **Vérifier** : `manage.py check --deploy` muet, *Supervision > État
   du serveur* au vert, une connexion, les écrans touchés par le
   changement.
9. **Revenir en arrière** si besoin : déployer l'étiquette précédente ;
   restaurer la sauvegarde de l'étape 5 si une migration n'est pas
   réversible.

## 5. Configuration

- Production et développement sont séparés : deux modules de réglages,
  deux piles, deux fichiers d'environnement aux secrets différents.
  `asgi.py` et `wsgi.py` partent par défaut sur la production : `DEBUG`
  n'est jamais activé par accident.
- Toute la configuration est dans git (fichiers compose, Dockerfile,
  réglages) sauf les secrets, dans `docker/prod.env`, qui n'y est jamais.
- Les systèmes de fichiers des conteneurs sont en lecture seule [dans
  les projets créés par `scripts/new_project.py`] : un serveur en
  service ne peut pas s'écarter de son image.
- Un changement d'un réglage cité dans POL-03, POL-04 ou POL-06 met ce
  document à jour dans le même changement.

## 6. Enregistrements

| Enregistrement | Où |
| --- | --- |
| Les demandes de changement, leur approbation, leur réalisation et leur revue | `iso.changes`, et l'historique de chaque demande |
| La modification du code, sa relecture et ses tests | git, la pull request, l'exécution de l'intégration continue |
| Ce qui a changé dans chaque version | `CHANGELOG.md`, affiché sous *Aide > Ce qui a changé* |
| Les données modifiées par le changement (une migration, un import) | L'historique des fiches |
| Les redémarrages planifiés | L'annonce et sa notification |

## 7. Séparation des tâches

Le demandeur et l'approbateur sont toujours deux personnes différentes :
l'application refuse l'approbation du demandeur. [Quand l'équipe est trop
petite pour cela, le RSSI approuve et la revue de direction examine les
changements qu'il a demandés.]
