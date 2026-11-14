#!/bin/bash
PID=4201
WT=/home/hatch/workspace/global-news-map-service-wt-sma800-share-retire
LOG=/home/hatch/workspace/global-news-map-service/run-logs/sma800-share-retire/monitor.log
echo "monitor start $(date -u +%FT%TZ) watching PID $PID" > "$LOG"
for i in $(seq 1 40); do
  if ! kill -0 $PID 2>/dev/null; then
    echo "CC session PID $PID exited after ~${i} min" >> "$LOG"
    break
  fi
  sleep 60
done
if kill -0 $PID 2>/dev/null; then echo "TIMEOUT: CC still running after 40 min" >> "$LOG"; fi
echo "--- worktree status ---" >> "$LOG"
git -C "$WT" status --short >> "$LOG" 2>&1
echo "--- recent commits ---" >> "$LOG"
git -C "$WT" log --oneline -5 >> "$LOG" 2>&1
echo "--- PRs for branch ---" >> "$LOG"
gh pr list --head cc/sma800-share-retire --repo spuffy-stl/global-news-map >> "$LOG" 2>&1
echo "--- claude.log tail ---" >> "$LOG"
tail -c 3000 /home/hatch/workspace/global-news-map-service/run-logs/sma800-share-retire/claude.log >> "$LOG" 2>&1
cat "$LOG"
