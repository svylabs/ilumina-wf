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
    
class Param(BaseModel):
    name: str
    value: Optional[str] = None
    type: str # val | ref

class SequenceStep(BaseModel):
    type: str  # "deploy" or "call"
    contract: str
    function: Optional[str] = None
    params: List[Param]

class DeploymentInstruction(BaseModel):
    sequence: List[SequenceStep]

    def to_dict(self):
        return {"sequence": [step.dict() for step in self.sequence]}

    @staticmethod
    def build_dependency_tree(contracts: List[Contract]) -> Dict[str, List[str]]:
        """Build a dependency tree for the contracts."""
        dependency_tree = {}
        for contract in contracts:
            dependencies = []
            for function in contract.functions:
                for param in function.inputs:
                    if "address" in param:  # Assuming deployed addresses are passed as inputs
                        dependencies.append(param)
            dependency_tree[contract.name] = dependencies
        return dependency_tree

    @staticmethod
    def resolve_dependencies(dependency_tree: Dict[str, List[str]]) -> List[str]:
        """Resolve the order of contracts based on dependencies."""
        resolved = []
        unresolved = set()

        def resolve(contract):
            if contract in resolved:
                return
            if contract in unresolved:
                raise ValueError(f"Circular dependency detected: {contract}")
            unresolved.add(contract)
            for dependency in dependency_tree.get(contract, []):
                resolve(dependency)
            unresolved.remove(contract)
            resolved.append(contract)

        for contract in dependency_tree:
            resolve(contract)

        return resolved

    @staticmethod
    def prepare_sequence(contracts: List[Contract]) -> List[SequenceStep]:
        """Prepare the deployment instruction sequence."""
        dependency_tree = DeploymentInstruction.build_dependency_tree(contracts)
        deployment_order = DeploymentInstruction.resolve_dependencies(dependency_tree)

        sequence = []
        deployed_addresses = {}

        for contract_name in deployment_order:
            DeploymentInstruction._process_contract(
                contract_name, contracts, dependency_tree, deployed_addresses, sequence
            )

        return sequence

    @staticmethod
    def _process_contract(contract_name, contracts, dependency_tree, deployed_addresses, sequence):
        """Recursively process contracts based on dependencies."""
        contract = next((c for c in contracts if c.name == contract_name), None)
        if not contract:
            return

        # Prepare constructor parameters
        constructor_params = []
        for function in contract.functions:
            if function.name == "constructor":
                for param in function.inputs:
                    param_value = deployed_addresses.get(param, None)  # Use deployed address if available
                    if not param_value:  # If value is missing, ask the user
                        param_value = input(f"Enter value for constructor parameter '{param}' in contract '{contract.name}': ")
                    constructor_params.append({"name": param, "value": param_value})

        # Add deploy step
        deploy_step = SequenceStep(
            type="deploy",
            contract=contract.name,
            params=constructor_params,
        )
        sequence.append(deploy_step)
        deployed_addresses[contract.name] = f"{contract.name}_address"  # Mock deployed address

        # Add call steps for each function
        for function in contract.functions:
            if function.name != "constructor":
                call_step = SequenceStep(
                    type="call",
                    contract=contract.name,
                    function=function.name,
                    params=[
                        {"name": input_param, "value": "unknown"} for input_param in function.inputs
                    ],
                )
                sequence.append(call_step)
