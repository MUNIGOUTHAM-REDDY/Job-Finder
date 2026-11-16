#!/usr/bin/env bash
# Runs both checks every 10 minutes, then the application worker, until the time budget runs out.
# GitHub only starts cron workflows every few hours, so one long run does the scheduling itself.
set -u
end=$(( $(date +%s) + ${LOOP_SECONDS:-19800} ))
push() { for i in 1 2 3 4 5; do git pull --rebase -q && git push -q && return 0; sleep $((RANDOM % 8 + 2)); done; return 1; }

while [ "$(date +%s)" -lt "$end" ]; do
  start=$(date +%s)
  git pull -q --rebase || true
  python run.py --cloud || echo "company sites check failed"
  xvfb-run -a python run.py --feeds || echo "LinkedIn + Naukri check failed"

  if ls inbox/*.json >/dev/null 2>&1; then
    (cd apps && git pull -q --rebase) || true
    python apps/worker.py inbox inbox loop || echo "application worker failed"
    rm -rf inbox
    (cd apps && git add applications resumes jobs 2>/dev/null && { git diff --cached --quiet || git commit -q -m "Update applications"; } && push) \
      || echo "couldn't save applications"
  fi

  git add state/seen-cloud.json state/seen-feeds.json 2>/dev/null
  git diff --cached --quiet || { git commit -q -m "Update seen jobs" && push || echo "couldn't save seen jobs"; }

  wait=$(( 600 - ($(date +%s) - start) ))
  [ "$wait" -gt 0 ] && [ $(( $(date +%s) + wait )) -lt "$end" ] && sleep "$wait"
done
