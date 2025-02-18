#!/usr/bin/env python3
import re
from collections import defaultdict
import os


def solidity_to_mermaid(file_path):
    with open(file_path, 'r') as f:
        solidity_code = f.read()

    contracts = re.findall(r'contract\s+(\w+)', solidity_code)
    inheritance = re.findall(r'contract\s+(\w+)\s+is\s+([\w,\s]+)', solidity_code)
    variables = re.findall(r'(\w+\s+\w+\s*public|private|internal\s+\w+)', solidity_code)
    functions = re.findall(r'function\s+(\w+)\s*\(([^)]*)\)', solidity_code)

    mermaid_code = "classDiagram\n"

    for contract in contracts:
        mermaid_code += f"    class {contract} {{\n"
        for var in variables:
            mermaid_code += f"        +{var}\n"
        for func in functions:
            func_name, params = func
            mermaid_code += f"        +{func_name}({params})\n"
        mermaid_code += "    }\n"

    for child, parents in inheritance:
        for parent in parents.split(','):
            mermaid_code += f"    {parent.strip()} <|-- {child}\n"

    return mermaid_code

def solidity_dependency_tree_in_project(project_path):
    dependencies = defaultdict(set)
    mermaid_code = "graph TD\n"

    for root, dirs, files in os.walk(project_path):
        for file in files:
            if file.endswith(".sol"):
                file_path = os.path.join(root, file)
                with open(file_path, 'r') as f:
                    solidity_code = f.read()

                imports = re.findall(r'import\s+\"(.*?)\";', solidity_code)
                inheritance = re.findall(r'contract\s+(\w+)\s+is\s+([\w,\s]+)', solidity_code)
                contracts = re.findall(r'contract\s+(\w+)', solidity_code)

                for imp in imports:
                    mermaid_code += f"    root --> {imp}\n"

                for child, parents in inheritance:
                    for parent in parents.split(','):
                        mermaid_code += f"    {parent.strip()} --> {child}\n"

                for contract in contracts:
                    if contract not in [parent.strip() for _, parents in inheritance for parent in parents.split(',')]:
                        mermaid_code += f"    root --> {contract}\n"

    return mermaid_code


file_path = "/tmp/workspaces/1/predify/contracts/Predify.sol"
class_diagram = solidity_to_mermaid(file_path)
print(class_diagram)


# Example usage
project_path = '/tmp/workspaces/1/predify/contracts'
dependency_tree = solidity_dependency_tree_in_project(project_path)

print(dependency_tree)

print(class_diagram)

with open('class_diagram.mmd', 'w') as f:
    f.write(class_diagram)

with open('dependency_tree.mmd', 'w') as f:
    f.write(dependency_tree)

print("Mermaid diagrams written to class_diagram.mmd and dependency_tree.mmd")