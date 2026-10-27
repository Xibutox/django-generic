# POL-06 Politique de journalisation et de surveillance

| | |
| --- | --- |
| Code | POL-06 |
| Version | 1.0 |
| Propriétaire | Responsable de la sécurité des systèmes d'information (RSSI) |
| Approuvée par | [Nom, fonction, date] |
| Revue | Tous les 12 mois |
| ISO/IEC 27001:2022 | 8.15, 8.16, 8.17, 8.10, 5.28 ; RGPD art. 5(1)(e), 30, 33 |
| S'applique à | Toute application construite sur django-generic, applications ISO comprises |

> **Mode d'emploi.** Ce document dit ce qu'une application django-generic
> enregistre, où, combien de temps et qui le lit. Le texte entre
> [crochets] est à compléter par l'organisme. Les valeurs sont celles du
> projet d'exemple ; un projet qui change ses réglages modifie ce
> document.

## 1. Objet

Garder une trace fiable de qui a fait quoi dans l'application, repérer
une activité anormale, disposer des preuves qu'une enquête sur un
incident demande, et ne pas garder les données personnelles des
journaux plus longtemps que nécessaire.

## 2. Ce qui est enregistré

L'application tient cinq enregistrements. Aucun n'a besoin d'être
déclaré, sauf le journal des accès, qu'une ressource active.

| Enregistrement | Contenu | Où le lire |
| --- | --- | --- |
| **Historique des fiches** | Chaque création, modification et suppression de chaque modèle enregistré - qui, quand, d'où (une page, une tâche, un import), chaque version en entier. Comptes, groupes et permissions compris. Les écritures en masse (`update()`, `bulk_create()`) sont enregistrées aussi ; sous PostgreSQL, un déclencheur de la base enregistre en plus les écritures faites hors de l'application (par `psql`, un autre programme), au nom du rôle de la base | L'onglet *Historique* d'une fiche ; *Historique > Modifications* |
| **Événements de sécurité** | `signed_in`, `sign_in_failed`, `locked_out`, `signed_out`, `password_changed`, `token_created`, `token_deleted`, `access_granted`, `access_refused`, `exported` - avec le compte, l'adresse vue par le serveur, le navigateur, l'heure | *Historique > Événements de sécurité* ; le journal `generic.security` |
| **Journal des accès** | Qui a ouvert la page d'une fiche (une fois toutes les dix minutes par personne et par fiche) et qui a téléchargé quel fichier, sur les ressources qui le demandent - dans les applications ISO, les preuves d'un incident | *Historique > Journal des accès* ; le lien *Journal des accès* de la fiche |
| **Journal applicatif** | Chaque erreur inattendue avec sa trace, les événements de sécurité, les tâches, à partir du niveau `INFO` | La sortie standard (`docker compose logs`), et le fichier `/app/logs/app.log` en production |
| **E-mails d'erreur** | Chaque erreur de niveau `ERROR` envoyée à `ADMINS` quand `DEBUG` est désactivé - la même erreur une fois toutes les 10 minutes au plus, l'e-mail suivant disant combien ont été retenues | La boîte des administrateurs |

Le mot de passe saisi n'est jamais enregistré, ni les empreintes des
mots de passe, ni la date de dernière connexion dans l'historique d'un
compte.

Ce qui n'est **pas** enregistré : copier ou imprimer un tableau (fait
dans le navigateur, sur des lignes déjà affichées), et une fiche
simplement listée dans un tableau.

## 3. Qui peut lire les enregistrements

| Enregistrement | Permission |
| --- | --- |
| L'onglet Historique d'une fiche | Qui peut consulter cette fiche - il ne montre que les champs de cette fiche, et masque ceux que le lecteur n'a pas le droit de voir |
| *Historique > Modifications* | `generic.view_historyentry` |
| *Historique > Événements de sécurité* | `generic.view_securityevent` |
| *Historique > Journal des accès* | `generic.view_accessentry` |
| Journal applicatif et e-mails | Ceux qui accèdent au serveur [et à la boîte de `DJANGO_ADMINS`] |

