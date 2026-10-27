# POL-03 Politique de contrôle d'accès et procédure de gestion des accès utilisateurs

| | |
| --- | --- |
| Code | POL-03 |
| Version | 1.0 |
| Propriétaire | Responsable de la sécurité des systèmes d'information (RSSI) |
| Approuvée par | [Nom, fonction, date] |
| Revue | Tous les 12 mois, et après tout changement des rôles ci-dessous |
| ISO/IEC 27001:2022 | 5.15, 5.16, 5.17, 5.18, 8.2, 8.3, 8.5 ; clause 7.5 |
| S'applique à | Toute application construite sur django-generic, applications ISO comprises |

> **Mode d'emploi.** Ce document décrit comment une application
> django-generic gère réellement les comptes, les groupes et les
> permissions : ce qui est écrit est ce que fait le logiciel. Le texte
> entre [crochets] est à compléter par l'organisme. Les réglages cités
> sont ceux du projet d'exemple (`example_project/settings/base.py`) ;
> un projet qui les change modifie aussi ce document.

## 1. Objet

Donner à chacun les accès dont son poste a besoin, et pas davantage,
garder la trace de qui a reçu quoi et de qui l'a donné, et retirer un
accès dès qu'il n'est plus nécessaire.

## 2. Principes

1. **Besoin d'en connaître, moindre privilège.** Un compte naît sans
   aucune permission. Les droits sont ajoutés pour un poste, jamais
   « au cas où ».
2. **Les droits vont aux groupes, pas aux personnes.** Un groupe est un
   poste (*Security officers*, *Auditors*, *Agents du support*...). Une
   personne reçoit les droits des postes qu'elle occupe en étant placée
   dans les groupes. Une permission donnée directement à un compte est
   l'exception, consignée avec sa raison.
3. **Une personne, un compte.** Les comptes sont nominatifs et jamais
   partagés. Un script utilise le jeton d'API d'une personne nommée, pas
   un mot de passe partagé.
4. **Séparation des tâches.** Personne n'approuve, ne vérifie ni ne
   revoit son propre travail (section 6).
5. **Les accès à privilèges sont rares et revus.** Les super-utilisateurs
   et les comptes « équipe » sont réduits au minimum [indiquer le
   nombre] et revus tous les [3] mois.
6. **Tout est tracé.** Chaque modification d'un compte, d'un groupe ou
   d'une permission est conservée dans l'historique de l'application,
   avec son auteur et sa date.

## 3. Fonctionnement des accès dans l'application

### 3.1 Les comptes

Les comptes de l'application sont les utilisateurs de Django. Ils se
gèrent sur le site lui-même, sous **Personnes > Utilisateurs** (et non
dans `/admin/` de Django) :

| Champ | Signification |
| --- | --- |
| Nom d'utilisateur, nom, e-mail | Qui est le titulaire du compte |
| Actif | Décoché : le compte ne peut plus se connecter, ses jetons d'API sont refusés, ses sessions ouvertes s'arrêtent à leur requête suivante. Son historique reste |
| Statut équipe | Ouvre `/admin/` de Django (voir 3.6) |
| Statut super-utilisateur | Détient toutes les permissions sans qu'on les lui donne |
| Groupes | Les postes occupés |
| Permissions de l'utilisateur | Droits donnés directement, en plus de ceux des groupes |

Les écrans **Utilisateurs**, **Groupes** et **Permissions** ne sont
montrés qu'aux titulaires de `auth.view_user` et `auth.view_group`.
L'écran **Permissions** est en lecture seule : les permissions sont
déclarées par le code, jamais créées à la main.

### 3.2 Les permissions

Chaque écran et chaque point d'API est protégé par les **permissions de
modèle** de Django, vérifiées par le serveur à chaque requête - masquer
un bouton n'est jamais la protection :

| Permission | Donne |
| --- | --- |
| `<app>.view_<model>` | La liste, la page de la fiche, ses exports et son onglet Historique |
| `<app>.add_<model>` | Le formulaire de création et la création de fiches |
| `<app>.change_<model>` | La modification, l'édition dans le tableau, la modification en masse, les actions qui modifient (pouvoir modifier permet de consulter) |
| `<app>.delete_<model>` | La suppression |

Une personne non connectée n'obtient rien : chaque point d'API refuse
une requête anonyme.

Au-delà des quatre permissions par modèle, certaines actions ont la
leur. Dans les applications ISO :

| Permission | Donne |
| --- | --- |
| `risks.accept_risk` | Accepter un risque résiduel (le propriétaire du risque) |
| `changes.approve_changerequest` | Approuver ou rejeter une demande de changement |
| `<app>.customize_<model>` | Ajouter des champs personnalisés à une liste |

Et dans le framework :

