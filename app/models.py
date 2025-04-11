import re
import json
from typing import List, Dict, Optional
from pydantic import BaseModel
import os

def extract_solidity_functions_and_contract_name(content):
    """Extract the contract name and public/external functions from a Solidity contract file."""
    #with open(file_path, 'r') as f:
    #    content = f.read()

    # Extract contract name
    # Extract contract type and name
    contract_pattern = r'\b(abstract\s+contract|contract|interface|library)\s+(\w+)'
    contract_match = re.search(contract_pattern, content)
    
    if contract_match:
        contract_type, contract_name = contract_match.groups()
        contract_type = contract_type.replace("abstract contract", "abstract")  # Normalize for consistency
    else:
        contract_name = "Unknown"
        contract_type = "Unknown"

    # Updated regex to capture public/external function definitions across multiple lines
    function_pattern = r'function\s+(\w+)\s*\(([^)]*)\)\s*(?:public|external)\s*(?:view|pure|payable)?\s*(?:returns\s*\(([^)]*)\))?'
    matches = re.findall(function_pattern, content, re.DOTALL)

    functions = []
    for match in matches:
        function_name, params, returns = match
        param_list = [param.strip() for param in params.split(',')] if params else []
        visibility = "public" if "public" in content or "external" in content else "unknown"
        returns = returns.strip() if returns else None

        functions.append({
            "function_name": function_name,
            "parameters": param_list,
            "visibility": visibility,
            "returns": returns
        })

    return {"contract_name": contract_name, "type": contract_type, "functions": functions}

class Function(BaseModel):
    name: str
    summary: str
    inputs: list[str]
    outputs: list[str]

    def __str__(self):
        return json.dumps(self.dict())
    

    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "inputs": self.inputs,
            "outputs": self.outputs
        }

class Contract(BaseModel):
    path: str
    name: str
    type: str # external, library, interface
    summary: str
    functions: list[Function]

    def __str__(self):
        return json.dumps(self.dict())
    
    def to_dict(self):
        return {
            "path": self.path,
            "name": self.name,
            "type": self.type,
            "summary": self.summary,
            "functions": [function.to_dict() for function in self.functions]
        }

class Project(BaseModel):
    name: str
    summary: str
    type: str
    dev_tool: str
    contracts: list[Contract]

    def __str__(self):
        return json.dumps(self.dict())
    
    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "type": self.type,
            "dev_tool": self.dev_tool,
            "contracts": [contract.to_dict() for contract in self.contracts]
        }
    
    def clear_contracts(self):
        self.contracts = []

    def add_contract(self, contract):
        self.contracts.append(contract)

    @classmethod
    def load(cls, data):
        return cls(**data)
    
    @classmethod
    def load_summary(self, path):
        if (os.path.exists(path)):
            with open(path, "r") as f:
                content = json.loads(f.read())
                #print(json.dumps(content))
                return Project.load(content)
        return None

class DeploymentInstruction(BaseModel):
    sequence: list[dict]

    def to_dict(self):
        return {"sequence": self.sequence}

    @staticmethod
    def prepare_sequence(contracts):
        sequence = []
        for contract in contracts:
            # Extract constructor parameters from ABI if available
            constructor_params = []
            if hasattr(contract, 'abi'):
                for item in contract.abi:
                    if item.get("type") == "constructor":
                        constructor_params = [
                            {"name": input.get("name", f"param_{i}"), "type": input.get("type", "unknown"), "value": None}
                            for i, input in enumerate(item.get("inputs", []))
                        ]
                        break

            # Create deploy step
            deploy_step = {
                "Type": "deploy",
                "Contract": {"Name": contract.name},
                "Params": constructor_params if constructor_params else [
                    {"name": "default_param", "type": "unknown", "value": None}
                ]
            }
            sequence.append(deploy_step)

            # Create call steps for each function
            if hasattr(contract, 'functions'):
                for function in contract.functions:
                    call_step = {
                        "Type": "call",
                        "Contract": contract.name,
                        "Function": function.name,
                        "Params": [
                            {"name": input.get("name", f"param_{i}"), "type": input.get("type", "unknown"), "value": None}
                            for i, input in enumerate(function.inputs)
                        ]
                    }
                    sequence.append(call_step)

        return sequence
