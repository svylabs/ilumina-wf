import json
import subprocess
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class ContractDeployer:
    def __init__(self, context):
        self.context = context
        self.local_repo_path = f"/tmp/workspace/{self.context.repo_name}"

    def compile_contracts(self) -> dict:
        """Compile smart contracts and return ABIs/bytecode"""
        try:
            if self._has_file("hardhat.config.js"):
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

    def _compile_with_hardhat(self) -> dict:
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

    def _compile_with_foundry(self) -> dict:
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

    def _parse_hardhat_artifacts(self, artifacts_dir: str) -> dict:
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
                                "bytecode": artifact["bytecode"]
                            }
        return {"compiler": "hardhat", "contracts": contracts}

    def _parse_foundry_artifacts(self, artifacts_dir: str) -> dict:
        contracts = {}
        for file in os.listdir(artifacts_dir):
            if file.endswith(".json") and not file.endswith(".metadata.json"):
                with open(os.path.join(artifacts_dir, file), "r") as f:
                    artifact = json.load(f)
                    if "abi" in artifact and "bytecode" in artifact:
                        contract_name = file.replace(".json", "")
                        contracts[contract_name] = {
                            "abi": artifact["abi"],
                            "bytecode": artifact["bytecode"]
                        }
        return {"compiler": "foundry", "contracts": contracts}