Ces permissions ne sont dans aucun groupe créé par les démonstrations.
Elles sont données à [le RSSI et l'auditeur interne], nommément
(POL-03).

## 4. Protection des enregistrements

- Personne n'ajoute ni ne modifie une entrée d'historique, un événement
  de sécurité ou une entrée du journal des accès depuis les écrans ; les
  entrées du journal des accès ne peuvent pas non plus y être supprimées.
- **Limite :** un titulaire de `generic.delete_historyentry` ou de
  `generic.delete_securityevent` - tout super-utilisateur - peut
  supprimer des entrées d'historique ou des événements de sécurité
  depuis les écrans *Historique*, et cette suppression ne laisse aucune
  entrée. En conséquence :
  - ces deux permissions ne sont données à personne ; les
    super-utilisateurs sont peu nombreux et revus (POL-03) ;
  - le journal applicatif, qui porte chaque événement de sécurité sous
    forme d'une ligne écrite sur le moment, est copié hors du serveur
    [vers le collecteur de journaux / SIEM nommé ici], où l'application
    ne peut pas le modifier ;
  - [sous PostgreSQL, l'audit propre à la base (`pgaudit`) couvre ce
    que fait un administrateur de la base].
- Chaque entrée garde le nom de la personne tel qu'il était : la trace
  reste lisible après la suppression d'un compte.
- L'adresse enregistrée est celle que le serveur a vue (`REMOTE_ADDR`),
  jamais un en-tête qu'un client peut écrire. Derrière le proxy, c'est
  le proxy qui la fixe.

## 5. Horloges

Chaque enregistrement est stocké en UTC et affiché dans le fuseau du
lecteur (`USE_TZ = True` ; `TIME_ZONE = "Europe/Paris"` dans l'exemple).
Les conteneurs lisent l'horloge de l'hôte qui les exécute : c'est elle
qu'il faut tenir juste. [Les hôtes se synchronisent sur le ou les
serveurs NTP ... .]

## 6. Conservation

Les enregistrements contiennent des données personnelles (noms,
adresses) : chacun est conservé une durée fixée, puis supprimé par
`manage.py apply_retention` (ou la tâche gérée
`generic.apply_retention`), planifiée chaque jour.

| Enregistrement | Réglage | Projet d'exemple | [Organisme] |
| --- | --- | --- | --- |
| Historique | `HISTORY_RETENTION_DAYS` | conservé (None) | [conservé pendant la vie des fiches / N ans] |
| Journal des accès | `ACCESS_LOG_RETENTION_DAYS` | 365 jours | [365 jours - CNIL : 6 mois à 1 an] |
| Événements de sécurité | `SECURITY_LOG_RETENTION_DAYS` | conservés (None) | [365 jours] |
| Notifications | `EVENTS_RETENTION_DAYS` | 90 jours | [90 jours] |
| Fichier du journal applicatif | `logging_config(max_bytes, backups)` | 5 fichiers de 10 Mo | [et la conservation du collecteur] |

`None` conserve tout. Chaque suppression est elle-même journalisée
(`generic.retention`). Les durées choisies sont inscrites au registre
des traitements (RGPD).

## 7. Surveillance

| Quoi | Comment | Qui | Quand |
| --- | --- | --- | --- |
| Erreurs | E-mails à `DJANGO_ADMINS` ; `check --deploy` avertit tant que la liste est vide | [Exploitation] | À réception |
| Santé du serveur | *Supervision > État du serveur* (`generic.view_status`) : processeurs, mémoire, disques, base, cache, Celery, migrations, tâches en échec sur 24 heures ; les contrôles de santé de la pile de production | [Exploitation] | [Chaque jour] |
| Échecs de connexion et verrouillages | *Événements de sécurité*, filtrés sur `sign_in_failed` et `locked_out` ; lignes `WARNING` du journal | [RSSI] | [Chaque semaine] |
| Exports | *Événements de sécurité*, filtrés sur `exported` : qui a exporté quel tableau, combien de lignes | [RSSI / propriétaire des données] | [Chaque mois] |
| Droits accordés | *Événements de sécurité* `access_granted`, *Personnes > Demandes d'accès* | [RSSI] | [Chaque mois] |
| Modifications des comptes et des groupes | *Historique > Modifications*, filtré sur les modèles utilisateur et groupe | [RSSI] | [Chaque mois, et à la revue des accès] |
| Téléchargements des preuves | *Historique > Journal des accès* | [Responsable des incidents] | Pendant un incident |

Toute anomalie - une rafale d'échecs, un export que personne
n'attendait, un droit donné hors procédure - est déclarée comme
événement de sécurité dans `iso.incidents` (POL-08).

## 8. Réglages obligatoires en production

- `generic.middleware.CurrentUserMiddleware` après le middleware
  d'authentification : sans lui, l'historique enregistre ce qui a changé,
  pas qui l'a changé.
- `GENERIC["SECURITY_LOG"]` laissé à `True` (la valeur par défaut).
- `LOGGING = logging_config(...)` avec un fichier, et `ADMINS` renseigné.
- `apply_retention` planifié.
- Sous PostgreSQL, `HISTORY_TRIGGERS` laissé à sa valeur par défaut.
- Un cache partagé (Redis) quand il y a plusieurs processus, pour que le
  verrouillage des connexions compte chaque tentative.

## 9. Revue de cette politique

À chaque revue, vérifier que les réglages de la section 8 sont toujours
ceux de l'application en service (`manage.py check --deploy`), que la
copie des journaux arrive toujours hors du serveur, et que les durées
de conservation correspondent toujours au registre des traitements.
