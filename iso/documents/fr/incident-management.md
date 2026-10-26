# POL-08 Procédure de gestion des incidents de sécurité de l'information

| | |
| --- | --- |
| Code | POL-08 |
| Version | 1.0 |
| Propriétaire | Responsable de la sécurité des systèmes d'information (RSSI) |
| Approuvée par | [Nom, fonction, date] |
| Revue | Tous les 12 mois, et après chaque incident majeur |
| ISO/IEC 27001:2022 | 5.24, 5.25, 5.26, 5.27, 5.28, 5.5, 6.8 ; clause 10.2 ; RGPD art. 33, 34 |
| S'applique à | Tout événement qui peut toucher les informations que détient l'organisme, dans ou autour des applications construites sur django-generic |

> **Mode d'emploi.** Ce document décrit comment un événement est
> signalé, évalué, traité et analysé avec `iso.incidents`, et quels
> enregistrements de l'application une enquête utilise. Le texte entre
> [crochets] est à compléter par l'organisme.

## 1. Objet

Signaler vite chaque événement de sécurité, décider s'il s'agit d'un
incident, le contenir, conserver les preuves, prévenir à temps qui doit
l'être - l'autorité de protection des données dans les 72 heures pour
une violation de données personnelles - et en tirer les leçons.

## 2. Signaler un événement (6.8)

Chacun signale ce qu'il remarque : un e-mail d'hameçonnage, un
ordinateur perdu, une connexion étrange, des données envoyées à la
mauvaise personne, un écran qui montre ce qu'il ne devrait pas.

- **Dans l'application :** *Incidents > Ajouter*. Signaler ne demande que
  `incidents.add_incident` ; [la donner à tout le personnel par un groupe
  *Personnel*]. Qui ne détient que cette permission dépose le
  signalement mais ne peut pas lire le registre. L'application enregistre
  qui l'a signalé et quand.
