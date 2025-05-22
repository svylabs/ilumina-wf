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
from app.context import example_contexts

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
        # result[func.full_name] = func.source_mapping.content
        result[func.full_name] = func

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

    def _get_contract_code(self, contract_name: str) -> str:
        """Get full source code for a contract"""
        contract_path = os.path.join(self.context.cws(), f"{contract_name}.sol")
        with open(contract_path, "r") as f:
            return f.read()
    
    def _get_function_call_tree(self, contract_name: str, entry_function: str) -> dict:
        """Get all functions called by the entry function"""
        project_path = self.context.cws()
        return extract_local_function_tree(
            project_path,
            contract_name,
            # f"{entry_function}()"
            entry_function 
        )
    
    def _build_action_context(self, action) -> dict:
        """Build complete context for action analysis"""
        # Get all contracts/functions involved
        call_tree = self._get_function_call_tree(
            action.contract_name,
            action.function_name
        )
        
        # Get context for each contract
        contracts = set()
        contract_code = {}
        for func_name, func in call_tree.items():
            contracts.add(func.contract.name)
            if func.contract.name not in contract_code:
                contract_code[func.contract.name] =func.source_mapping.content

            else:
                contract_code[func.contract.name] += "\n" + func.source_mapping.content
        
        print(f"Contracts involved: {contracts}")

        contract_contexts = []
        for contract_name in contract_code.keys():
            print(f"Contract: {contract_name}")
            if contract_name == "ERC721Utils": continue
            abi = ""
            with open(self.context.contract_artifact_path(contract_name), "r") as f:
                abi = json.load(f)["abi"]

            contract_contexts.append({
                "name": contract_name,
                "code": contract_code[contract_name],
                "abi": abi,
                "is_main": contract_name == action.contract_name
            })
        
        return {
            "action": {
                "name": action.name,
                "summary": action.summary,
                "contract": action.contract_name,
                "function": action.function_name
            },
            "contracts": contract_contexts
        }
    
    def analyze(self, action):
        """Main analysis workflow"""
        # Step 1: Build complete context
        context = self._build_action_context(action)
        
        # Step 2: Generate LLM prompt for state changes
        prompt = self._generate_state_change_prompt(context)
        
        # Step 3: Get state change analysis from LLM
        analyzer = ThreeStageAnalyzer(ActionExecution)
        action_execution = analyzer.ask_llm(prompt)
        
        # Step 4: Generate detailed action description
        detail_prompt = self._generate_detail_prompt(action_execution)
        action_detail = analyzer.ask_llm(detail_prompt)
        
        return {
            "execution": action_execution,
            "detail": action_detail,
            "context": context
        }
    
    def _generate_state_change_prompt(self, context) -> str:
        """Generate prompt for state change analysis"""
        contracts_text = "\n\n".join(
            f"Contract: {c['name']}\n"
            f"Code:\n{c['code']}\n"
            f"ABI:\n{json.dumps(c['abi'], indent=2)}"
            for c in context['contracts']
        )
        
        return f"""
Analyze the state changes for this action:

Action: {context['action']['name']}
Description: {context['action']['summary']}
Main Contract: {context['action']['contract']}
Main Function: {context['action']['function']}

Contracts Involved:
{contracts_text}

Please analyze:
1. Which state variables are modified
2. When they are modified (conditions/timing)
3. What new identifiers are created

Return analysis in JSON matching ActionExecution schema.
"""
    
    def _generate_detail_prompt(self, action_execution) -> str:
        """Generate prompt for detailed action description"""
        return f"""
Based on this state change analysis, create detailed action instructions:

{json.dumps(action_execution.dict(), indent=2)}

Generate:
1. Parameter generation rules
2. State update descriptions  
3. Validation rules

Return in JSON matching ActionDetail schema.
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

# if __name__ == "__main__":
#     # Example usage
#     # project_path = "/tmp/workspaces/de71c43b-9ae9-462c-a97e-3b5c46498193/stablebase"
#     project_path = "/tmp/workspaces/s2/stablebase"
#     contract_name = "StableBaseCDP.sol"
#     # entry_func_full_name = "liquidate()"
#     entry_func_full_name = "openSafe(uint256,uint256)"
#     os.environ["SOLC_ARGS"] = "--allow-paths .,node_modules"
#     local_function_tree = extract_local_function_tree(project_path, contract_name, entry_func_full_name)
#     for func_name, code in local_function_tree.items():
#         print(f"Function: {func_name}\nCode:\n{code}\n")

if __name__ == "__main__":
    # Setup test environment
    def cws(self):
            return "/tmp/workspaces/s2/stablebase"
    
    from app.models import Action
    
    test_action = Action(
        name="openSafe",
        summary="Open a new safe position",
        contract_name="StableBaseCDP",
        function_name="openSafe(uint256,uint256)",
        probability=1.0
    )
    
    # context = MockContext()
    context = example_contexts[1]
    analyzer = ActionAnalyzer(test_action, context)
    
    # Test 1: Call tree extraction
    print("Testing call tree extraction...")
    call_tree = analyzer._get_function_call_tree("StableBaseCDP", "openSafe(uint256,uint256)")
    print(f"Found {len(call_tree)} functions in call tree")
    
    # Test 2: Full analysis
    print("\nRunning full analysis...")
    result = analyzer.analyze(test_action)
    
    print("\nAnalysis Results:")
    print(result)
    
    
    # Save results for inspection
    with open("action_analysis.json", "w") as f:
        json.dump({
            "execution": result["execution"].dict(),
            "detail": result["detail"].dict()
        }, f, indent=2)
    
    print("\nSaved results to action_analysis.json")