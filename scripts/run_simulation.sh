#!/bin/bash

# Exit immediately on error
set -e

# Check if simulation ID is provided
if [ -z "$1" ]; then
  echo "Error: Simulation ID is required as the first argument."
  exit 1
fi

SIMULATION_ID=$1
SIMULATION_PATH=$2
if [ -z "$SIMULATION_PATH" ]; then
  echo "Error: Simulation path is required as the second argument."
  exit 1
fi

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/$SIMULATION_ID.log"
cd "$SIMULATION_PATH" || { echo "Failed to enter directory $SIMULATION_PATH"; exit 1; }

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Determine project type (simulation environment is always Hardhat)
echo "Preparing simulation environment"
npm install --legacy-peer-deps
npm install --save-dev \
  "@nomicfoundation/hardhat-chai-matchers@^2.0.0" \
  "@nomicfoundation/hardhat-ethers@^3.0.0" \
  "@nomicfoundation/hardhat-network-helpers@^1.0.0" \
  "@types/chai@^4.2.0" \
  "@types/mocha@>=9.1.0" \
  "chai@^4.2.0" \
  "hardhat-gas-reporter@^1.0.8" \
  "solidity-coverage@^0.8.1" \
  "typechain@^8.3.0"

echo "Running simulation"
npx hardhat run --config hardhat.config.ts simulation/run.ts >> "$LOG_FILE" 2>&1 || { echo "Simulation failed"; exit 1; }

echo "Simulation completed. Logs are available at $LOG_FILE"
exit 0