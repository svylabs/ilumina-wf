#!/bin/bash

# Exit immediately on error
set -e

# Check if tracking ID is provided
if [ -z "$1" ]; then
  echo "Error: Validation tracking ID is required as the first argument."
  exit 1
fi

if [ -z "$2" ]; then
  echo "Error: Simulation path is required as the second argument."
  exit 1
fi

if [ -z "$3" ]; then
  echo "Error: Script name is required as the third argument."
  exit 1
fi

if [ -z "$4" ]; then
  echo "Error: Sequence name is required as the fourth argument."
  exit 1
fi

TRACKING_ID=$1
SIMULATION_PATH=$2
SCRIPT_NAME=$3
SEQUENCE_NAME=$4

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/validation_$TRACKING_ID.log"
cd "$SIMULATION_PATH" || { echo "Failed to enter directory $SIMULATION_PATH"; exit 1; }

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Determine project type (simulation environment is always Hardhat)
echo "Preparing validation environment"
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

echo "Running validation sequence"
RESULT_PATH="result_$TRACKING_ID.json" SEQUENCE_PATH="$SEQUENCE_NAME" npx hardhat run --config hardhat.config.ts "scripts/$SCRIPT_NAME" >> "$LOG_FILE" 2>&1 || { echo "Validation failed"; exit 1; }

echo "Validation completed. Logs are available at $LOG_FILE"
exit 0
