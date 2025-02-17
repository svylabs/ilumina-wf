#!/usr/bin/env python3

import re

def extract_solidity_functions(file_path):
    """Extract public and external functions from a Solidity contract file."""
    with open(file_path, 'r') as f:
        content = f.read()

    # Updated regex to capture function definitions across multiple lines
    pattern = r'function\s+(\w+)\s*\(([^)]*)\)\s*(?:public|external)\s*(?:view|pure|payable)?\s*(?:returns\s*\(([^)]*)\))?'

    matches = re.findall(pattern, content, re.DOTALL)

    functions = []
    for match in matches:
        function_name, params, returns = match
        param_list = [param.strip() for param in params.split(',')] if params else []
        returns = returns.strip() if returns else None

        visibility = "public" if "public" in content or "external" in content else "unknown"

        functions.append({
            "function_name": function_name,
            "parameters": param_list,
            "visibility": visibility,
            "returns": returns
        })

    return functions

# Example Usage
contract_file = "/tmp/workspaces/1/predify/contracts/IResolutionStrategy.sol"
methods = extract_solidity_functions(contract_file)

print(f"🔍 Extracted Public/External Methods:")
for method in methods:
    params = ', '.join(method['parameters']) if method['parameters'] else 'None'
    returns = method['returns'] if method['returns'] else 'None'
    print(f" - {method['function_name']}({params}) [visibility: {method['visibility']}, returns: {returns}]")
