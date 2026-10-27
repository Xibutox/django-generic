# POL-04 Politique de sauvegarde et de restauration

| | |
| --- | --- |
| Code | POL-04 |
| Version | 1.0 |
| Propriétaire | Responsable informatique |
| Approuvée par | [Nom, fonction, date] |
| Revue | Tous les 12 mois, et après chaque test de restauration en échec |
| ISO/IEC 27001:2022 | 8.13, 8.14, 5.29, 5.30, 8.10, 8.24 |
| S'applique à | Toute application construite sur django-generic et déployée avec sa pile Docker |

> **Mode d'emploi.** Ce document décrit ce qu'il faut sauvegarder dans
> une application django-generic et comment les piles de ce dépôt le
> font. Le texte entre [crochets] est à compléter par l'organisme.

## 1. Objet

Pouvoir remettre l'application en service, avec ses données, dans les
objectifs de reprise fixés par le bilan d'impact (`iso.continuity` :
DMIA/RTO, PDMA/RPO), et le prouver en testant les restaurations.

## 2. Ce qui est sauvegardé

Deux éléments portent l'état de l'application, et **ils sont
sauvegardés ensemble, au même instant** :

| Quoi | Où | Pourquoi |
| --- | --- | --- |
| La base de données | PostgreSQL, le volume `postgres-data` | Toutes les fiches, l'historique, les événements de sécurité, le journal des accès, les comptes et leurs permissions |
| Les fichiers déposés | `MEDIA_ROOT`, le volume `app-media` | Pièces jointes, documents des politiques, preuves des incidents, images du wiki. La base les nomme : l'un sans l'autre est incomplet |

Ne sont pas sauvegardés, car reconstruits : Redis (la file des tâches et
le cache), les fichiers statiques (collectés dans l'image), les images
elles-mêmes (construites depuis le dépôt). La configuration -
`docker/prod.env` et ses secrets - est conservée [dans le gestionnaire
de mots de passe], **pas** avec les sauvegardes.

## 3. Comment

### 3.1 Un projet créé par `scripts/new_project.py`

Son service `backup` le fait chaque jour à `BACKUP_TIME` :

1. un `pg_dump` (format personnalisé) de la base et un `tar` des
   fichiers déposés, chacun envoyé directement dans GnuPG - AES-256, à
   partir de `BACKUP_PASSPHRASE` - si bien que rien de non chiffré
   n'atteint le disque ;
2. un `MANIFEST` (versions, SHA-256 des deux fichiers), puis une
   vérification : les empreintes, puis les deux fichiers déchiffrés et
   relus (`pg_restore --list`, `tar -t`). Seule une sauvegarde vérifiée
   prend son nom définitif ;
3. les sauvegardes plus anciennes que `BACKUP_KEEP_DAYS` sont
   supprimées, jamais la plus récente ;
4. le jour `BACKUP_TEST_WEEKDAY`, la plus récente est restaurée en
   entier dans une base jetable, ses tables, migrations et fichiers
   comptés, et le résultat ajouté à `backups/restore-tests.log`.

| Commande | Fait |
| --- | --- |
| `python ops.py backup` | Une sauvegarde maintenant |
| `python ops.py backups` | La liste |
| `python ops.py verify [NOM]` | Les vérifications de l'étape 2 |
| `python ops.py restore-test [NOM]` | L'étape 4, maintenant |
| `python ops.py restore NOM` | Demande de saisir le nom du projet, sauvegarde l'état présent, arrête le site, restaure la base et les fichiers à côté des actuels, ne bascule qu'une fois les deux complets, redémarre |

### 3.2 La pile d'exemple (`docker/docker-compose.prod.yml`)

Elle n'a pas de service de sauvegarde. Les deux commandes ci-dessous
sont lancées [chaque jour par le cron de l'hôte à 02:00], leur sortie
chiffrée et copiée hors du serveur comme le dit la section 4 :

```bash
C="docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env"
$C exec -T db pg_dump -U generic generic > backup.sql
$C exec -T web tar -C /app/media -czf - . > media.tar.gz
```

## 4. Règles

| Règle | Valeur |
| --- | --- |
| Fréquence | Chaque jour [, et avant chaque changement qui migre la base - POL-07] |
| Conservation | [`BACKUP_KEEP_DAYS` = 30 jours sur le serveur ; 12 copies mensuelles hors site] |
| Copies | `backups/` copié hors du serveur chaque jour [vers ...], dans un autre lieu que le serveur |
| Chiffrement | AES-256 (GnuPG). La phrase secrète est conservée hors du serveur [dans ...], connue de [noms] |
| Accès | Seuls [le responsable informatique et son suppléant] lisent les sauvegardes et la phrase secrète |
| Test de restauration | Hebdomadaire, automatique (3.1, étape 4) ; un exercice de restauration complète [deux fois par an], enregistré dans `iso.continuity` |
| PDMA / DMIA (RPO / RTO) | Ceux du service dans `iso.continuity` [ex. RPO 24 h, RTO 4 h] |

Une sauvegarde quotidienne donne au mieux une PDMA (RPO) de 24 heures.
Un service dont la PDMA est plus courte demande davantage [archivage
des WAL de PostgreSQL, réplicas].

## 5. Tests de restauration : les preuves

- `backups/restore-tests.log` : chaque test hebdomadaire, sa date et son
  résultat. [Lu chaque mois par le responsable informatique ; une ligne
  en échec est un incident - POL-08.]
- `iso.continuity` : un **exercice** de type *Restauration de
  sauvegarde* pour chaque test complet, avec la durée de reprise et la
  perte de données obtenues. L'exercice les compare à la DMIA et à la
  PDMA du service et indique si l'objectif est atteint.
- Un exercice en échec ou partiellement réussi ouvre une non-conformité
  dans `iso.audits`.

## 6. Restaurer

1. Décider la restauration [le responsable informatique, avec le
   propriétaire du service], et la sauvegarde : la plus récente avant le
   dommage.
2. Annoncer l'interruption (*Planifier un redémarrage*, POL-07).
3. `python ops.py restore NOM` (3.1), ou à la main : base et fichiers de
   la **même** sauvegarde.
4. Vérifier : se connecter, ouvrir des fiches récentes et leurs
   fichiers, *État du serveur* tout vert, `manage.py showmigrations`
   complet.
5. L'enregistrer : dans la chronologie d'un incident quand elle en
   découle, comme exercice dans `iso.continuity` sinon.

Restaurer ramène l'historique, les événements de sécurité et le journal
des accès tels qu'ils étaient à la sauvegarde : ce qui s'est passé
ensuite est dans le journal applicatif copié hors du serveur (POL-06).

## 7. Suppression

Les sauvegardes sont supprimées après leur durée de conservation, pour
que les données personnelles qu'elles contiennent ne soient pas gardées
plus longtemps que ne le dit le registre des traitements. Une fiche
supprimée de l'application reste dans les sauvegardes jusqu'à leur
expiration ; [l'indiquer au registre].
