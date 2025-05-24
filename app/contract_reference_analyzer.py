import re
import json
import subprocess
from dataclasses import dataclass
from typing import List, Dict, Optional, Union
import os
import tempfile
from typing import List, Dict
from slither.slither import Slither
from slither.core.declarations import Function, Contract
from slither.core.variables.state_variable import StateVariable
#from app.context import prepare_context_lazy

# Data Models
@dataclass
class ContractReference:
    state_variable_name: str
    interface_type: str  # Interface (e.g., IStabilityPool)
    concrete_implementation: Optional[str] = None  # Actual deployed contract (e.g., MockStabilityPool)
    initialization: Optional[Dict] = None  # {method: str, params: List[str], code_snippet: str}

@dataclass
class ContractAnalysisResult:
    contract_name: str
    references: List[ContractReference]
    deployment_matches: Dict[str, str]  # var_name -> deployment_code_snippet

# Core Analyzer
class ContractReferenceAnalyzer:
    def __init__(
        self,
        use_slither: bool = True,
        llm_fallback: bool = True,
        solc_version: Optional[str] = None
    ):
        self.use_slither = use_slither
        self.llm_fallback = llm_fallback
        self.solc_version = solc_version

    def analyze(
        self,
        contract_code: str,
        deployment_instructions: Union[str, Dict],
        contract_name: str
    ) -> ContractAnalysisResult:
        """
        Full Analysis:
        1. Extract contract references from state variables.
        2. Match with concrete implementations in deployment.
        3. Use LLM fallback for unresolved cases.
        """
        # Step 1: Extract references (Slither -> Regex fallback)
        references = self._extract_references_static(contract_code, contract_name)
        
        # Step 2: Parse deployment instructions (supports scripts/JSON)
        deployment_code = self._normalize_deployment_instructions(deployment_instructions)
        
        # Step 3: Match initializations
        result = self._match_deployment_initializers(references, deployment_code, contract_name)
        
        # Step 4: LLM fallback for unresolved references
        if self.llm_fallback and self._needs_llm_fallback(result):
            llm_result = self._analyze_with_llm(contract_code, deployment_code, contract_name)
            if llm_result:
                return llm_result
        
        return result

    # Step 1: Static Reference Extraction
    def _extract_references_static(self, code: str, contract_name: str) -> List[ContractReference]:
        """Extract contract references using Slither (with regex fallback)."""
        references = []
        
        # Option 1: Slither (accurate)
        if self.use_slither:
            try:
                slither_vars = self._run_slither(code, contract_name)
                for var in slither_vars:
                    if self._is_contract_reference(var["type"]):
                        references.append(
                            ContractReference(
                                state_variable_name=var["name"],
                                interface_type=var["type"]
                            )
                        )
                return references
            except Exception as e:
                print(f"Slither failed, falling back to regex: {e}")
        
        # Option 2: Regex fallback
        # Matches: `IStabilityPool public stabilityPool;` or `StabilityPool stabilityPool;`
        pattern = r"(I?[A-Z][a-zA-Z0-9]*)\s+(?:public|private|internal)?\s*([a-zA-Z0-9_]+)\s*;"
        matches = re.finditer(pattern, code)
        for match in matches:
            contract_type, var_name = match.group(1), match.group(2)
            if self._is_contract_reference(contract_type):
                references.append(
                    ContractReference(
                        state_variable_name=var_name,
                        interface_type=contract_type
                    )
                )
        
        return references

    def _is_contract_reference(self, var_type: str) -> bool:
        """Heuristic: Is this type likely a contract reference?"""
        return (
            var_type[0].isupper()  # Uppercase (Solidity naming convention)
            and var_type not in ["uint256", "string", "bool"]  # Not a primitive
            and not var_type.startswith(("mapping", "array", "uint", "int"))  # Not a complex type
        )

    # Step 2: Deployment Initialization Matching
    def _normalize_deployment_instructions(self, instructions: Union[str, Dict]) -> str:
        """Convert deployment config (JSON/script) into parseable text."""
        if isinstance(instructions, dict):
            return json.dumps(instructions)
        return instructions

    def _match_deployment_initializers(
        self,
        references: List[ContractReference],
        deployment_code: str,
        contract_name: str
    ) -> ContractAnalysisResult:
        """Match references with deployment initializations."""
        deployment_matches = {}
        updated_references = []
        
        for ref in references:
            # Case 1: Direct assignment (e.g., `stabilityPool = new MockStabilityPool()`)
            direct_pattern = rf"{ref.state_variable_name}\s*=\s*(.*?);"
            direct_match = re.search(direct_pattern, deployment_code)
            
            # Case 2: Method call (e.g., `setStabilityPool(address(stabilityPool))`)
            method_pattern = rf"\.(set\w+|setAddresses)\s*\((.*?)\)"
            method_matches = re.finditer(method_pattern, deployment_code)
            
            # Case 3: Constructor initialization
            constructor_pattern = rf"constructor\s*\(.*?{ref.interface_type}\s+{ref.state_variable_name}.*?\)"
            constructor_match = re.search(constructor_pattern, deployment_code)
            
            if direct_match:
                impl = self._extract_concrete_implementation(direct_match.group(1))
                ref.concrete_implementation = impl
                ref.initialization = {
                    "method": "direct_assignment",
                    "params": [direct_match.group(1)],
                    "code_snippet": direct_match.group(0)
                }
                deployment_matches[ref.state_variable_name] = direct_match.group(0)
            elif constructor_match:
                ref.initialization = {
                    "method": "constructor",
                    "params": [],
                    "code_snippet": constructor_match.group(0)
                }
            else:
                # Check method calls
                for match in method_matches:
                    if ref.state_variable_name.lower() in match.group(0).lower():
                        impl = self._extract_concrete_implementation(match.group(2))
                        ref.concrete_implementation = impl
                        ref.initialization = {
                            "method": match.group(1),
                            "params": [p.strip() for p in match.group(2).split(",")],
                            "code_snippet": match.group(0)
                        }
                        deployment_matches[ref.state_variable_name] = match.group(0)
                        break
            
            updated_references.append(ref)
        
        return ContractAnalysisResult(
            contract_name=contract_name,
            references=updated_references,
            deployment_matches=deployment_matches
        )

    def _extract_concrete_implementation(self, code_snippet: str) -> Optional[str]:
        """Extract concrete contract type from initialization code."""
        # Example: `new MockStabilityPool()` -> "MockStabilityPool"
        new_pattern = r"new\s+([A-Z][a-zA-Z0-9]*)"
        match = re.search(new_pattern, code_snippet)
        return match.group(1) if match else None

    # Step 3: LLM Fallback
    def _analyze_with_llm(
        self,
        contract_code: str,
        deployment_code: str,
        contract_name: str
    ) -> Optional[ContractAnalysisResult]:
        """Use LLM to resolve ambiguous references."""
        try:
            from app.three_stage_llm_call import ThreeStageAnalyzer  # Your custom LLM analyzer
            analyzer = ThreeStageAnalyzer()
            llm_result = analyzer.analyze_contract_references(
                contract_code,
                deployment_code,
                contract_name
            )
            references = [
                ContractReference(
                    state_variable_name=ref["variable"],
                    interface_type=ref["interface"],
                    concrete_implementation=ref.get("implementation"),
                    initialization=ref.get("initialization")
                )
                for ref in llm_result.get("references", [])
            ]
            return ContractAnalysisResult(
                contract_name=contract_name,
                references=references,
                deployment_matches={
                    ref.state_variable_name: ref.initialization["code_snippet"]
                    for ref in references if ref.initialization
                }
            )
        except Exception as e:
            print(f"LLM fallback failed: {e}")
            return None

    def _needs_llm_fallback(self, result: ContractAnalysisResult) -> bool:
        """Check if any references lack initialization info."""
        return any(
            ref.initialization is None or ref.concrete_implementation is None
            for ref in result.references
        )

    # Slither Integration
    def _run_slither(self, project_path: str, contract_name: str) -> List[Dict]:
        """Run Slither directly via Python API and extract state variables for a contract."""
        slither = Slither(project_path)
        for contract in slither.contracts:
            if contract.name == contract_name:
                return [
                    {
                        "name": var.name,
                        "type": str(var.type),
                        "visibility": var.visibility,
                        #"src": var.source_mapping.content,
                        "expression": var.expression
                    }
                    for var in contract.state_variables
                ]
        return []
    
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



    def find_contract_references(self, project_path: str, contract_name: str) -> List[Dict]:
        slither = Slither(project_path)
        result = []

        for contract in slither.contracts:
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
                        result.append({
                            "variable": var.name,
                            "contract_type": var.type.name,
                            "assignment_type": "declaration_new",
                            "implementation": contract_name,
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
                            result.append(assignment)


            # Case 3: Inline casts in external calls (e.g., IOracle(addr).fetchPrice())
            for func in contract.functions:
                for node in func.nodes:
                    for ir in node.irs:
                        if hasattr(ir, "destination"):
                            dest = ir.destination
                            if hasattr(dest, "type") and hasattr(dest.type, "type") and isinstance(dest.type.type, Contract):
                                cast_from = self.find_original_cast_source(func, ir.destination)
                                result.append({
                                    "variable": dest.name,
                                    "inline_call_cast": True,
                                    "cast_to": dest.type.type.name,
                                    "used_in_function": func.full_name,
                                    "line": node.source_mapping.start,
                                    "cast_from": cast_from
                                })

        return result

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
    
    def extract_address_assignments(self, project_path: str, contract_name: str, target_vars: List[str]) -> List[Dict]:
        slither = Slither(project_path)
        results = []

        for contract in slither.contracts:
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
    """context = prepare_context_lazy({
        "run_id": "1746304145",
        "submission_id": "b2467fc4-e77a-4529-bcea-09c31cb2e8fe",
        "github_repository_url": "https://github.com/svylabs/stablebase"
    })"""
    analyzer = ContractReferenceAnalyzer(use_slither=True, llm_fallback=True)
    print(f"Extracting contract references for contract: {contract_name} in {project_path}")
    state_vars = analyzer._run_slither(project_path, contract_name)
    print("State Variables:")
    for var in state_vars:
        print(f"- {var['name']} ({var['type']}, {var['visibility']}), {var['expression']})")

    references = [
        ContractReference(state_variable_name=var['name'], interface_type=var['type'])
        for var in state_vars if analyzer._is_contract_reference(var['type'])
    ]
    print("\nContract References:")
    for ref in references:
        print(f"- {ref.state_variable_name}: {ref.interface_type}")
    

    result = analyzer.find_contract_references(project_path, contract_name)
    print("\nContract References from Slither:")
    for ref in result:
        print(f"- {ref}")

    result = analyzer.extract_address_assignments(project_path, contract_name, ["stableBaseCDP"])
    print("\nCasts from Address Variables:")
    for ref in result:
        print(f"- {ref}")
