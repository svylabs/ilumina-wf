#!/bin/bash

if [ "$MODE" == "server" ]; then
    echo "Starting server..."
    source .env
    source venv/bin/activate
    venv/bin/gunicorn -b 0.0.0.0:8080 main:app --timeout 900
elif [ "$MODE" == "runner" ]; then
    echo "Starting in background..."
    source .env
    source venv/bin/activate
    python3 simulation_runner_job.py
else
    echo "Invalid mode. Use 'server' or 'runner'."
    exit 1
fi