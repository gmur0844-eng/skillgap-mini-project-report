#!/usr/bin/env bash
# Stop the local server started by run.sh:  bash scripts/local/stop.sh   (PORT=8010 for another port)
PORT="${PORT:-8000}"
pids="$(lsof -ti "tcp:$PORT" 2>/dev/null)"
if [ -z "$pids" ]; then echo "nothing is running on port $PORT"; exit 0; fi
kill $pids && echo "stopped the server on port $PORT"
