import json
import subprocess
import os
from typing import Dict, Any
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ContractDeployer:
    def __init__(self, context):
        self.context = context
        self.local_repo_path = f"/tmp/workspace/{self.context.repo_name}"
        self.contracts_dir = os.path.join(self.local_repo_path, "contracts")

    def _setup_build_environment(self):
        """Automatically set up build tools if none exist"""
        if not os.path.exists(self.contracts_dir):
            os.makedirs(self.contracts_dir)
            
        # Initialize package.json if doesn't exist
        if not os.path.exists(os.path.join(self.local_repo_path, "package.json")):
            subprocess.run(["npm", "init", "-y"], cwd=self.local_repo_path, check=True)
        
        # Install Hardhat by default if no build tool detected
        hardhat_configs = [
            os.path.join(self.local_repo_path, "hardhat.config.js"),
            os.path.join(self.local_repo_path, "hardhat.config.ts"),
            os.path.join(self.local_repo_path, "foundry.toml")
        ]
        if not any(os.path.exists(config) for config in hardhat_configs):
            logger.info("No build tool detected, installing Hardhat...")
            subprocess.run(["npm", "install", "--save-dev", "hardhat"], 
                         cwd=self.local_repo_path, check=True)
            subprocess.run(["npx", "hardhat", "init"], 
                         cwd=self.local_repo_path, check=True)
            
    def compile_contracts(self) -> Dict[str, Any]:
        """Compile smart contracts using detected dev tool"""
        try:
            # Ensure the build environment is set up
            self._setup_build_environment()
            
            # if self._has_file("hardhat.config.js"):
            if self._has_file("hardhat.config.js") or self._has_file("hardhat.config.ts"):
                return self._compile_with_hardhat()
            elif self._has_file("foundry.toml"):
                return self._compile_with_foundry()
            else:
                raise RuntimeError("No supported build tool detected")
        except Exception as e:
            logger.error(f"Compilation failed: {str(e)}")
            raise

    def _has_file(self, filename: str) -> bool:
        return os.path.exists(os.path.join(self.local_repo_path, filename))

    def _compile_with_hardhat(self) -> Dict[str, Any]:
        result = subprocess.run(
            ["npx", "hardhat", "compile"],
            cwd=self.local_repo_path,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Hardhat compilation failed: {result.stderr}")
        
        artifacts_dir = os.path.join(self.local_repo_path, "artifacts")
        return self._parse_hardhat_artifacts(artifacts_dir)

    def _compile_with_foundry(self) -> Dict[str, Any]:
        result = subprocess.run(
            ["forge", "build"],
            cwd=self.local_repo_path,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Foundry compilation failed: {result.stderr}")
        
        artifacts_dir = os.path.join(self.local_repo_path, "out")
        return self._parse_foundry_artifacts(artifacts_dir)

    def _parse_hardhat_artifacts(self, artifacts_dir: str) -> Dict[str, Any]:
        contracts = {}
        for root, _, files in os.walk(artifacts_dir):
            for file in files:
                if file.endswith(".json") and not file.endswith(".dbg.json"):
                    with open(os.path.join(root, file), "r") as f:
                        artifact = json.load(f)
                        if "abi" in artifact and "bytecode" in artifact:
                            contract_name = file.replace(".json", "")
                            contracts[contract_name] = {
                                "abi": artifact["abi"],
                                "bytecode": artifact["bytecode"],
                                "metadata": artifact.get("metadata", {})
                            }
        return {"compiler": "hardhat", "contracts": contracts}

    def _parse_foundry_artifacts(self, artifacts_dir: str) -> Dict[str, Any]:
        contracts = {}
        for file in os.listdir(artifacts_dir):
            if file.endswith(".json") and not file.endswith(".metadata.json"):
                with open(os.path.join(artifacts_dir, file), "r") as f:
                    artifact = json.load(f)
                    if "abi" in artifact and "bytecode" in artifact:
                        contract_name = file.replace(".json", "")
                        contracts[contract_name] = {
                            "abi": artifact["abi"],
                            "bytecode": artifact["bytecode"],
                            "metadata": artifact.get("metadata", {})
                        }
        return {"compiler": "foundry", "contracts": contracts}