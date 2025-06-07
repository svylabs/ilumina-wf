#!/bin/bash

# Exit immediately on error
set -e

# Check if directory argument was passed
if [ -z "$1" ]; then
  echo "Usage: ./compile_contracts.sh <project_directory> [config_file]"
  exit 1
fi

echo "Compiling contracts in directory: $1"
cd "$1" || { echo "Failed to enter directory $1"; exit 1; }

# Determine project type
if [ -f "hardhat.config.js" ] || [ -f "hardhat.config.ts" ]; then
  echo "Detected Hardhat project"
  CONFIG_FILE=${2:-"hardhat.config.js"}
  
  # Verify config exists
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file $CONFIG_FILE not found"
    exit 1
  fi
  
  # Install dependencies if needed
  if [ ! -d "node_modules" ]; then
    echo "Installing Hardhat dependencies..."
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
  fi
  
  echo "Compiling with Hardhat using $CONFIG_FILE"
  npx hardhat compile --config "$CONFIG_FILE" || { echo "Hardhat compilation failed"; exit 1; }

elif [ -f "foundry.toml" ]; then
  echo "Detected Foundry project"
  
  # Check if Foundry is installed
  if ! command -v forge &> /dev/null; then
    echo "Installing Foundry..."
    curl -L https://foundry.paradigm.xyz | bash || { echo "Foundry install failed"; exit 1; }
    foundryup || { echo "Foundry setup failed"; exit 1; }
  fi
  
  echo "Compiling with Foundry"
  forge build || { echo "Foundry compilation failed"; exit 1; }

else
  echo "Error: Could not determine project type (Hardhat or Foundry)"
  echo "Looking for either hardhat.config.js/ts or foundry.toml"
  exit 1
fi

echo "Compilation completed successfully"
exit 0