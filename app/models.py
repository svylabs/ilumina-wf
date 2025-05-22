import re
import json
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
import os
from enum import Enum
from typing import Literal
from abc import ABC, abstractmethod
import re

class IluminaOpenAIResponseModel(BaseModel):
    @abstractmethod
    def to_dict(self) -> dict:
        pass

import re

def extract_all_solidity_definitions(content):
    """
    Extracts all contracts/interfaces/libraries in a Solidity file.
    For each, captures name, type, constructor (with initializer), and public/external functions.
    """

    # Matches contract-like declarations (including optional inheritance)
    contract_pattern = r'\b(abstract\s+contract|contract|interface|library)\s+(\w+)(?:\s+is\s+[^{]+)?\s*{'
    matches = list(re.finditer(contract_pattern, content))

    def extract_block(start_index):
        """Extract a brace-balanced block starting at {"""
        brace_count = 0
        i = start_index
        while i < len(content):
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    return content[start_index:i + 1]
            i += 1
        return content[start_index:]

    def extract_constructor(block):
        """Extract constructor with brace tracking (handles initializers like Ownable(...))"""
        constructor_pattern = r'\bconstructor\s*\([^)]*\)\s*(?:[^\{]*){'
        match = re.search(constructor_pattern, block)
        if not match:
            return None

        start = match.start()
        brace_open = block.find('{', match.end() - 1)

        # Track braces to get constructor body
        brace_count = 0
        i = brace_open
        while i < len(block):
            if block[i] == '{':
                brace_count += 1
            elif block[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    return block[start:i + 1]
            i += 1
        return block[start:]

    results = []

    for match in matches:
        contract_type_raw, contract_name = match.groups()
        contract_type = contract_type_raw.replace("abstract contract", "abstract")
        brace_start = content.find('{', match.end() - 1)
        block = extract_block(brace_start)

        constructor_str = extract_constructor(block)

        # Extract functions
        function_pattern = (
            r'function\s+(\w+)\s*\(([^)]*)\)\s*'
            r'(public|external)?\s*'
            r'(view|pure|payable)?\s*'
            r'(returns\s*\(([^)]*)\))?'
        )
        function_matches = re.findall(function_pattern, block, re.DOTALL)

        functions = []
        for func in function_matches:
            name, params, visibility, modifier, _, returns = func
            param_list = [p.strip() for p in params.split(',')] if params.strip() else []
            visibility = visibility or "unknown"
            returns = returns.strip() if returns else None
            functions.append({
                "function_name": name,
                "parameters": param_list,
                "visibility": visibility,
                "returns": returns
            })

        results.append({
            "contract_name": contract_name,
            "type": contract_type,
            "constructor": constructor_str,
            "functions": functions
        })

    return results


def extract_solidity_functions_and_contract_name(content):
    """Extract the contract name, type, public/external functions, and constructor (modern syntax) from a Solidity contract file."""

    # Extract contract type and name
    contract_pattern = r'\b(abstract\s+contract|contract|interface|library)\s+(\w+)'
    contract_match = re.search(contract_pattern, content)

    if contract_match:
        contract_type, contract_name = contract_match.groups()
        contract_type = contract_type.replace("abstract contract", "abstract")
    else:
        contract_name = "Unknown"
        contract_type = "Unknown"

    # Helper: Extract full block starting at first opening brace
    def extract_block(start_index):
        brace_count = 0
        i = start_index
        while i < len(content):
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    return content[start_index:i + 1]
            i += 1
        return ""

    # Extract constructor using modern syntax only
    constructor_str = None
    constructor_pattern = r'\bconstructor\s*\(([^)]*)\)[^{]*{'
    constructor_match = re.search(constructor_pattern, content)
    if constructor_match:
        start = constructor_match.start()
        brace_start = content.find('{', start)
        constructor_str = content[start:brace_start] + extract_block(brace_start)

    # Extract public/external functions
    function_pattern = r'function\s+(\w+)\s*\(([^)]*)\)\s*(public|external)?\s*(view|pure|payable)?\s*(returns\s*\(([^)]*)\))?'
    matches = re.findall(function_pattern, content, re.DOTALL)

    functions = []
    for match in matches:
        function_name, params, visibility, modifier, _, returns = match
        param_list = [param.strip() for param in params.split(',')] if params else []
        visibility = visibility if visibility else "unknown"
        returns = returns.strip() if returns else None

        functions.append({
            "function_name": function_name,
            "parameters": param_list,
            "visibility": visibility,
            "returns": returns
        })

    return {
        "contract_name": contract_name,
        "type": contract_type,
        "constructor": constructor_str,
        "functions": functions
    }



class Function(IluminaOpenAIResponseModel):
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

class Contract(IluminaOpenAIResponseModel):
    name: str
    type: Literal["abstract", "library", "interface", "contract"]  # external, library, interface
    path: str = ""
    summary: str
    functions: list[Function]
    is_deployable: bool = False  # Default to False
    constructor: str = None  # Default to None
    # is_deployable: bool = False  # Default to False
    # constructor: Optional[str] = None  # Default to None

    def __str__(self):
        return json.dumps(self.dict())
    
    def to_dict(self):
        return {
            #"path": self.path,
            "name": self.name,
            "path": self.path,
            "type": self.type,
            "summary": self.summary,
            "functions": [function.to_dict() for function in self.functions],
            "is_deployable": self.is_deployable,
            "constructor": self.constructor
        }

class Project(IluminaOpenAIResponseModel):
    name: str
    summary: str
    type: str
    dev_tool: Literal["hardhat", "foundry"]
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
    
class Identifier(IluminaOpenAIResponseModel):
    name: str
    type: Literal["address", "random_id", "structured_id_internal", "structured_id_external"]
    has_max_identifier_limit_per_address: bool = False
    max_identifier_limit_per_address: int
    description: str
    
class ActionDetail(IluminaOpenAIResponseModel):
    action_name: str
    contract_name: str
    function_name: str
    pre_execution_parameter_generation_rules: list[str]
    on_execution_state_updates_made: list[str]
    # Validation rules in terms of function calls to make to validate the state
    post_execution_contract_state_validation_rules: list[str]

class StateUpdate(IluminaOpenAIResponseModel):
    name: str
    type: str
    summary_of_update: str
    conditional_update: bool
    conditions: list[str]

class ContractStateUpdate(IluminaOpenAIResponseModel):
    contract_name: str
    state_updated: list[StateUpdate]

class ActionExecution(IluminaOpenAIResponseModel):
    action_name: str
    contract_name: str
    function_name: str
    does_register_new_identifier: bool
    new_identifiers: list[Identifier]
    all_state_updates: list[ContractStateUpdate]
    
class Action(IluminaOpenAIResponseModel):
    name: str
    summary: str
    contract_name: str
    function_name: str
    probability: float
    #actors: list[Actor]

    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "contract_name": self.contract_name,
            "function_name": self.function_name,
            "probability": self.probability
        }
    

