#!/bin/bash

# Ensure the script exits on any error
set -e

# Check if simulation ID is provided
if [ -z "$1" ]; then
  echo "Error: Simulation ID is required as the first argument."
  exit 1
fi

SIMULATION_ID=$1
LOG_DIR="logs"
LOG_FILE="$LOG_DIR/$SIMULATION_ID.log"

# Create logs directory if it doesn't exist
mkdir -p $LOG_DIR

# Run the simulation and append output to the log file
npx hardhat run simulation/runner.ts >> $LOG_FILE 2>&1

# Print completion message
echo "Simulation completed. Logs are available at $LOG_FILE"