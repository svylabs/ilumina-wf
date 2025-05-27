import re
import json
import subprocess
import dotenv
dotenv.load_dotenv()
from dataclasses import dataclass
from typing import List, Dict, Optional, Union
import os
import tempfile
from typing import List, Dict
from slither.slither import Slither
from slither.core.declarations import Function, Contract
from slither.core.variables.state_variable import StateVariable
from .context import RunContext, prepare_context_lazy
from .models import DeploymentInstruction, ContractReference, ContractReferences
from .three_stage_llm_call import ThreeStageAnalyzer
#from app.context import prepare_context_lazy


# Core Analyzer
class ContractReferenceAnalyzer:
    def __init__(
        self,
        context: RunContext,
        slither=None
    ):
        self.context = context
        if slither is None:
            self.slither = Slither(context.cws())
        else:
            self.slither = slither

    def analyze(
        self,
        deployment_instructions: DeploymentInstruction,
        contract_name: str
    ) -> ContractReferences:
        """
        Full Analysis:
        1. Extract contract references from state variables.
        2. Match with concrete implementations in deployment.
        3. Use LLM fallback for unresolved cases.
        """
        # Step 1: Extract references (Slither -> Regex fallback)
        references = self.find_contract_references(contract_name)
        direct_initializations = references[0]
        initialization_with_constructors_functions = references[1]
        inline_casts = references[2]

        known_references = []

        contract_references = []
        for init in direct_initializations:
            known_references.append(init["variable"])
            contract_references.append(
                ContractReference(
                    state_variable_name=init["variable"],
                    contract_name=init["implementation"]
                )
            )

        references_to_resolve = []

        for init in initialization_with_constructors_functions:
            known_references.append(init["variable"])
            references_to_resolve.append(
                    {
                        "state_variable_name": init["variable"],
                        "initialization_expression": init["assignment_expression"],
                        "initialized_function": init["assigned_in"],
                    }
                )
        possible_address_assignments = []
        for cast in inline_casts:
            if cast["variable"].startswith("TMP_") and (cast["cast_from"] != "" and cast["cast_from"] is not None):
                if cast["cast_from"] not in possible_address_assignments:
                    possible_address_assignments.append(cast["cast_from"])

        
        address_assignments = self.extract_address_assignments(contract_name, possible_address_assignments)
        for assignment in address_assignments:
            if assignment["variable"] not in known_references:
                known_references.append(assignment["variable"])
                references_to_resolve.append(
                    {
                        "state_variable_name": assignment["variable"],
                        "initialization_expression": assignment["assignment_expression"],
                        "initialized_function": assignment["assigned_in"],
                    }
                )
        
        # Step 2: Call LLM to resolve contract references based on deployment instructions:
        prompt = self._construct_prompt(contract_name, references_to_resolve, deployment_instructions)
        #print(f"Constructed prompt for LLM:\n{prompt}")
        llm = ThreeStageAnalyzer(ContractReferences)
        result = llm.ask_llm(prompt)
        for ref in contract_references:
            result.references.append(ref)
        return result
    
    def _construct_prompt(
        self,
        contract_name: str,
        references: List[Dict],
        deployment_instructions: DeploymentInstruction
    ) -> str:
        """
        Construct a prompt for LLM to resolve contract references.
        """
        prompt = f"""
        Here is a list of contract references that need to be resolved. By references what I mean is, one contract can refer to other contracts. 
        The references are generally state variables that are initialized during deployment.

        The references(state variables) to resolve for {contract_name} are:

        References:
        {json.dumps(references, indent=2)}

        Deployment Instructions:
        {deployment_instructions.to_dict()}

        Please provide a list of resolved contract names for the state variables based on deployment instructions.
        """
        return prompt

    def resolve_assignment_expression(self, func, value_name: str, depth=0, visited=None) -> str:
        if visited is None:
            visited = set()
        if value_name in visited or depth > 5:
            return value_name  # avoid infinite loops
        visited.add(value_name)

        for node in func.nodes:
            for ir in node.irs:
                # Match the IR instruction where the temp var is defined
                if hasattr(ir, 'lvalue') and str(ir.lvalue) == value_name:
                    # Try to resolve known forms of RHS
                    if hasattr(ir, 'rvalue') and ir.rvalue:
                        rvalue = ir.rvalue
                        rvalue_str = str(rvalue)
                        if rvalue_str.startswith("TMP_"):
                            return self.resolve_assignment_expression(func, rvalue_str, depth + 1, visited)
                        return rvalue_str
                    elif hasattr(ir, 'expression'):
                        return str(ir.expression)
                    elif hasattr(ir, 'value'):
                        return str(ir.value)
                    else:
                        return str(ir)  # fallback

        return value_name  # unresolved



    def find_contract_references(self, contract_name: str) -> List[Dict]:
        result = []
        direct_initializations = []
        initialization_with_constructors_functions = []
        inline_casts = []

        for contract in self.slither.contracts:
            if contract.name != contract_name:
                continue

            # All contract-type state variables
            state_vars = {
                var.name: var
                for var in contract.state_variables
                if hasattr(var.type, "type") and isinstance(var.type.type, Contract)
            }

            # Case 1: Declaration-time assignments (e.g., new ConcreteContract())
            for var in state_vars.values():
                if var.initialized and var.expression:
                    expr_str = str(var.expression)
                    if "new " in expr_str:
                        # Try to extract contract name (e.g., new ChainlinkOracle(...) → ChainlinkOracle)
                        contract_name = expr_str.split("new ")[1].split("(")[0].strip()
                        direct_initializations.append({
                            "variable": var.name,
                            "contract_type": var.type.name,
                            "assignment_type": "declaration_new",
                            "implementation": contract_name,
                            "assignment_expression": expr_str,
                            "line": var.source_mapping.start_line
                        })

            # Case 2: Assignments to state vars (in constructor or functions)
            for function in contract.functions:
                for node in function.nodes:
                    for ir in node.irs:
                        # check if the LHS is a state variable
                        if hasattr(ir, "lvalue") and isinstance(ir.lvalue, StateVariable):
                            #print(f"Found state variable assignment in {function.full_name}: {ir.lvalue}")
                            var_name = ir.lvalue.name
                            if var_name not in state_vars:
                                continue

                            raw_expr = str(getattr(ir, "rvalue", "unknown"))
                            assignment_expression = (
                                self.resolve_assignment_expression(function, raw_expr)
                                if raw_expr.startswith("TMP_")
                                else raw_expr
                            )

                            assignment = {
                                "variable": var_name,
                                "contract_type": state_vars[var_name].type.type.name,
                                "assigned_in": function.full_name,
                                "assignment_expression": assignment_expression,
                                "line": getattr(node.source_mapping, "start", -1)
                            }
                            initialization_with_constructors_functions.append(assignment)


            # Case 3: Inline casts in external calls (e.g., IOracle(addr).fetchPrice())
            for func in contract.functions:
                for node in func.nodes:
                    for ir in node.irs:
                        if hasattr(ir, "destination"):
                            dest = ir.destination
                            if hasattr(dest, "type") and hasattr(dest.type, "type") and isinstance(dest.type.type, Contract):
                                cast_from = self.find_original_cast_source(func, ir.destination)
                                inline_casts.append({
                                    "variable": dest.name,
                                    "inline_call_cast": True,
                                    "cast_to": dest.type.type.name,
                                    "used_in_function": func.full_name,
                                    "line": node.source_mapping.start,
                                    "cast_from": cast_from
                                })

        return direct_initializations, initialization_with_constructors_functions, inline_casts

    def find_original_cast_source(self, func, tmp_var):
        """
        Trace TMP variable back to its cast source expression like stableBaseCDP
        from IRewardSender(stableBaseCDP)
        """
        for node in func.nodes:
            for ir in node.irs:
                if hasattr(ir, 'lvalue') and str(ir.lvalue) == str(tmp_var):
                    expr = None

                    if hasattr(ir, 'expression'):
                        expr = str(ir.expression)
                    elif hasattr(ir, 'value'):
                        expr = str(ir.value)
                    else:
                        expr = str(ir)

                    # Strip the cast wrapper like: IInterface(x) → x
                    if "(" in expr and ")" in expr:
                        try:
                            inner = expr.split("(", 1)[1].rsplit(")", 1)[0]
                            return inner.strip()
                        except IndexError:
                            return expr  # fallback: return full

                    return expr

        return None
    
    def extract_address_assignments(self, contract_name: str, target_vars: List[str]) -> List[Dict]:
        results = []

        for contract in self.slither.contracts:
            if contract.name != contract_name:
                continue

            for func in contract.functions:
                for node in func.nodes:
                    for ir in node.irs:
                        if hasattr(ir, "lvalue"):
                            var_name = str(ir.lvalue)

                            if var_name in target_vars:
                                var_type = getattr(ir.lvalue, "type", None)
                                if not var_type or "address" not in str(var_type):
                                    continue  # skip non-address types

                                # Get the RHS (rvalue)
                                rhs = (
                                    str(getattr(ir, "rvalue", None)) or
                                    str(getattr(ir, "expression", None)) or
                                    str(getattr(ir, "value", None)) or
                                    "unknown"
                                )

                                results.append({
                                    "variable": var_name,
                                    "assigned_in": func.full_name,
                                    "assignment_expression": rhs,
                                    "line": getattr(node.source_mapping, "start", -1)
                                })

        return results





# Example Usage
if __name__ == "__main__":
    project_path = "/tmp/workspaces/b2467fc4-e77a-4529-bcea-09c31cb2e8fe/stablebase"
    contract_name = "StabilityPool"
    context = prepare_context_lazy({
        "run_id": "1747743579",
        "submission_id": "b2467fc4-e77a-4529-bcea-09c31cb2e8fe",
        "github_repository_url": "https://github.com/svylabs/stablebase"
    })
    analyzer = ContractReferenceAnalyzer(context)
    print(f"Extracting contract references for contract: {contract_name} in {project_path}")
    print (context.deployment_instructions())
    result = analyzer.analyze(
        context.deployment_instructions(),
        "StableBaseCDP"
    )
    print("Contract References:")
    for ref in result.references:
        print(f"State Variable: {ref.state_variable_name}, Contract: {ref.contract_name}")
