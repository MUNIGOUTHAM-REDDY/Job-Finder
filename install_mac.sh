#!/bin/bash
# Schedules the LinkedIn + Naukri check every 10 minutes, and keeps the Mac awake
# while it's on the charger. Re-run any time; run with --uninstall to remove both.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
JOB="com.jobfinder.check"
AWAKE="com.jobfinder.awake"
mkdir -p "$AGENTS" "$DIR/logs"

launchctl bootout "gui/$(id -u)/$JOB" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/$AWAKE" 2>/dev/null || true
if [ "$1" = "--uninstall" ]; then
  rm -f "$AGENTS/$JOB.plist" "$AGENTS/$AWAKE.plist"
  echo "Removed. Job Finder no longer runs on this Mac."
  exit 0
fi

cat > "$AGENTS/$JOB.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$JOB</string>
  <key>ProgramArguments</key><array>
    <string>$DIR/.venv/bin/python</string><string>$DIR/run.py</string><string>--mac</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/logs/mac.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/mac.log</string>
</dict></plist>
EOF

# caffeinate -s: no system sleep while on AC power (screen can still turn off).
cat > "$AGENTS/$AWAKE.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$AWAKE</string>
  <key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-s</string></array>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF

launchctl bootstrap "gui/$(id -u)" "$AGENTS/$JOB.plist"
launchctl bootstrap "gui/$(id -u)" "$AGENTS/$AWAKE.plist"
echo "Installed. Checks run every 10 min; log: $DIR/logs/mac.log"