- **Sinon :** [numéro de téléphone / boîte de l'équipe sécurité], quand
  l'application est inaccessible ou elle-même touchée.

Signaler tout de suite, même en cas de doute. Ne pas enquêter seul, ne
rien supprimer, ne pas prévenir la personne soupçonnée.

## 3. Rôles

| Rôle | Qui | Permissions |
| --- | --- | --- |
| Déclarant | Tout le monde | `incidents.add_incident` |
| Gestionnaire d'incident | [Responsable informatique, les *Security officers*] | Toutes les permissions `incidents.*` |
| Responsable des incidents | [RSSI] | Les mêmes, et décide des notifications |
| Délégué à la protection des données | [Nom] | Lit les violations (`incidents.view_incident`) |
| Enquêteur | [RSSI] | `generic.view_securityevent`, `generic.view_accessentry`, `generic.view_historyentry` |

## 4. Les étapes

| Étape | Statut dans `iso.incidents` | Ce qui est fait |
| --- | --- | --- |
| 1. Signalé | *Rapporté* | Le signalement : titre, catégorie (hameçonnage, logiciel malveillant, accès non autorisé, fuite de données, perte ou vol, déni de service, mauvaise configuration, physique, autre), description, date de détection, actifs touchés |
| 2. Évaluation (5.25) | *En cours d'évaluation* | Le gestionnaire décide sous [4 heures ouvrées] : un incident, ou *Pas un incident* (la raison dans la chronologie). Il fixe la **gravité** et le **gestionnaire**. Il coche **Violation de données personnelles** quand des données personnelles ont été perdues, divulguées, altérées ou rendues indisponibles |
| 3. Endiguement (5.26) | *Contenu* | Arrêter les dégâts : désactiver un compte (POL-03), révoquer ses jetons d'API, isoler une machine, changer un secret. Chaque action est une mise à jour de type *Action menée* dans la chronologie |
| 4. Résolution | *Résolu* | Supprimer la cause, restaurer (POL-04), vérifier |
| 5. Retour d'expérience (5.27) | *Clôturé* | Cause racine, leçons apprises ; actions correctives enregistrées comme non-conformité dans `iso.audits` quand un contrôle a failli |

Le statut se change sur l'incident, ou en déplaçant sa carte sur le
*Tableau de traitement*. Chaque mise à jour de la **chronologie** -
note, action menée, décision, communication - garde son auteur et son
heure ; l'historique de l'incident garde chaque modification de ses
champs.

## 5. Violation de données personnelles (RGPD art. 33, 34)

- Cocher *Violation de données personnelles* donne une échéance à
  l'incident : **72 heures après sa détection** pour notifier l'autorité
  [CNIL : notifications.cnil.fr]. La liste l'affiche dans *Notifier
  avant*, et *en retard* une fois dépassée sans notification.
- Le DPO et le responsable des incidents décident de notifier l'autorité
  et d'informer les personnes concernées (art. 34). Les dates vont dans
  *Autorité notifiée le* et *Personnes concernées notifiées le* ; le
  raisonnement dans la chronologie comme *Décision*.
- Une violation non notifiée est enregistrée quand même, avec la raison
  (art. 33(5)).

Les autorités et contacts (CNIL, CERT-FR, la cellule cybercriminalité
de la police, [assureur, avocat]) sont listés dans les *contacts*
(`iso.isms`, 5.5).

## 6. Preuves (5.28)

- Chaque preuve est ajoutée à l'incident (*Preuves*) : un fichier, qui
  l'a collecté, quand, où il est conservé, et sa chaîne de traçabilité.
- L'application calcule le **SHA-256** du fichier au dépôt ; vérifier
  l'empreinte plus tard prouve que le fichier n'a pas changé.
- Chaque téléchargement d'une preuve est inscrit au **journal des
  accès** : qui, quand, depuis quelle adresse. Il fait partie de la
  traçabilité.
- Exporter de l'application ce dont l'enquête a besoin **avant** toute
  restauration et avant que la conservation ne le supprime (section 7),
  et l'ajouter comme preuve.

## 7. Ce que l'application dit à l'enquêteur

| Question | Où | Permission |
| --- | --- | --- |
| Qui s'est connecté, depuis quelle adresse, quand ; mots de passe erronés ; verrouillages | *Historique > Événements de sécurité* (`signed_in`, `sign_in_failed`, `locked_out`), et les lignes `generic.security` du journal applicatif | `generic.view_securityevent` |
| Qui a exporté quel tableau, combien de lignes | Événements de sécurité `exported` | la même |
| Qui a reçu un droit, de qui | Événements de sécurité `access_granted` ; *Personnes > Demandes d'accès* | la même |
| Quels jetons d'API existent, quand chacun a servi pour la dernière fois ; qui en a créé ou révoqué un | *Personnes > Jetons d'API* ; événements de sécurité `token_created`, `token_deleted` | `generic_tokens.view_apitoken` |
| Ce qui a changé dans une fiche, qui l'a changé, ce qu'elle était avant | L'onglet *Historique* de la fiche ; *Historique > Modifications* | `generic.view_historyentry` |
| Qui a ouvert une fiche ou téléchargé un fichier | *Historique > Journal des accès* (ressources dotées d'un journal des accès) | `generic.view_accessentry` |
| Ce qui a échoué sur le serveur | Le journal applicatif, les e-mails d'erreur (POL-06) | Accès au serveur |

Les fiches supprimées laissent une entrée *supprimée* qui contient ce
qu'elles étaient en dernier. L'adresse enregistrée est celle que le
serveur a vue, jamais une qu'un client pourrait falsifier.

## 8. Endiguer dans l'application

| Besoin | Comment |
| --- | --- |
| Arrêter un compte | Décocher *Actif* sous **Personnes > Utilisateurs** : il ne peut plus se connecter, ses sessions s'arrêtent à leur requête suivante, ses jetons sont refusés |
| Arrêter un script | Révoquer son jeton sous **Personnes > Jetons d'API** |
| Arrêter les exports et téléchargements | Retirer `generic.export_rows` / `generic.download_files` du groupe, quand ce sont des droits sur demande |
| Arrêter le site pour une correction | *Planifier un redémarrage* (POL-07), ou arrêter la pile |
| Déconnecter tout le monde | Changer `DJANGO_SECRET_KEY` et redémarrer [en dernier recours : cela invalide aussi les liens de réinitialisation de mot de passe] |

## 9. Enregistrements

L'incident, sa chronologie, ses preuves et leur journal des accès, son
historique, et les non-conformités qu'il a ouvertes sont les
enregistrements des contrôles 5.24 à 5.28. Ils sont conservés [5 ans].
