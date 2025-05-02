# compiler.py
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Optional
from .context import RunContext
from .models import Contract, Project

class Compiler:
    def __init__(self, context: RunContext):
        self.context = context
        self.artifacts_dir = os.path.join(context.cws(), "artifacts")
        self.build_dir = os.path.join(context.cws(), "build")
        self.compiled_contracts_path = context.compiled_contracts_path()
        
    def detect_dev_tool(self) -> str:
        """Detect whether project uses Hardhat or Foundry"""
        if os.path.exists(os.path.join(self.context.cws(), "hardhat.config.js")) or \
           os.path.exists(os.path.join(self.context.cws(), "hardhat.config.ts")):
            return "hardhat"
        elif os.path.exists(os.path.join(self.context.cws(), "foundry.toml")):
            return "foundry"
        else:
            raise Exception("Could not detect development tool (Hardhat/Foundry)")
    
    def compile(self) -> Dict[str, dict]:
        """Compile contracts and return ABIs"""
        tool = self.detect_dev_tool()
        
        if tool == "hardhat":
            return self._compile_hardhat()
        else:
            return self._compile_foundry()
    
    def _compile_hardhat(self) -> Dict[str, dict]:
        """Compile using Hardhat and return contract ABIs"""
        try:
            # Run hardhat compile
            subprocess.run(
                ["npx", "hardhat", "compile"],
                cwd=self.context.cws(),
                check=True,
                capture_output=True,
                text=True
            )
            
            # Process artifacts
            return self._process_hardhat_artifacts()
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Hardhat compilation failed: {e.stderr}")
    
    def _process_hardhat_artifacts(self) -> Dict[str, dict]:
        """Process Hardhat artifacts and extract ABIs"""
        contracts_abi = {}
        
        # Walk through artifacts directory
        for root, _, files in os.walk(os.path.join(self.artifacts_dir, "contracts")):
            for file in files:
                if file.endswith(".json") and not file.endswith(".dbg.json") and not file.endswith(".metadata.json"):
                    contract_path = os.path.join(root, file)
                    with open(contract_path, "r") as f:
                        artifact = json.load(f)
                        
                    if "abi" in artifact and artifact["abi"]:
                        contract_name = Path(file).stem
                        contracts_abi[contract_name] = {
                            "abi": artifact["abi"],
                            "bytecode": artifact.get("bytecode", ""),
                            "deployedBytecode": artifact.get("deployedBytecode", "")
                        }
        
        # Print all extracted ABIs
        # print("Hardhat Contracts ABI:", json.dumps(contracts_abi, indent=2))
        
        # Save compiled contracts to JSON file
        with open(self.compiled_contracts_path, "w") as f:
            json.dump(contracts_abi, f, indent=2)
            
        return contracts_abi
    
    def _compile_foundry(self) -> Dict[str, dict]:
        """Compile using Foundry and return contract ABIs"""
        try:
            # Run forge build
            subprocess.run(
                ["forge", "build"],
                cwd=self.context.cws(),
                check=True,
                capture_output=True,
                text=True
            )
            
            # Process artifacts
            return self._process_foundry_artifacts()
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Foundry compilation failed: {e.stderr}")
    
    def _process_foundry_artifacts(self) -> Dict[str, dict]:
        """Process Foundry artifacts and extract ABIs"""
        contracts_abi = {}
        
        # Walk through artifacts directory
        for root, _, files in os.walk(os.path.join(self.artifacts_dir)):
            for file in files:
                if file.endswith(".json") and not file.endswith(".dbg.json") and not file.endswith(".metadata.json"):
                    contract_path = os.path.join(root, file)
                    with open(contract_path, "r") as f:
                        artifact = json.load(f)
                        
                    if "abi" in artifact and artifact["abi"]:
                        contract_name = Path(file).stem
                        contracts_abi[contract_name] = {
                            "abi": artifact["abi"],
                            "bytecode": artifact.get("bytecode", ""),
                            "deployedBytecode": artifact.get("deployedBytecode", "")
                        }
        
        # Print all extracted ABIs
        # print("Foundry Contracts ABI:", json.dumps(contracts_abi, indent=2))
        
        # Save compiled contracts to JSON file
        with open(self.compiled_contracts_path, "w") as f:
            json.dump(contracts_abi, f, indent=2)
            
        return contracts_abi
    
    def get_contract_abi(self, contract_name: str) -> Optional[dict]:
        """Get ABI for a specific contract"""
        if not os.path.exists(self.compiled_contracts_path):
            self.compile()
            
        with open(self.compiled_contracts_path, "r") as f:
            contracts_abi = json.load(f)
            
        return contracts_abi.get(contract_name)