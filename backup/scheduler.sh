#!/bin/sh
# ─────────────────────────────────────────────────────────────
# Scheduler — lance backup.sh une fois au démarrage,
#             puis chaque nuit à 02h00 (heure Europe/Brussels)
# Compatible BusyBox (Alpine)
# ─────────────────────────────────────────────────────────────

LOG="/backups/backup.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# Calcule les secondes jusqu'au prochain 02:00 en utilisant uniquement
# des opérations arithmétiques (compatible BusyBox)
seconds_until_next_2am() {
    CURRENT_HOUR=$(date +%H | sed 's/^0*//')
    CURRENT_MIN=$(date +%M | sed 's/^0*//')
    CURRENT_SEC=$(date +%S | sed 's/^0*//')

    # Secondes écoulées depuis minuit
    ELAPSED=$(( ${CURRENT_HOUR:-0} * 3600 + ${CURRENT_MIN:-0} * 60 + ${CURRENT_SEC:-0} ))

    # 02:00:00 = 7200 secondes depuis minuit
    TARGET=7200

    if [ "$ELAPSED" -lt "$TARGET" ]; then
        echo $(( TARGET - ELAPSED ))
    else
        # 02:00 déjà passé → demain 02:00
        echo $(( 86400 - ELAPSED + TARGET ))
    fi
}

log "═══════════════════════════════════════════════"
log "Service de sauvegarde Patrimonium démarré"
log "Rétention : ${BACKUP_RETENTION_DAYS:-30} jours"
log "Heure programmée : chaque nuit à 02h00 (${TZ:-UTC})"
log "═══════════════════════════════════════════════"

# Première sauvegarde immédiate au démarrage
log "Exécution de la sauvegarde initiale…"
sh /backup.sh >> "$LOG" 2>&1

# Boucle : attend jusqu'au prochain 02:00 et répète
while true; do
    SLEEP_SEC=$(seconds_until_next_2am)
    SLEEP_H=$(( SLEEP_SEC / 3600 ))
    SLEEP_M=$(( (SLEEP_SEC % 3600) / 60 ))
    log "Prochaine sauvegarde dans ${SLEEP_H}h ${SLEEP_M}m (à 02:00)"

    sleep "$SLEEP_SEC"

    log "Exécution de la sauvegarde nocturne…"
    sh /backup.sh >> "$LOG" 2>&1
done
