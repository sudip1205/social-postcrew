#!/usr/bin/env bash
# Runs ON the lab (copied there by ship.py when the lab was busy): wait until no crew run, plan generation or analysis is in
# progress, then update and restart Postcrew. Gives up after 3 hours. (2026-11-23: a skipped update left a fix undeployed and the
# owner's next video was made with the old code.)
for i in $(seq 1 360); do
  T=$(cat ~/postcrew/workspace/studio-token 2>/dev/null)
  B=$(curl -s -m 8 -H "Cookie: postcrew_token=$T" -H "X-Postcrew: 1" localhost:8765/api/overview \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print(any(d.get(k) for k in ("running","planning","analyzing")))' 2>/dev/null)
  if [ "$B" = "False" ] || [ -z "$B" ]; then
    ~/.local/bin/postcrew-lab update >> /tmp/postcrew-update-when-idle.log 2>&1
    exit 0
  fi
  sleep 30
done
