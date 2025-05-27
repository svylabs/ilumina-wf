import os
from dotenv import load_dotenv
load_dotenv()
import json
from slither.slither import Slither
from slither.core.declarations import Function
from slither.slithir.operations import InternalCall, HighLevelCall
from .compiler import Compiler
from .three_stage_llm_call import ThreeStageAnalyzer
from .models import ActionExecution, ActionDetail, ContractReferences
from .context import example_contexts, prepare_context_lazy
from .contract_reference_analyzer import ContractReferenceAnalyzer

class ActionAnalyzer:
    def __init__(self, action, context):
        self.action = action
        self.context = context

    def _get_contract_code(self, contract_name: str) -> str:
        """Get full source code for a contract"""
        contract_path = os.path.join(self.context.cws(), f"{contract_name}.sol")
        with open(contract_path, "r") as f:
            return f.read()
        
    def extract_local_function_tree(self, project_path: str, contract_name: str, entry_func_full_name: str) -> dict:
        slither = Slither(project_path)
        local_root = os.path.abspath(project_path if os.path.isdir(project_path) else os.path.dirname(project_path))
        print(f"Local root: {local_root}")

        # Step 1: Map all locally defined functions
        all_funcs = {}  # full_name -> Function
        funcs_by_name = {}  # short name -> list of Functions (for fallback matching)
        contract_reference_analyzer = ContractReferenceAnalyzer(context, slither=slither)

        deployment_instructions = self.context.deployment_instructions()
        contract_map = {}
        for contract in slither.contracts:
            if contract.is_interface:
                continue
            contract_map[contract.name] = contract
        
        contract_references = contract_reference_analyzer.analyze(deployment_instructions, contract_name)

        result = {} # A mapping of contract_name and list of functions called by the entry function

        for contract in slither.contracts:
            if contract.is_interface:
                continue
            for func in contract.functions:
                src_path = func.source_mapping.filename.absolute
                if src_path and local_root in os.path.abspath(src_path):
                    all_funcs[contract.name + "_" + func.full_name] = func
                    print (f"Found local function: {contract.name}_{func.full_name} in {src_path}")
                    funcs_by_name.setdefault(func.name, []).append(func)
            

        if contract_name + "_"+ entry_func_full_name not in all_funcs:
            print("Available function full names detected by Slither:")
            for fname in all_funcs.keys():
                print(f"  - {fname}")
            raise ValueError(f"Function '{entry_func_full_name}' not found in local project.")

        visited = set()
        result = {}

        def visit(contract_name: str, func: Function):
            if contract_name + "_" + func.full_name in visited:
                return
            visited.add(contract_name + "_" + func.full_name)
            # result[func.full_name] = func.source_mapping.content
            result[contract_name + "_" + func.full_name] = func

            for node in func.nodes:
                for ir in node.irs:
                    # Internal call to a known local function
                    if isinstance(ir, InternalCall):
                        callee = ir.function
                        if isinstance(callee, Function) and callee.full_name in all_funcs:
                            visit(contract_name, all_funcs[contract_name + "_" + callee.full_name])

                    # External call (possibly to another local contract or library)
                    elif isinstance(ir, HighLevelCall):
                        # First: direct function resolution (if available)
                        if isinstance(ir.function, Function):
                            callee = ir.function
                            destination = ir.destination
                            resolved_contract = self.resolve_contract(callee, destination.name, contract_references)
                            full_name = f"{resolved_contract}_{callee.full_name}" if resolved_contract else callee.full_name
                            print(f"Visiting function: {full_name} in contract {contract_name}")
                            if full_name in all_funcs:
                                visit(resolved_contract, all_funcs[full_name])
                        """
                        else:
                            # Fallback: match by function name
                            called_name = ir.function_name
                            if called_name in funcs_by_name and len(funcs_by_name[called_name]) == 1:
                                possible_callee = funcs_by_name[called_name][0]
                                if possible_callee.full_name in all_funcs:
                                    visit(all_funcs[possible_callee.full_name])
                        """

        visit(contract_name, all_funcs[contract_name + "_" + entry_func_full_name])
        return result
    
    def resolve_contract(self, func: Function, var_name: str, contract_references: ContractReferences, depth=0, max_depth=10):
        """
        Recursively resolve the contract type for a variable name used in a given function,
        tracing assignments and checking against known state variables via contract_references.
        """
        if depth > max_depth:
            return None  # Prevent infinite recursion

        # Check if var_name matches any known state variable reference
        for state_var in contract_references.references:
            if state_var.state_variable_name == var_name:
                return state_var.contract_name

        # Check if var_name is a parameter of the function
        for param in func.parameters:
            if param.name == var_name and param.type:
                return param.type.name  # Return the contract type from parameter definition

        # Walk through IR to trace variable assignment
        for node in func.nodes:
            for ir in node.irs:
                if hasattr(ir, 'destination') and hasattr(ir, 'value'):
                    dest = ir.destination
                    value = ir.value

                    if hasattr(dest, 'name') and dest.name == var_name:
                        if hasattr(value, 'name'):
                            origin_var_name = value.name
                            # Recurse to resolve the origin
                            return self.resolve_contract(func, origin_var_name, contract_references, depth + 1, max_depth)

        return None




    
    def _get_function_call_tree(self, contract_name: str, entry_function: str) -> dict:
        """Get all functions called by the entry function"""
        project_path = self.context.cws()
        return self.extract_local_function_tree(
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
        detail_analyzer = ThreeStageAnalyzer(ActionDetail)
        action_detail = detail_analyzer.ask_llm(detail_prompt)
        
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
        name="borrow",
        summary="Borrow from the protocol",
        contract_name="StableBaseCDP",
        function_name="borrow(uint256,uint256,uint256,uint256,uint256)",
        probability=1.0
    )
    
    # context = MockContext()
    #context = example_contexts[1]
    context = prepare_context_lazy({
        "run_id": "1747743579",
        "submission_id": "b2467fc4-e77a-4529-bcea-09c31cb2e8fe",
        "github_repository_url": "https://github.com/svylabs/stablebase"
    })
    analyzer = ActionAnalyzer(test_action, context)
    
    # Test 1: Call tree extraction
    print("Testing call tree extraction...")
    call_tree = analyzer._get_function_call_tree("StableBaseCDP", "borrow(uint256,uint256,uint256,uint256,uint256)")
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