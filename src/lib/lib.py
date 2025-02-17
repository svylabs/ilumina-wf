import re
import json
from pydantic import BaseModel

def extract_solidity_functions_and_contract_name(content):
    """Extract the contract name and public/external functions from a Solidity contract file."""
    #with open(file_path, 'r') as f:
    #    content = f.read()

    # Extract contract name
    contract_name_pattern = r'\b(contract|interface|library)\s+(\w+)'
    contract_match = re.search(contract_name_pattern, content)
    contract_name = contract_match.group(2) if contract_match else "Unknown"

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

    return {"contract_name": contract_name, "functions": functions}

class RunContext:
    def __init__(self, run_id, repo, workspace):
        self.run_id = run_id
        self.repo = repo
        self.workspace = workspace
        self.name = repo.split("/")[-1]

    def get_run_id(self):
        return self.run_id

    def cwd(self):
        return self.workspace + "/" + self.run_id

    def cws(self):
        return self.cwd() + "/" + self.name

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
