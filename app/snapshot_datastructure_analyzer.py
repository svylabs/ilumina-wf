import os
import dotenv
dotenv.load_dotenv()
import json
from .context import RunContext, prepare_context_lazy
from .models import Action, ActionSummary, SnapshotDataStructure
from .three_stage_llm_call import ThreeStageAnalyzer
class SnapshotDataStructureAnalyzer:
    def __init__(self, context: RunContext):
        self.context = context

    def analyze(self, contract_name: str):
        """
          Analyze the contract to implement code
        """
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
        
        abi_path = self.context.contract_artifact_path(contract_name)
        with open(abi_path, 'r') as f:
            artifact = json.load(f)
            abi = artifact.get('abi', [])

        analyzer = ThreeStageAnalyzer(SnapshotDataStructure)
        prompt = self._get_prompt_for_snapshot_structure(contract_name, abi, new_identifiers)
        #print(prompt)
        snapshot_data_structure = analyzer.ask_llm(prompt)
        with open(self.context.snapshot_data_structure_path(contract_name), 'w') as f:
            f.write(json.dumps(snapshot_data_structure.to_dict(), indent=2))
        
        self.context.commit(f"Snapshot data structure for {contract_name} generated successfully.")
        #print(f"Snapshot Data Structure for {contract_name}:\n{json.dumps(snapshot_data_structure.to_dict(), indent=2)}")

    def _get_prompt_for_snapshot_structure(self, contract_name: str, abi: list, new_identifiers: list):
        """
        Generate the prompt for snapshot structure analysis
        """
        return f"""
        Analyze the contract {contract_name} with the following ABI:
        {json.dumps(abi, indent=2)}

        The contract also registers new identifiers during execution of some of the functions:
        {json.dumps(new_identifiers, indent=2)}

        Can you come up with a datastructure to snapshot the state of the contract(along with functions to use to snapshot them)? Use the view functions, any functions that requires identifiers.
        There is also an inbuilt identifier(accountAddress) in addition to the identifiers listed above.

        The snapshot should have two fields, the list of attributes and the datastructure defined in typescript.

        1. Ignore any constants.
        2. Include only public state variables and view functions, any function that does state changes should not be included in this.
        3. Have proper names(nouns) for the attributes.
        4. In reference attribute for parameter, use the identifier name as value, and it has to be from the list of identifiers.
        5. Ignore any state variables that are addresses.
        6. For any state variable that is a mapping, use the identifier name as the key and the value as the value.

        For typescript structure, use the following format:
        1. Use bigint for any uint or int types.
        2. Use string for any address types.
        3. common_contract_state_snapshot_interface_code - should have typescript datastructure for contract state snapshot
        4. user_data_snapshot_interface_code - should have typescript datastructure for user specific data snapshot
        5. Have proper names for the interfaces in common_contract_state_snapshot_interface_code and user_data_snapshot_interface_code based on the contract name.
        """

if __name__ == "__main__":
    # Example usage
    context = prepare_context_lazy({
        "run_id": "1747743579",
        "submission_id": "b2467fc4-e77a-4529-bcea-09c31cb2e8fe",
        "github_repository_url": "https://github.com/svylabs/stablebase"
        #"run_id": "3",
        #"submission_id": "s3",
        #"github_repository_url": "https://github.com/svylabs-com/sample-hardhat-project"
    })
    analyzer = SnapshotDataStructureAnalyzer(context)
    # analyzer.analyze("StabilityPool")  # Replace "MyContract" with the actual contract name
    analyzer.analyze("StableBaseCDP")
        