| Permission | Donne |
| --- | --- |
| `generic.view_historyentry` | *Historique > Modifications* : toutes les modifications enregistrées, de tous les modèles |
| `generic.view_securityevent` | *Historique > Événements de sécurité* : connexions, échecs, verrouillages, exports |
| `generic.view_accessentry` | *Historique > Journal des accès* : qui a ouvert quelle fiche, téléchargé quel fichier |
| `generic.export_rows`, `generic.download_files` | Exporter les tableaux, télécharger les fichiers, quand le projet en fait des droits sur demande (3.4) |
| `generic.validate_accessrequest` | Décider des demandes de ces droits |
| `generic_tokens.add_apitoken` | Créer des jetons d'API personnels (3.5) |
| `generic_tokens.view_apitoken`, `generic_tokens.delete_apitoken` | Voir et révoquer les jetons de tous |
| `generic.view_status` | *Supervision > État du serveur* |
| `generic.add_restartannouncement` | Annoncer un redémarrage planifié |

### 3.3 Plus fin qu'un modèle

- **Champs.** Une ressource peut restreindre un seul champ
  (`field_permissions`) : un coût que seuls les acheteurs voient, une
  date que seul un responsable modifie. Un champ masqué disparaît de la
  liste, du formulaire, des exports, des filtres, des graphiques et de
  l'onglet Historique de qui n'a pas le droit de le voir.
- **Équipes.** Avec `generic.teams` installé, les fiches peuvent
  appartenir à des équipes : une personne ne voit alors que les fiches
  de ses équipes, partout - listes, recherches, exports, formulaires,
  fichiers. Les groupes disent ce qu'une personne peut *faire*, les
  équipes *sur quelles fiches*. `generic_teams.see_every_team` lève la
  restriction ; ne la donner qu'aux responsables.
- **Fichiers.** Une ressource peut refuser un champ fichier à un lecteur
  qui voit pourtant la fiche (`may_download`).

### 3.4 Les droits sur demande

Un projet peut faire de l'export et du téléchargement des droits que
l'on demande (`GENERIC["ACCESS_ON_REQUEST"] = ("export", "download")`,
comme le projet d'exemple). Qui n'a pas le droit trouve *Demander la
permission d'exporter* à la place de l'export, *Demander à télécharger*
à la place du fichier ; la demande (qui, quoi, pourquoi, depuis quelle
page) part aux super-utilisateurs et aux titulaires de
`generic.validate_accessrequest`, qui l'accordent ou la refusent sous
*Personnes > Demandes d'accès*. Personne ne décide de sa propre demande.
Chaque décision est un événement de sécurité (`access_granted`,
`access_refused`). Un rappel peut aussi être affiché, et coché, avant
chaque export et chaque téléchargement (`EXPORT_DISCLAIMER`,
`DOWNLOAD_DISCLAIMER`).

### 3.5 Les jetons d'API

Un jeton permet à un script d'appeler l'API **avec exactement les
permissions de son titulaire**. Il est créé par son titulaire sur sa
page de compte, affiché une seule fois, et seule son empreinte est
conservée. Par défaut : valable 90 jours, 365 au plus
(`API_TOKEN_DEFAULT_DAYS`, `API_TOKEN_MAX_DAYS`), 10 par personne au
plus, *lecture seule* sauf si *lecture et écriture* est choisi. Créer
des jetons demande `generic_tokens.add_apitoken`, que seuls les
super-utilisateurs détiennent tant qu'elle n'est pas donnée à un groupe.
Les jetons des comptes inactifs, expirés ou révoqués sont refusés. La
création et la révocation d'un jeton sont des événements de sécurité.

### 3.6 La règle qui protège les écrans Personnes

Qui peut modifier les comptes pourrait sinon se donner n'importe quoi.
Les écrans Personnes le refusent, sur une seule règle : **ce que l'on
accorde, il faut déjà l'avoir** (`generic/accounts/guard.py`). Pour qui
n'est pas super-utilisateur :

| Tentative | Résultat |
| --- | --- |
| Cocher *super-utilisateur* | Refusé |
| Cocher *équipe* sans l'être soi-même | Refusé |
| Ajouter un groupe, ou une permission, qui accorde ce que l'on n'a pas | Refusé, avec le nom de la permission |
| Donner à un groupe une permission que l'on n'a pas | Refusé |
| Ouvrir le formulaire d'un super-utilisateur, pour le modifier ou le supprimer | Refusé : changer son mot de passe ferait de soi ce super-utilisateur |

Pour tous, super-utilisateurs compris : personne ne supprime ni ne
désactive le compte avec lequel il est connecté.

**`/admin/` de Django n'applique pas cette règle** : un compte équipe
qui y détient `auth.change_user` peut cocher *super-utilisateur*. Le
statut équipe est donc un droit à privilèges [donné aux seuls
administrateurs nommés en section 4 / donné à personne].

### 3.7 L'authentification

