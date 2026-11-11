#!/bin/bash
# Sammelt beim nächsten Hänger alle wichtigen Infos in eine Datei.
# Aufruf (am Pi, im Repo-Ordner):  bash pi_diagnose.sh
# Ergebnis: logs/diagnose_<Zeit>.txt

RADEST_IP="${RADEST_IP:-192.168.0.10}"
RADEST_PORT="${RADEST_PORT:-2101}"
CAN="${CAN:-can0}"

mkdir -p logs
OUT="logs/diagnose_$(date +%Y%m%d_%H%M%S).txt"

run() {
    echo "===== $* =====" >> "$OUT"
    timeout 10 "$@" >> "$OUT" 2>&1
    echo >> "$OUT"
}

run date
run uptime
run free -h
run df -h /
# Unterspannung/Überhitzung: 0x0 ist gut, alles andere ist verdächtig.
run vcgencmd get_throttled
run vcgencmd measure_temp
# Wer belegt die Ports der Weboberflächen (8000 Prüfung, 8001 AEB)?
run ss -ltnp
# Offene Verbindungen zum RadEsT
run ss -tnp dst "$RADEST_IP"
# Python-Server und Browser mit Speicherverbrauch
echo "===== Prozesse (Python, uvicorn, Browser) =====" >> "$OUT"
ps -eo pid,ppid,stat,etime,%cpu,%mem,rss,cmd --sort=-rss \
    | grep -Ei "PID|python|uvicorn|chrom|firefox" | grep -v grep >> "$OUT" 2>&1
echo >> "$OUT"
echo "===== Prozesse mit meistem Speicher =====" >> "$OUT"
ps -eo pid,%cpu,%mem,rss,cmd --sort=-rss | head -15 >> "$OUT" 2>&1
echo >> "$OUT"
# RadEsT erreichbar? Port offen?
run ping -c 3 -W 1 "$RADEST_IP"
run bash -c "echo > /dev/tcp/$RADEST_IP/$RADEST_PORT && echo 'RadEsT-Port offen' || echo 'RadEsT-Port NICHT erreichbar'"
# CAN-Zustand (BUS-OFF, ERROR-PASSIVE, Fehlerzähler)
run ip -details -statistics link show "$CAN"
# Kernel-Meldungen: Speicher voll (oom), Unterspannung, CAN, SD-Karte
echo "===== dmesg (gefiltert) =====" >> "$OUT"
dmesg -T 2>/dev/null | grep -Ei "oom|out of memory|killed process|voltage|throttl|can|mmc|i/o error|hung" | tail -60 >> "$OUT" 2>&1 \
    || sudo -n dmesg -T | grep -Ei "oom|out of memory|killed process|voltage|throttl|can|mmc|i/o error|hung" | tail -60 >> "$OUT" 2>&1
echo >> "$OUT"
run bash -c "journalctl -k -p warning --since '-2h' --no-pager | tail -40"
run bash -c "ls -lt logs | head -5"

echo "Gespeichert: $OUT"
