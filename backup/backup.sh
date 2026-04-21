#!/bin/sh
# ─────────────────────────────────────────────────────────────
# Patrimonium — sauvegarde automatique PostgreSQL
# Exécuté chaque nuit par le conteneur 'backup'
# ─────────────────────────────────────────────────────────────

set -e

BACKUP_DIR="/backups"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
FILENAME="patrimonium_${TIMESTAMP}.sql.gz"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Démarrage de la sauvegarde → ${FILENAME}"

# Dump compressé
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
  -h "${POSTGRES_HOST:-db}" \
  -U "${POSTGRES_USER:-patrimonium}" \
  -d "${POSTGRES_DB:-patrimonium}" \
  --no-password \
  | gzip > "${BACKUP_DIR}/${FILENAME}"

SIZE=$(du -sh "${BACKUP_DIR}/${FILENAME}" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sauvegarde terminée — taille : ${SIZE}"

# Nettoyage des sauvegardes plus vieilles que RETENTION_DAYS jours
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nettoyage des sauvegardes de plus de ${RETENTION_DAYS} jours…"
find "${BACKUP_DIR}" -name "patrimonium_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete

# Affiche les sauvegardes disponibles
COUNT=$(find "${BACKUP_DIR}" -name "patrimonium_*.sql.gz" | wc -l | tr -d ' ')
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${COUNT} sauvegarde(s) disponible(s) dans ${BACKUP_DIR}"
echo "---"
find "${BACKUP_DIR}" -name "patrimonium_*.sql.gz" | sort | while read f; do
  echo "  $(basename $f)  ($(du -sh $f | cut -f1))"
done
