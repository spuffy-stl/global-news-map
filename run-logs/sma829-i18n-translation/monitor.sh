#!/bin/bash
PID=4840
WT=/home/hatch/workspace/global-news-map-service-wt-sma829-i18n
LOG=/home/hatch/workspace/global-news-map-service/run-logs/sma829-i18n-translation/monitor.log
echo "monitor start $(date -u +%FT%TZ) watching PID $PID" > "$LOG"
for i in $(seq 1 60); do
  if ! kill -0 $PID 2>/dev/null; then
    echo "CC session PID $PID exited after ~${i} min" >> "$LOG"
    break
  fi
  sleep 60
done
if kill -0 $PID 2>/dev/null; then echo "TIMEOUT: CC still running after 60 min" >> "$LOG"; fi
echo "--- worktree status ---" >> "$LOG"
git -C "$WT" status --short >> "$LOG" 2>&1
echo "--- recent commits ---" >> "$LOG"
git -C "$WT" log --oneline -5 >> "$LOG" 2>&1
echo "--- PRs for branch ---" >> "$LOG"
gh pr list --head cc/sma829-i18n-translation --repo spuffy-stl/global-news-map >> "$LOG" 2>&1
echo "--- claude.log tail ---" >> "$LOG"
tail -c 3000 /home/hatch/workspace/global-news-map-service/run-logs/sma829-i18n-translation/claude.log >> "$LOG" 2>&1
cat "$LOG"