class Actor(IluminaOpenAIResponseModel):
    name: str
    summary: str
    actions: list[Action]

    @classmethod
    def load(cls, data):
        return cls(**data)

    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "actions": [action.to_dict() for action in self.actions]
        }

class UserJourney(BaseModel):
    name: str
    summary: str
    actions: list[Action]

    @classmethod
    def load(cls, data):
        return cls(**data)
    
    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "actions": [action.to_dict() for action in self.actions]
        }
    
class UserJourneys(BaseModel):
    user_journeys: list[UserJourney]

    @classmethod
    def load(cls, data):
        return cls(**data)

    def to_dict(self):
        return {
            "user_journeys": [user_journey.to_dict() for user_journey in self.user_journeys]
        }
    
class Actions(IluminaOpenAIResponseModel):
    actions: list[Action]

    @classmethod
    def load(cls, data):
        return cls(**data)

    def to_dict(self):
        return {
            "actions": [action.to_dict() for action in self.actions]
        }
    
class Actors(IluminaOpenAIResponseModel):
    actors: list[Actor]

    @classmethod
    def load(cls, data):
        return cls(**data)

    def to_dict(self):
        return {
            "actors": [actor.to_dict() for actor in self.actors]
        }
    
    @classmethod
    def load_summary(self, path):
        if (os.path.exists(path)):
            with open(path, "r") as f:
                content = json.loads(f.read())
                #print(json.dumps(content))
                return Actors.load(content)
        return None

    
class Param(IluminaOpenAIResponseModel):
    name: str
    value: str = Field(..., description="Leave empty if it's type val")
    type: Literal["val", "ref"] # val | ref

    def to_dict(self):
        return {
            "name": self.name,
            "value": self.value,
            "type": self.type
        }

class SequenceStep(IluminaOpenAIResponseModel):
    type: Literal["deploy", "call"]  # "deploy" or "call"
    contract: str
    constructor: str = None
    ref_name: str
    function: str
    params: List[Param]

    def to_dict(self):
        return {
            "type": self.type,
            "contract": self.contract,
            "constructor": self.constructor,
            "function": self.function,
            "ref_name": self.ref_name,
            "params": [param.to_dict() for param in self.params]
        }

class DeploymentInstruction(IluminaOpenAIResponseModel):
    sequence: List[SequenceStep]

    def to_dict(self):
        return {"sequence": [step.to_dict() for step in self.sequence]}
    
    @classmethod
    def load(cls, data):
        return cls(**data)
    
    @classmethod
    def load_summary(cls, path):
        if (os.path.exists(path)):
            with open(path, "r") as f:
                content = json.loads(f.read())
                return DeploymentInstruction.load(content)
        return None

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

class ActionInstruction(IluminaOpenAIResponseModel):
    name: str
    contract: str
    function: str
    parameters: List[Dict[str, str]]  # List of parameter name and type
    content: str  # Generated TypeScript code

    def to_dict(self):
        return {
            "name": self.name,
            "contract": self.contract,
            "function": self.function,
            "parameters": self.parameters,
            "content": self.content
        }
    
class Code(IluminaOpenAIResponseModel):
    commit_message: str
    change_summary: str
    code: str
    language: str = Literal["typescript"]

    def to_dict(self):
        return {
            "commit_message": self.commit_message,
            "change_summary": self.change_summary,
            "code": self.code
        }
    
class SnapshotCode(IluminaOpenAIResponseModel):
    contract_name: str
    code: str
    dependencies: List[str] = []
    
    def to_dict(self):
        return {
            "contract_name": self.contract_name,
            "code": self.code,
            "dependencies": self.dependencies
        }
