import re
import json
import subprocess
from dataclasses import dataclass
from typing import List, Dict, Optional, Union
import os
import tempfile

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
            and var_type not in ["uint256", "address", "string", "bool"]  # Not a primitive
            and not var_type.startswith(("mapping", "array"))  # Not a complex type
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
        from slither.slither import Slither
        slither = Slither(project_path)
        for contract in slither.contracts:
            if contract.name == contract_name:
                return [
                    {
                        "name": var.name,
                        "type": var.type,
                        "visibility": var.visibility,
                        "src": var.source_mapping.content
                    }
                    for var in contract.state_variables
                ]
        return []

# Example Usage
if __name__ == "__main__":
    # Example Contract
    contract_code = """
    pragma solidity ^0.8.0;
    interface IStabilityPool {}
    interface IDFireToken {}
    contract StableBaseCDP {
        IStabilityPool public stabilityPool;
        IDFireToken public dfireToken;
        address public owner;
        constructor(IStabilityPool _stabilityPool) {
            stabilityPool = _stabilityPool;
        }
    }
    """
    
    # Example Deployment Script
    deployment_code = """
    // Deploy mocks
    MockStabilityPool stabilityPool = new MockStabilityPool();
    DFireToken dfireToken = new DFireToken();
    // Initialize StableBaseCDP
    StableBaseCDP cdp = new StableBaseCDP(stabilityPool);
    cdp.setDFireToken(dfireToken);
    """
    
    analyzer = ContractReferenceAnalyzer(use_slither=False, llm_fallback=True)
    result = analyzer.analyze(contract_code, deployment_code, "StableBaseCDP")
    
    print("===== Analysis Result =====")
    print(f"Contract: {result.contract_name}")
    for ref in result.references:
        print(f"\nState Variable: {ref.state_variable_name}")
        print(f"  - Interface: {ref.interface_type}")
        print(f"  - Implementation: {ref.concrete_implementation}")
        if ref.initialization:
            print(f"  - Initialized via: {ref.initialization['method']}")
            print(f"  - Code: {ref.initialization['code_snippet']}")
    
    # Example usage with real project data (like in action_analyzer)
    # Set your real project path and contract name here
    project_path = "/tmp/workspaces/s2/stablebase"  # Example path
    contract_name = "StableBaseCDP"
    analyzer = ContractReferenceAnalyzer(use_slither=True, llm_fallback=True)
    print(f"Extracting state variables for contract: {contract_name} in {project_path}")
    state_vars = analyzer._run_slither(project_path, contract_name)
    print("State Variables:")
    for var in state_vars:
        print(f"- {var['name']} ({var['type']}, {var['visibility']})")
        # Optionally print source code: print(var['src'])
