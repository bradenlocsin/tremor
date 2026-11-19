#!/bin/sh
# Start the job scheduler in the background and the dashboard in the foreground.
set -e
mkdir -p /data
uv run --no-sync tremor scheduler &
exec uv run --no-sync streamlit run src/tremor/dashboard/app.py \
  --server.port 8501 --server.address 0.0.0.0 --server.headless true
