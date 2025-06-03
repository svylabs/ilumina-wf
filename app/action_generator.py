from .models import Action, ActionCode, ActionSummary
from .context import RunContext, prepare_context_lazy
from .three_stage_llm_call import ThreeStageAnalyzer
import re
import json

class ActionGenerator:

    """
    ActionGenerator is a class that generates actions based on the provided context.
    It takes an action and a context as input and generates a structured representation of the action.
    """

    def __init__(self, action: Action, context: RunContext):
        self.action = action
        self.context = context

    def generate_typescript_contract_snapshot_interface(self, ts_file_path):
        with open(ts_file_path, 'r') as file:
            content = file.read()

        # Regex to capture: contractSnapshot["key"] = await functionName(
        pattern = r'contractSnapshot\["(?P<key>\w+)"\]\s*=\s*await\s+(?P<function>\w+)\('
        matches = re.findall(pattern, content)

        fields = []
        for key, function_name in matches:
            # Strip "take" prefix and capitalize the rest
            if function_name.startswith("take"):
                typename = function_name[4:]
            else:
                typename = function_name
            typename = typename[0].upper() + typename[1:]

            fields.append(f"  {key}: {typename};")

        # Compose the TypeScript interface
        interface_code = f"export interface ContractSnapshot {{\n" + "\n".join(fields) + "\n}  \n\n export interface Snapshot {{ contractSnapshot: ContractSnapshot, accountSnapshot: Record<string, bigint> }} \n\n "
        return interface_code


    def generate_action(self):
        action_summary_path = self.context.action_summary_path(self.action)
        action_summary = ActionSummary.load_summary(action_summary_path)
        snapshot_structure_path = self.context.snapshot_provider_code_path()
        abi = self.context.contract_artifact_path(self.action.contract_name)
        with open(abi, 'r') as f:
            artifact = json.load(f)
            abi = artifact.get('abi', [])
        function_definition = next((f for f in abi if f.get('name') == self.action.function_name), None)
        if not function_definition:
            raise ValueError(f"Function {self.action.function_name} not found in contract {self.action.contract_name} ABI.")
        core_snapshot_structure = self.generate_typescript_contract_snapshot_interface(snapshot_structure_path)
        snapshot_interfaces_path = self.context.snapshot_interface_code_path()
        with open(snapshot_interfaces_path) as f:
            snapshot_interfaces = f.read()
            core_snapshot_structure += "\n\n" + snapshot_interfaces
        print (f"Core Snapshot Structure:\n{core_snapshot_structure}")
        prompt = self._generate_action_prompt(function_definition, action, action_summary, core_snapshot_structure)
        analyzer = ThreeStageAnalyzer(ActionCode, system_prompt="You are an expert in generating structured typescript code using ethers.js to interact with smart contract based on the structure provided in the context.")
        code = analyzer.ask_llm(prompt)
        with open(self.context.action_code_path(self.action), 'w') as f:
            f.write(code.typescript_code)
        self.context.commit(code.commit_message)

    def _generate_action_prompt(self, function_definition, action: Action, action_summary: ActionSummary, snapshot_structure: str) -> str:
        return f"""
        Generate a production ready TypeScript code to call the smart contract action {action.name}, contract: {action.contract_name}, function: {action.function_name} using ethers.js. 

        Here is a summary of the action.
        {action_summary.to_dict()}

        function definition:
        {json.dumps(function_definition)}

        The code should include:
        1. A class named {action.function_name.capitalize()}Action extending Action in ilumina framework.
        2. It should have a constructor that takes in ethers.js contract instance that will be used during execution.
            constructor(contract: ethers.Contract) {{
                super({{action.function_name.capitalize()}}Action)
                this.contract = contract;
            }}
        2. There should be three methods:
            a. `initialize`: Where parameters are created to call the contract function, including any new identifiers that needs to be created for the action.
            b. `execute`: Where the contract function is called with the parameters generated.
            c. `validate`: Where the execution of the contract function is validated through snapshots.

    The implementation of `initialize` should return the parameters that will be used to call the contract function.
    Use random values for the parameters generated using prng provided with RunContext, within bounds based on snapshots available(for ex: if ether is being sent, it should be a valid value upto max eth available)
    ```async function initialize(
        context: RunContext,
        actor: Actor,
        currentSnapshot: Snapshot
    ): Promise<[any, Record<string, any>]>;```

    The initialize function should return a tuple, where the first element is the action parameters, and the second element is the new identifiers that are created.

    The implementation of `execute` should call the contract function with the parameters generated in `initialize` and will be passed as `actionParams`.
    It should execute using actor.account.value cast as Hardhat signer object.
    ```async function execute(
        context: RunContext,
        actor: Actor,
        currentSnapshot: Snapshot,
        actionParams: any
    ): Promise<Record<string, any> | void>;```

    // To validate the action
    Validate the action by comparing the previous snapshot with the new snapshot based on validation rules provided in action summary.
    In addition, the validation should also be made for account balances, token balances for affected contracts and accounts. Contract address can be accessed using contract.target
    ```async function validate(
        context: RunContext,
        actor: Actor,
        previousSnapshot: Snapshot,
        newSnapshot: Snapshot,
        actionParams: any
    ): Promise<boolean>;```

        1. RunContext is a context that provides the following:
            a. context.prng: A pseudo-random number generator for generating random values, context.prng.next() will provide a random number between [0, 4294967296). Do not use Math.random()
        2. actor: Actor is an object that represents the actor performing the action. It has the following properties:
            account - and account.address gives the address and account.value gives the HardHat signer object.
            identifiers - can be accessed using getIdentifiers()
        3. Snapshot instances contain  has the following structure:
        ```typescript 
           {snapshot_structure}
        4. The action should import the required dependencies from @svylabs/ilumia(Actor, RunContext, Snapshot, Account, Action).
        5. Use expect from 'chai' for assertions in the validate method and also import these correctly.
        6. Use BigInt inplace of Number for any numeric values.
        7. ETH Balances / Token balances for contracts can be accessed the same way as account balances for other real actors.
        ```
            """
        pass
    
if __name__ == "__main__":
    context = prepare_context_lazy({
        "run_id": "1747743579",
        "submission_id": "b2467fc4-e77a-4529-bcea-09c31cb2e8fe",
        "github_repository_url": "https://github.com/svylabs/stablebase"
        #"run_id": "3",
        #"submission_id": "s3",
        #"github_repository_url": "https://github.com/svylabs-com/sample-hardhat-project"
    }, needs_parallel_workspace=False)
    # Load the Actors file
    actors = context.actor_summary()

        # Get the action
    action = actors.find_action("StableBaseCDP", "borrow")
        
    generator = ActionGenerator(action, context)
    generator.generate_action()
    print("Snapshot code generation completed.")