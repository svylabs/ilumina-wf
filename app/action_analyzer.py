import os
from dotenv import load_dotenv
load_dotenv()
import json
from slither.slither import Slither
from slither.core.declarations import Function
from slither.slithir.operations import InternalCall, HighLevelCall
from app.compiler import Compiler
from app.three_stage_llm_call import ThreeStageAnalyzer
from app.models import ActionExecution, ActionDetail  

def extract_local_function_tree(project_path: str, contract_name: str, entry_func_full_name: str) -> dict:
    slither = Slither(project_path)
    local_root = os.path.abspath(project_path if os.path.isdir(project_path) else os.path.dirname(project_path))
    print(f"Local root: {local_root}")

    # Step 1: Map all locally defined functions
    all_funcs = {}  # full_name -> Function
    funcs_by_name = {}  # short name -> list of Functions (for fallback matching)

    for contract in slither.contracts:
        if contract.is_interface:
            continue
        for func in contract.functions:
            src_path = func.source_mapping.filename.absolute
            if src_path and local_root in os.path.abspath(src_path):
                all_funcs[func.full_name] = func
                funcs_by_name.setdefault(func.name, []).append(func)

    if entry_func_full_name not in all_funcs:
        print("Available function full names detected by Slither:")
        for fname in all_funcs.keys():
            print(f"  - {fname}")
        raise ValueError(f"Function '{entry_func_full_name}' not found in local project.")

    visited = set()
    result = {}

    def visit(func: Function):
        if func.full_name in visited:
            return
        visited.add(func.full_name)
        result[func.full_name] = func.source_mapping.content

        for node in func.nodes:
            for ir in node.irs:
                # Internal call to a known local function
                if isinstance(ir, InternalCall):
                    callee = ir.function
                    if isinstance(callee, Function) and callee.full_name in all_funcs:
                        visit(all_funcs[callee.full_name])

                # External call (possibly to another local contract or library)
                elif isinstance(ir, HighLevelCall):
                    # First: direct function resolution (if available)
                    if isinstance(ir.function, Function):
                        callee = ir.function
                        if callee.full_name in all_funcs:
                            visit(all_funcs[callee.full_name])
                    else:
                        # Fallback: match by function name
                        called_name = ir.function_name
                        if called_name in funcs_by_name and len(funcs_by_name[called_name]) == 1:
                            possible_callee = funcs_by_name[called_name][0]
                            if possible_callee.full_name in all_funcs:
                                visit(all_funcs[possible_callee.full_name])

    visit(all_funcs[entry_func_full_name])
    return result

