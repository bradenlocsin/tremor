#!/bin/bash
# Send a short iMessage update to the author (address from TREMOR_NOTIFY_IMESSAGE in .env).
# Usage: scripts/imsg.sh "message text"
TO=$(grep '^TREMOR_NOTIFY_IMESSAGE=' "$(dirname "$0")/../.env" | cut -d= -f2-)
[ -z "$TO" ] && { echo "TREMOR_NOTIFY_IMESSAGE not set in .env" >&2; exit 1; }
osascript -e 'on run argv
tell application "Messages"
  set s to 1st account whose service type = iMessage
  send (item 1 of argv) to participant (item 2 of argv) of s
end tell
end run' "$1" "$TO"
