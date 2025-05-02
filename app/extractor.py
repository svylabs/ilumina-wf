from .models import extract_all_solidity_definitions
import os
import json
if __name__ == "__main__":
    def find_contracts():
        base_contract_path = "/Users/sg/Documents/workspace/svylabs/stablebase/contracts"
        contracts = []
        for root, dirs, files in os.walk(base_contract_path):
            for file in files:
                if file.endswith(".sol"):
                    content = ""
                    with open(os.path.join(root, file), "r") as f:
                        content = f.read()
                    if (content.strip() == ""):
                        continue
                    contracts.append(
                        {
                            "path": os.path.join(root, file),
                            "name": file,
                            "content": content
                        }
                    )
        return contracts
    contracts = find_contracts()
    for contract in contracts:
        if (contract["name"] != "StableBase.sol"):
            continue
        print(f"Found contract {contract['name']} at {contract['path']}")
        contract_list = extract_all_solidity_definitions(contract["content"])
        for contract_detail in contract_list:
            if (contract_detail["contract_name"] == "Unknown"):
                print(f"Warning: Unknown contract name {json.dumps(contract_detail)}")
                continue
            print("Found contract" + json.dumps(contract_detail))
