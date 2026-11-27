#!/usr/bin/env bash
# Once a minute, runs whichever searches are due (see scheduler.py and the dashboard's Searches tab),
# then the application worker, until the time budget runs out.
# GitHub only starts cron workflows every few hours, so one long run does the scheduling itself.
set -u
end=$(( $(date +%s) + ${LOOP_SECONDS:-19800} ))
push() {
  for i in 1 2 3 4 5; do
    if git pull --rebase -q; then git push -q && return 0; else git rebase --abort 2>/dev/null; fi
    sleep $((RANDOM % 8 + 2))
  done
  return 1
}

python scheduler.py publish || echo "couldn't publish search terms"
buttons=0
while [ "$(date +%s)" -lt "$end" ]; do
  start=$(date +%s)
  git pull -q --rebase || true
  due=$(python scheduler.py due) || { echo "scheduler failed"; due=""; }
  for s in $due; do
    case $s in
      company) python run.py --cloud ;;
      design_feeds) xvfb-run -a python run.py --feeds ;;
      quick) xvfb-run -a python run.py --quick ;;
    esac && result=ok || { result=failed; echo "$s search failed"; }
    python scheduler.py report "$s" "$result" || true
  done
  # Searches collect Telegram Approve/Skip taps; when none has run for a while, collect them anyway.
  if [ -n "$due" ]; then buttons=$start
  elif [ $((start - buttons)) -ge 600 ]; then python run.py --buttons || true; buttons=$start; fi

  worked=$due
  if ls inbox/*.json >/dev/null 2>&1; then
    worked=1
    (cd apps && git pull -q --rebase) || true
    python apps/worker.py inbox inbox loop || echo "application worker failed"
    rm -rf inbox
    (cd apps && git add applications resumes jobs 2>/dev/null && { git diff --cached --quiet || git commit -q -m "Update applications"; } && push) \
      || echo "couldn't save applications"
  fi

  if [ -n "$worked" ]; then
    # Copy new and changed records to Supabase, which the dashboard reads.
    [ -n "${SUPABASE_SECRET_KEY:-}" ] && { python supabase_sync.py apps || echo "couldn't sync to Supabase"; }

    git add state/seen-cloud.json state/seen-feeds.json state/seen-quick.json 2>/dev/null
    git diff --cached --quiet || { git commit -q -m "Update seen jobs" && push || echo "couldn't save seen jobs"; }
  fi

  wait=$(( 60 - ($(date +%s) - start) ))
  [ "$wait" -gt 0 ] && [ $(( $(date +%s) + wait )) -lt "$end" ] && sleep "$wait"
done
true  # a finished run is a success, whatever the last test above returned
