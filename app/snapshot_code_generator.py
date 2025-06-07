import os
import json
import dotenv
import re
dotenv.load_dotenv()
from .models import SnapshotDataStructure, DeploymentInstruction, SnapshotCode, ActionSummary
from .context import RunContext, prepare_context_lazy
from .three_stage_llm_call import ThreeStageAnalyzer
from typing import Dict, List

from jinja2 import FileSystemLoader, Environment

scaffold_templates = FileSystemLoader('scaffold')
env = Environment(loader=scaffold_templates)

class SnapshotCodeGenerator:
    def __init__(self, context: RunContext):
        self.context = context

    def _get_interface_names(self, interfaces: str) -> List[str]:
        pattern = r'export\s+interface\s+(\w+)'
        matches = re.findall(pattern, interfaces)
        inames = [match for match in matches]
        return inames
    
    def _get_identifiers(self):
        actions_directory = self.context.actions_directory()
        # iterate over all files in the actions directory
        actions = []
        for root, _, files in os.walk(actions_directory):
            for file in files:
                if file.endswith(".json"):
                    file_path = os.path.join(root, file)
                    action = ActionSummary.load_summary(file_path)
                    actions.append(action)

        new_identifiers = []
        for action in actions:
            if action.action_execution.does_register_new_identifier:
                for id in action.action_execution.new_identifiers:
                    new_identifiers.append({
                        "name": id.name,
                        "description": id.description
                    })
        return new_identifiers
        

    def generate(self):
        """
        Generate the snapshot data structure for all contracts in the project.
        """
        #contracts = self.context.deployed_contracts()
        print(f"📁 Deployment instructions path: {self.context.deployment_instructions_path()}")
        deployment_instructions = self.context.deployment_instructions()
        if deployment_instructions is None:
            print("Error: deployment_instructions is None. Please check your context or deployment instructions source.")
            return
        interfaces = ""
        snapshot_functions = []
        contracts = []
        
        # Track contract references to handle multiple deployments of same contract
        contract_references: Dict[str, List[str]] = {}
        interfaces_created = {}

        actor_identifiers = self._get_identifiers()
        
        for item in deployment_instructions.sequence:
            if item.type == "deploy":
                contract_name = item.contract
                ref_name = item.ref_name
                
                # Track contract references
                if contract_name not in contract_references:
                    contract_references[contract_name] = []
                contract_references[contract_name].append(ref_name)
                
                print(f"Generating snapshot data structure for {contract_name} ({ref_name})...")
                snapshot_path = self.context.snapshot_data_structure_path(contract_name)
                #print (snapshot_path)
                snapshot_data_structure = SnapshotDataStructure.load_summary(snapshot_path)
                
                if snapshot_data_structure is None:
                    print(f"Snapshot data structure for {contract_name} not found. Skipping...")
                    continue

                contract_instance = {}

                contract_instance["reference_name"] = ref_name
                contract_instance["function_name"] = f"take{ref_name}ContractSnapshot"
                contract_instance["snapshot_file_name"] = f"{ref_name}_snapshot.ts"
                contract_instance["interface_name"] = snapshot_data_structure.typescript_interfaces.interface_name
                contracts.append(contract_instance)
                
                interfaces_for_contract = ""
                if contract_name not in interfaces_created:
                    interfaces_for_contract += self._exported(snapshot_data_structure.typescript_interfaces.contract_snapshot_interface_code)
                    #interfaces_for_contract += self._exported(snapshot_data_structure.typescript_interfaces.user_data_snapshot_interface_code)
                    interface_names = self._get_interface_names(interfaces_for_contract)
                    interfaces_created[contract_name] = {
                        "contract_state": interface_names[0]
                        #"user_state": interface_names[1]
                    }
                
                interfaces += interfaces_for_contract
                    
                # Generate snapshot functions for this contract
                snapshot_code = self._generate_snapshot_logic(
                    interfaces_created,
                    contract_name, 
                    ref_name,
                    snapshot_data_structure,
                    actor_identifiers
                )
                if isinstance(snapshot_code, str):
                    snapshot_functions.append(snapshot_code)

                # Write snapshot logic file
                snapshot_code_path = os.path.join(
                    os.path.dirname(self.context.snapshot_interface_code_path()),
                    f"{ref_name}_snapshot.ts"
                )

                with open(snapshot_code_path, 'w') as f:
                    f.write("// Generated by SnapshotCodeGenerator\n\n")
                    f.write(snapshot_code)
                    print(f"Snapshot logic for {ref_name} written to {snapshot_code_path}")
        
        
        # Write interfaces file
        with open(self.context.snapshot_interface_code_path(), 'w') as f:
            f.write("// Generated by SnapshotCodeGenerator\n\n")
            f.write(interfaces)
            print(interfaces)

        template = env.get_template("contract_snapshot_provider_v2.ts.j2")
        provider_code = template.render(
            contract_instances=contracts
        )
        with open(self.context.snapshot_provider_code_path(), 'w') as f:
            f.write("// Generated by SnapshotCodeGenerator\n\n")
            f.write(provider_code)
            print(f"Snapshot provider code written to {self.context.snapshot_provider_code_path()}")
        
        
        self.context.commit("Snapshot interfaces and functions generated successfully.")

    def _generate_snapshot_logic(self, interfaces_created, contract_name: str, ref_name: str, snapshot_data: SnapshotDataStructure, identifiers) -> str:
        analyzer = ThreeStageAnalyzer(SnapshotCode, system_prompt="You are a TypeScript code generator specialized in generating code to take snapshots for smart contracts using ethers")
        """
        Generate TypeScript functions to take contract and user snapshots
        """
        prompt = f"""
        Generate complete, production-ready TypeScript functions to snapshot the state of {contract_name} contract (reference: {ref_name}).
        
        Requirements:
        1. Generate function:
           - take{ref_name}ContractSnapshot: For contract state
        2. Must handle BigInt conversions properly
        3. Include comprehensive error handling
        4. All contract function calls should have an await statement.
        5. Use the attributes and methods from the snapshot data structure are below. Interfaces are also defined for the contract state and user state.
           {json.dumps(snapshot_data.to_dict(), indent=2)}
        6. Each function should accept:
           - contract: ethers.Contract instance
        7. Return type should match the interfaces from the snapshot data structure
        8. Include detailed JSDoc comments
        9. Don't import any unnecessary libraries, no need for any retry logic.
        10. Interfaces {interfaces_created[contract_name]["contract_state"]} can be imported from './snapshot_interfaces.ts'

        Use the following imports:
        ```
        ethers
        Actor, Snapshot from @svylabs/ilumina and any other necessary imports
        interfaces provides above from `./snapshot_interfaces.ts` 
        
        Output format:
        ```
        /**
         * Takes a snapshot of {contract_name} state
         * @param contract - ethers.Contract instance
         * @returns Promise returning the interface {interfaces_created[contract_name]["contract_state"]}
         */
        export async function take{ref_name}ContractSnapshot(contract: ethers.Contract, actors: Actor[]): Promise<...> {{
            // Implementation
        }}

        actors will have a list of identifiers that can be used to fetch user specific data. You need to map the identifiers to be used with appropriate functions.
        Here are the list of identifiers that can be used:
        {json.dumps(identifiers, indent=2)}
        In addition to this, all actors will have an inbuilt identifier called accountAddress which is the address of the user.
        actor.getIdentifiers() will provide the list of all identifiers including accountAddress.
        The identifiers is a javascript object, with key being the identifier name, and value will be a single value or an array of values. If it's an array, you need to iterate over the array and fetch 
        the data for each identifier.

        
        ```
        """
        response = analyzer.ask_llm(prompt)
        return response.code if hasattr(response, 'code') else response

    def _exported(self, code: str) -> str:
        """
        Formats TypeScript interfaces and other code blocks for export.
        Ensures all interface declarations are prefixed with 'export'.
        """
        # If it starts with "export", leave it alone
        if code.strip().startswith("export "):
            return code + "\n\n"

        # Add 'export' before all 'interface' declarations not already exported
        def export_interface(match):
            if match.group(1) == 'export ':
                return match.group(0)
            return f"export interface {match.group(2)}"

        code = re.sub(r'(?:(export )?\binterface\b\s+([A-Za-z0-9_]+))',
                    export_interface,
                    code)

        return code.strip() + "\n\n"

if __name__ == "__main__":
    context = prepare_context_lazy({
        "run_id": "1747743579",
        "submission_id": "b2467fc4-e77a-4529-bcea-09c31cb2e8fe",
        "github_repository_url": "https://github.com/svylabs/stablebase"
        #"run_id": "3",
        #"submission_id": "s3",
        #"github_repository_url": "https://github.com/svylabs-com/sample-hardhat-project"
    }, needs_parallel_workspace=False)
    generator = SnapshotCodeGenerator(context)
    generator.generate()
    print("Snapshot code generation completed.")