class ActionAnalyzer:
    def __init__(self, action, context):
        self.action = action
        self.context = context
        self.contract_abi_cache = {}  # Cache for contract ABIs

    def _get_contract_abi(self, contract_name):
        """Get ABI for a contract, with caching"""
        if contract_name not in self.contract_abi_cache:
            compiler = Compiler(self.context)
            self.contract_abi_cache[contract_name] = compiler.get_contract_abi(contract_name)
        return self.contract_abi_cache[contract_name]
    
    def _extract_affected_contracts(self):
        """
        Identify all contracts affected by this action by analyzing the function call tree
        Returns list of contract names
        """
        # Use the existing extract_local_function_tree to get the call graph
        project_path = self.context.project_path()
        function_tree = extract_local_function_tree(
            project_path,
            self.action.contract_name,
            f"{self.action.function_name}()"
        )

        # Extract unique contract names from the function full names
        contracts = set()
        for func_name in function_tree.keys():
            # Function full name format: ContractName.functionName(...)
            contract_name = func_name.split('.')[0]
            contracts.add(contract_name)

        return list(contracts)
    
    def _build_contract_context(self, contract_name):
        """
        Build comprehensive context for a contract including:
        - Source code
        - ABI
        - State variables
        - Function signatures
        """
        # Get contract source code
        slither = Slither(os.path.join(self.context.project_path(), f"{contract_name}.sol"))
        contract = slither.get_contract_from_name(contract_name)[0]
        
        # Get ABI
        abi = self._get_contract_abi(contract_name)

        # Get state variables
        state_vars = [{
            "name": var.name,
            "type": str(var.type),
            "visibility": var.visibility
        } for var in contract.state_variables]

        return {
            "contract_name": contract_name,
            "source_code": contract.source_mapping.content,
            "abi": abi,
            "state_variables": state_vars,
            "entry_function": self.action.function_name if contract_name == self.action.contract_name else None
        }
    
    def _generate_llm_prompt_for_state_updates(self, contract_contexts):
        """
        Generate a comprehensive LLM prompt to analyze state updates
        """
        prompt = """
        Analyze the following smart contracts and action to determine state changes. For each contract:

        1. Identify which state variables are modified when executing the action
        2. Describe the nature of each state change
        3. Note any conditions that affect the state changes
        4. Identify if new identifiers are created

        Action: {action_name}
        Description: {action_summary}
        Primary Contract: {primary_contract}
        Primary Function: {primary_function}

        Contract Contexts:
        """.format(
            action_name=self.action.name,
            action_summary=self.action.summary,
            primary_contract=self.action.contract_name,
            primary_function=self.action.function_name
        )

        for ctx in contract_contexts:
            prompt += f"""
            === Contract: {ctx['contract_name']} ===
            Source Code:
            {ctx['source_code']}

            ABI:
            {json.dumps(ctx['abi'], indent=2)}

            State Variables:
            {json.dumps(ctx['state_variables'], indent=2)}
            """

        prompt += """
        Output format should be JSON matching the models.ActionExecution schema, including:
        - List of ContractStateUpdate objects detailing state changes per contract
        - Any new identifiers that may be created
        """

        return prompt
    
    def analyze(self):
        # Step 1: Identify all contracts affected by this action
        affected_contracts = self._extract_affected_contracts()
        
        # Step 2: Build comprehensive context for each contract
        contract_contexts = [self._build_contract_context(name) for name in affected_contracts]
        
        # Step 3: Generate LLM prompt to analyze state changes
        llm_prompt = self._generate_llm_prompt_for_state_updates(contract_contexts)
        
        # Step 4: Call LLM to get state change analysis
        analyzer = ThreeStageAnalyzer(ActionExecution)
        action_execution = analyzer.ask_llm(llm_prompt)
        
        # Step 5: Generate final ActionDetail with additional LLM call
        action_detail_prompt = self._generate_action_detail_prompt(action_execution)
        action_detail = analyzer.ask_llm(action_detail_prompt)

        return {
            "action_execution": action_execution,
            "action_detail": action_detail
        }
    
    def _generate_action_detail_prompt(self, action_execution):
        """Generate prompt to create detailed action description"""
        return f"""
Based on the following action execution analysis, create a detailed ActionDetail object:

Action: {self.action.name}
Contract: {self.action.contract_name}
Function: {self.action.function_name}

State Changes:
{json.dumps(action_execution.dict(), indent=2)}

Generate:
1. Pre-execution parameter generation rules
2. Description of state updates made during execution
3. Post-execution validation rules

Output should be a JSON object matching the ActionDetail schema.
"""
        
    # def analyze(self):
        # Understand what the action is about, any new identifiers it needs.
        # We need to get relevant code snippets from the project and pass that to LLM.

        # 1. Understand state variables that are updated by an action
        # 2. Understand if the action needs any identifiers.

        # For one action provided by the user, we need to build models.ActionExecution instance
        #Steps 1:
        # 1. Get the code snippet for the action(this may encompass multiple functions, multiple contract calls)
        # 2. Identify the contracts affected by the action
        # 3. Identify the code snippets for each contracts separately
        # 4. For each contract affected by the action: build a code snippet and identify the ABI for the contract
        # Call LLM to build a list of (models.ContractStateUpdate)
            # LLM should be given the following
            # 1. The code snippet from the contract
            # ABI for the contract
            # Function entry point for the contract
            # It should produce list[ContractStateUpdate] as output


        # Step 2:
        # We should also understand if the action needs any new identifiers or not.
        # and capture that as list[models.Identifier]
        
        # Once these two steps are done, we need to build a models.ActionExecution instance.
        # From models.ActionExecution instance, we need to build models.ActionDetail instance with LLM.


        # pass

if __name__ == "__main__":
    # Example usage
    # project_path = "/tmp/workspaces/de71c43b-9ae9-462c-a97e-3b5c46498193/stablebase"
    project_path = "/tmp/workspaces/s2/stablebase"
    contract_name = "StableBaseCDP.sol"
    # entry_func_full_name = "liquidate()"
    entry_func_full_name = "openSafe(uint256,uint256)"
    os.environ["SOLC_ARGS"] = "--allow-paths .,node_modules"
    local_function_tree = extract_local_function_tree(project_path, contract_name, entry_func_full_name)
    for func_name, code in local_function_tree.items():
        print(f"Function: {func_name}\nCode:\n{code}\n")