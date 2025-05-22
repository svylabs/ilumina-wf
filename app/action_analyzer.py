import os
from slither.slither import Slither
from slither.core.declarations import Function
from slither.slithir.operations import InternalCall, HighLevelCall

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
    
    def analyze(self):
        # Understand what the action is about, any new identifiers it needs.
        # We need to get relevant code snippets from the project pass that to LLM.

        # 1. Understand state variables that are updated by an action
        # 2. Understand if the action needs any identifiers.

        # For one action-
        # 1. Get the code snippet for the action(this may encompass multiple functions, multiple contract calls)
        # 2. Identify the contracts affected by the action
        # 3. Identify the code snippets for each contracts separately
        # 4. For each contract: build a code snippet and identify the ABIs for the contract
        # call llm to get the models.ContractStateUpdate



        pass

if __name__ == "__main__":
    # Example usage
    project_path = "/tmp/workspaces/de71c43b-9ae9-462c-a97e-3b5c46498193/stablebase"
    contract_name = "StableBaseCDP.sol"
    entry_func_full_name = "liquidate()"
    os.environ["SOLC_ARGS"] = "--allow-paths .,node_modules"
    local_function_tree = extract_local_function_tree(project_path, contract_name, entry_func_full_name)
    for func_name, code in local_function_tree.items():
        print(f"Function: {func_name}\nCode:\n{code}\n")