| Mesure | Valeur dans le projet d'exemple | Réglage |
| --- | --- | --- |
| Règles de mot de passe | Les quatre validateurs de Django : pas ressemblant au nom du compte, une longueur minimale, pas un mot de passe courant, pas uniquement des chiffres [projets créés par `scripts/new_project.py` : 12 caractères minimum] | `AUTH_PASSWORD_VALIDATORS` |
| Stockage des mots de passe | Argon2 (quand l'extra `argon2` est installé), jamais en clair, jamais renvoyé par l'API, jamais conservé dans l'historique | `PASSWORD_HASHERS` |
| Verrouillage | 5 échecs de suite sur un compte le verrouillent 15 minutes, sans même vérifier le mot de passe ; une adresse qui échoue sur n'importe quels comptes est verrouillée après 20 | `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES` |
| Durée de session | 8 heures au plus | `SESSION_COOKIE_AGE` |
| Déconnexion pour inactivité | Après 60 minutes sans clic ni frappe | `SESSION_IDLE_MINUTES` |
| Cookies | Sécurisés et HTTP-only en HTTPS en production | `settings/prod.py` |
| Authentification unique (SSO) | Optionnelle : un fournisseur (Entra ID, une bibliothèque OIDC ou SAML) mène la page de connexion ; les mots de passe locaux peuvent être interdits (`SSO_PASSWORD_LOGIN = False`). Le second facteur du fournisseur s'applique à ses connexions | `SSO_PROVIDERS` |

[Si l'organisme exige l'authentification multifacteur, elle s'obtient
par le fournisseur d'authentification unique : le formulaire de mot de
passe du framework n'a pas de second facteur.]

## 4. Rôles

| Rôle | Détient | Qui |
| --- | --- | --- |
| Super-utilisateur | Tout | [2 administrateurs nommés au plus ; leurs comptes servent uniquement à l'administration] |
| Administrateur des accès | `auth.view_user`, `auth.add_user`, `auth.change_user`, `auth.view_group`, `auth.change_group`, et seulement les droits qu'il peut distribuer | [Responsable informatique] |
| Validateur des demandes de droits | `generic.validate_accessrequest` | [Propriétaire des données / RSSI] |
| Réviseur des accès | `access_reviews.*` | [RSSI] |
| Auditeur (lecture) | Le groupe *Auditors* | [Auditeur interne] |

La démonstration des applications ISO (`manage.py seed_iso`) crée deux
groupes comme point de départ :

| Groupe | Permissions |
| --- | --- |
| *Security officers* | Toutes les permissions des applications ISO installées |
| *Auditors* | Lire toutes les fiches ISO (`view_*`), et toutes les permissions de `iso.audits` (enregistrer audits, constats, actions correctives) |

Les personnes hors de ces groupes (dans la démonstration, `dev` et
`sales`) ne voient aucun écran ISO. Aucun des deux groupes ne lit
*Historique > Modifications*, les événements de sécurité ni le journal
des accès : ces droits se donnent délibérément, un par un
(`generic.view_historyentry`, `generic.view_securityevent`,
`generic.view_accessentry`).

[Ajouter ici les groupes propres à l'organisme et l'usage de chacun.]

## 5. Procédure

### 5.1 Arrivée d'une personne (enregistrement, attribution)

1. Le responsable demande le compte [par ticket / par e-mail à
   l'administrateur des accès], en indiquant le poste de la personne.
2. L'administrateur des accès vérifie que le dossier du personnel est
   prêt (`iso.people` : vérification préalable, conditions d'emploi et
   accord de confidentialité signés).
3. Il crée le compte sous **Personnes > Utilisateurs** : nom
   d'utilisateur, nom, e-mail, *Actif* coché, les **groupes** du poste.
   Aucune permission directe sauf si la demande en donne la raison.
   - Avec l'authentification unique, le compte est créé à la première
     connexion par la bibliothèque du fournisseur, avec le groupe décidé
     là ; laisser le mot de passe vide - le compte n'a alors pas de mot
     de passe utilisable.
   - Sinon, définir un mot de passe provisoire que la personne change
     sur sa page de compte à la première connexion.
4. La personne prend connaissance des politiques qui l'exigent
   (*Politiques > Prendre connaissance*, `iso.isms`).

L'historique du compte garde qui l'a créé, avec quels groupes, quand.

### 5.2 Changement de poste (modification)

1. Le responsable demande le changement.
2. L'administrateur des accès **ajoute les groupes du nouveau poste et
   retire ceux de l'ancien** dans la même modification. Les droits qui
   ne servent plus partent tout de suite, pas à la revue suivante.
3. Les permissions données directement sont revues en même temps.

### 5.3 Départ d'une personne (retrait)

1. Le dernier jour [ou avant, pour un licenciement], l'administrateur
   des accès **désactive** le compte (décocher *Actif*, ou l'action
   groupée *Désactiver*). Les comptes sont désactivés, pas supprimés :
   leur historique et les fiches qu'ils ont signées restent lisibles.
2. Ses jetons d'API sont révoqués (*Personnes > Jetons d'API*) ; ceux
   d'un compte désactivé sont refusés de toute façon.
3. Le dossier du personnel enregistre la date du retrait des accès et
   de la restitution des actifs (`iso.people`, `iso.assets`).
4. Avec l'authentification unique, le compte est aussi désactivé chez
   le fournisseur.

### 5.4 Droits exceptionnels

Un droit temporaire (un export pour un audit, un téléchargement) se
demande par *Demander la permission* (3.4), pour que la demande, sa
raison et sa décision soient conservées. Il est retiré quand il ne sert
plus, en enlevant la permission du compte.

### 5.5 Comptes à privilèges

- Les super-utilisateurs sont créés par une personne, sur le serveur
  (`manage.py createsuperuser`), jamais par un script avec un mot de
  passe connu. Les comptes de démonstration (`seed_iso`,
  `seed_example`, mot de passe `demo`) n'existent jamais en production.
- Un compte super-utilisateur ne sert pas au travail quotidien :
  l'administrateur a un second compte, ordinaire.
- Le statut équipe n'est donné qu'avec une raison (3.6).

### 5.6 Revue périodique des droits d'accès

Tous les [6] mois pour tous les comptes, tous les [3] mois pour les
comptes à privilèges, avec `iso.access_reviews` :

1. Créer une revue des accès : périmètre *Tous les comptes actifs*,
   *Comptes à privilèges uniquement* (super-utilisateurs et équipe) ou
   *Membres d'un groupe* ; un réviseur ; une échéance.
2. **Collecter les comptes** : chaque compte du périmètre est copié tel
   qu'il est - groupes, nombre de permissions, super-utilisateur,
   équipe, dernière connexion.
3. Le réviseur décide de chaque compte : *Conserver*, *Révoquer* ou
   *Modifier les droits*. Chaque décision garde son auteur et sa date.
   **Personne ne décide de son propre compte.**
4. **Appliquer les décisions** : les comptes décidés *Révoquer* sont
   désactivés. Appliquer demande aussi `auth.change_user`, ne touche
   jamais le compte du réviseur, et seul un super-utilisateur désactive
   un super-utilisateur. *Modifier les droits* se fait à la main sous
   **Personnes > Utilisateurs** (l'historique l'enregistre).
5. Terminer la revue avec sa conclusion. La campagne, avec chaque
   décision, est la preuve du contrôle 5.18.

Regarder en particulier les comptes sans connexion depuis [90] jours,
les permissions directes et les membres des groupes à privilèges.

## 6. Séparation des tâches imposée par le logiciel

| Règle | Où |
| --- | --- |
| Personne n'approuve ni ne rejette sa propre demande de changement | `iso.changes` |
| Personne ne vérifie sa propre action corrective | `iso.audits` |
| Personne ne décide de son propre compte dans une revue des accès | `iso.access_reviews` |
| Personne ne décide de sa propre demande de droit | le framework (3.4) |
| Personne n'accorde ce qu'il ne détient pas | les écrans Personnes (3.6) |

## 7. Enregistrements

| Enregistrement | Où | Qui le lit |
| --- | --- | --- |
| Chaque modification d'un compte, d'un groupe, d'une permission : qui, quand, avant, après (mots de passe et dernière connexion exclus) | L'onglet *Historique* de la fiche ; *Historique > Modifications* | Titulaires de `auth.view_user` / `auth.view_group` ; `generic.view_historyentry` |
| Connexions, échecs, verrouillages, déconnexions, changements de mot de passe, jetons créés et révoqués, droits accordés et refusés, exports | *Historique > Événements de sécurité*, et le journal `generic.security` | `generic.view_securityevent` |
| Demandes de droits et leurs décisions | *Personnes > Demandes d'accès* | `generic.validate_accessrequest`, `generic.view_accessrequest` |
| Revues des accès et leurs décisions | `iso.access_reviews` | Les *Security officers*, les *Auditors* |
| Prises de connaissance des politiques | `iso.isms` | Les mêmes |

## 8. Ce que le logiciel ne fait pas

- Décider qui a besoin de quoi : cette politique et les responsables le
  font.
- Faire expirer un compte à une date : la désactivation est faite par
  une personne, le jour même (5.3).
- L'authentification multifacteur sur son propre formulaire de mot de
  passe : passer par l'authentification unique (3.7).
- Protéger contre un super-utilisateur : il peut tout, y compris
  supprimer des entrées de l'historique (POL-06). Les garder peu
  nombreux, nommés et revus.
- Appliquer la règle des écrans Personnes dans `/admin/` de Django
  (3.6).
