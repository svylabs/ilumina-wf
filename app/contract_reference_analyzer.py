import re
import json
import subprocess
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class ContractReference:
    state_variable_name: str
    contract_type: str  # Interface/contract name (e.g., IStabilityPool)
    initialization: Optional[Dict] = None  # {method: str, params: List[str], code_snippet: str}

@dataclass
class ContractAnalysisResult:
    contract_name: str
    references: List[ContractReference]
    deployment_matches: Dict[str, str]  # var_name -> deployment_code_snippet

class ContractReferenceAnalyzer:
    def __init__(self, use_slither: bool = True, llm_fallback: bool = True):
        self.use_slither = use_slither
        self.llm_fallback = llm_fallback

    def analyze(
        self,
        contract_code: str,
        deployment_code: str,
        contract_name: str
    ) -> ContractAnalysisResult:
        """Hybrid analysis with static + LLM fallback"""
        # Step 1: Static Extraction
        references = self._extract_references_static(contract_code, contract_name)
        
        # Step 2: Dynamic Deployment Matching
        result = self._match_deployment_initializers(references, deployment_code, contract_name)
        
        # Step 3: LLM Validation (if enabled)
        if self.llm_fallback and self._needs_llm_fallback(result):
            llm_result = self._analyze_with_llm(contract_code, deployment_code, contract_name)
            if llm_result:
                return llm_result
        
        return result

    def _extract_references_static(self, code: str, contract_name: str) -> List[ContractReference]:
        """Extract contract references using Slither + regex fallback"""
        references = []
        
        # Option 1: Slither (more accurate)
        if self.use_slither:
            try:
                slither_result = self._run_slither(code, contract_name)
                for var in slither_result.get("state_variables", []):
                    if self._is_contract_reference(var["type"]):
                        references.append(
                            ContractReference(
                                state_variable_name=var["name"],
                                contract_type=var["type"]
                            )
                        )
                return references
            except Exception:
                pass  # Fallback to regex
        
        # Option 2: Regex (fallback)
        # Matches: `IStabilityPool public stabilityPool;`
        pattern = r"([A-Za-z0-9_]+)\s+(public|private|internal)?\s*([A-Za-z0-9_]+)\s*;"
        matches = re.finditer(pattern, code)
        for match in matches:
            contract_type = match.group(1)
            var_name = match.group(3)
            # Heuristic: contract_type starts with uppercase and not a primitive
            if contract_type[0].isupper() and contract_type not in ["uint256", "address", "string", "bool"]:
                references.append(
                    ContractReference(
                        state_variable_name=var_name,
                        contract_type=contract_type
                    )
                )
        
        return references

    def _match_deployment_initializers(
        self,
        references: List[ContractReference],
        deployment_code: str,
        contract_name: str
    ) -> ContractAnalysisResult:
        """Match references with deployment script initializations"""
        deployment_matches = {}
        updated_references = []
        
        for ref in references:
            # Case 1: Direct assignment (e.g., `stabilityPool = new StabilityPool()`)
            direct_pattern = rf"{ref.state_variable_name}\s*=\s*(.*?);"
            direct_match = re.search(direct_pattern, deployment_code)
            
            # Case 2: Method call (e.g., `setStabilityPool(address(stabilityPool))`)
            method_pattern = rf"\.(\w+Address|set\w+)\s*\((.*?)\)"
            method_matches = re.finditer(method_pattern, deployment_code)
            
            if direct_match:
                ref.initialization = {
                    "method": "direct_assignment",
                    "params": [direct_match.group(1)],
                    "code_snippet": direct_match.group(0)
                }
                deployment_matches[ref.state_variable_name] = direct_match.group(0)
            else:
                # Check method calls
                for match in method_matches:
                    if ref.state_variable_name.lower() in match.group(0).lower():
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

    def _analyze_with_llm(self, contract_code: str, deployment_code: str, contract_name: str) -> Optional[ContractAnalysisResult]:
        """LLM fallback for complex cases using ThreeStageAnalyzer"""
        try:
            from app.three_stage_llm_call import ThreeStageAnalyzer
        except ImportError:
            print("ThreeStageAnalyzer not available. Skipping LLM fallback.")
            return None
        analyzer = ThreeStageAnalyzer()
        try:
            data = analyzer.analyze_contract_references(contract_code, deployment_code, contract_name)
            references = [
                ContractReference(
                    state_variable_name=ref["variable"],
                    contract_type=ref["contract_type"],
                    initialization=ref.get("initialization")
                ) for ref in data.get("references", [])
            ]
            return ContractAnalysisResult(
                contract_name=contract_name,
                references=references,
                deployment_matches={ref.state_variable_name: ref.initialization["code_snippet"] 
                                  for ref in references if ref.initialization}
            )
        except Exception as e:
            print(f"ThreeStageAnalyzer fallback failed: {e}")
            return None

    def _needs_llm_fallback(self, result: ContractAnalysisResult) -> bool:
        """Check if LLM fallback is needed (missing initializations)"""
        return any(ref.initialization is None for ref in result.references)

    def _run_slither(self, code: str, contract_name: str) -> Dict:
        """Run Slither analysis (simplified example)"""
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix='.sol', delete=False, mode='w') as f:
            f.write(code)
            temp_path = f.name
        try:
            result = subprocess.run([
                'slither', temp_path, '--json', temp_path + '.json'
            ], capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Slither failed: {result.stderr}")
            with open(temp_path + '.json', 'r') as jf:
                data = json.load(jf)
            # Find the contract by name
            for contract in data.get('contracts', []):
                if contract.get('name') == contract_name:
                    return {"state_variables": contract.get('stateVariables', [])}
            return {"state_variables": []}
        finally:
            os.remove(temp_path)
            if os.path.exists(temp_path + '.json'):
                os.remove(temp_path + '.json')

    def _is_contract_reference(self, var_type: str) -> bool:
        # Heuristic: contract reference types start with uppercase and are not primitives
        return var_type[0].isupper() and var_type not in ["uint256", "address", "string", "bool"]

# Example usage
if __name__ == "__main__":
    contract_code = """
    contract StableBaseCDP {
        StabilityPool public stabilityPool;
        DFIDToken public dfidToken;
        DFireToken public dfireToken;
        uint256 public totalDebt;
        mapping(address => uint256) public savings;
    }
    """
    deployment_code = """
    // Example deployment script
    stabilityPool = new MockStabilityPool();
    dfidToken = new MockDFIDToken();
    dfireToken = new MockDFireToken();
    """
    analyzer = ContractReferenceAnalyzer(use_slither=False, llm_fallback=False)
    result = analyzer.analyze(contract_code, deployment_code, contract_name="StableBaseCDP")
    print(json.dumps({
        "contract_name": result.contract_name,
        "references": [ref.__dict__ for ref in result.references],
        "deployment_matches": result.deployment_matches
    }, indent=2))
