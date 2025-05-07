#!/usr/bin/env python3
import json
import os
import re
import random
from pathlib import Path
from typing import Dict, List, Optional
from .context import RunContext
from .three_stage_llm_call import ThreeStageAnalyzer
from .models import ActionInstruction
# from .action_openai import ask_openai
from .compiler import Compiler

class ActionGenerator:
    def __init__(self, context: RunContext):
        self.context = context
        self.actions_dir = os.path.join(context.simulation_path(), "simulation", "actions")
        os.makedirs(self.actions_dir, exist_ok=True)
        self.compiler = Compiler(context)
        
        # Ensure context has a prng attribute
        if not hasattr(context, "prng"):
            context.prng = random.Random()  # Add a default PRNG if missing

    def generate_all_actions(self) -> List[Dict]:
        """Generate action files for all actors and actions"""
        # First compile contracts to get ABIs
        self.compiler.compile()

        with open(os.path.join(self.context.simulation_path(), "actor_summary.json"), "r") as f:
            actors = json.load(f).get("actors", [])
        
        results = []
        for actor in actors:
            for action in actor.get("actions", []):
                result = self._generate_action_file(
                    action["name"],
                    action["contract_name"],
                    action["function_name"],
                    action["summary"]
                )
                results.append({
                    "actor": actor["name"],
                    "action": action["name"],
                    "file_path": result["file_path"],
                    "status": "generated" if not result["existing"] else "skipped"
                })
        
        return results
    
    def generate_single_action(self, actor_name: str, action_name: str) -> Dict:
        """Generate a single action file for specific actor and action"""
        # First compile contracts to get ABIs
        self.compiler.compile()

        # Load actor data
        with open(os.path.join(self.context.simulation_path(), "actor_summary.json"), "r") as f:
            actors_data = json.load(f).get("actors", [])
        
        # Find the specific actor
        target_actor = next((a for a in actors_data if a["name"] == actor_name), None)
        if not target_actor:
            raise ValueError(f"Actor '{actor_name}' not found")
            
        # Find the specific action
        target_action = next((a for a in target_actor.get("actions", []) if a["name"] == action_name), None)
        if not target_action:
            raise ValueError(f"Action '{action_name}' not found for actor '{actor_name}'")
        
        # Generate the action file
        result = self._generate_action_file(
            target_action["name"],
            target_action["contract_name"],
            target_action["function_name"],
            target_action["summary"]
        )
        
        return {
            "file_path": result["file_path"],
            "action_details": {
                "actor": actor_name,
                "action": action_name,
                "contract": target_action["contract_name"],
                "function": target_action["function_name"],
                "status": "generated" if not result["existing"] else "skipped"
            }
        }

    def _solidity_to_ts_type(self, solidity_type: str) -> str:
        """Convert Solidity type to TypeScript type"""
        type_map = {
            "address": "string",
            "bool": "boolean",
            "string": "string",
            "uint": "bigint",
            "int": "bigint",
            "bytes": "string"
        }
        
        # Handle arrays
        if "[]" in solidity_type:
            base_type = solidity_type.replace("[]", "")
            return f"{self._solidity_to_ts_type(base_type)}[]"
        
        # Handle mappings
        if "mapping(" in solidity_type:
            return "Record<string, any>"
        
        # Handle tuples
        if "tuple" in solidity_type:
            return "any"
        
        for solidity, ts in type_map.items():
            if solidity_type.startswith(solidity):
                return ts
            
        return "any"

    def _sanitize_for_filename(self, name: str) -> str:
        """Sanitize name for safe filename: lowercase, underscore-separated."""
        cleaned = re.sub(r'[^\w\s]', '', name)  # Remove non-alphanum (keep spaces)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()  # Normalize whitespace
        return cleaned.lower().replace(' ', '_')
    
    def _sanitize_for_classname(self, name: str) -> str:
        """Sanitize name to generate PascalCase class name."""
        cleaned = re.sub(r'[^\w\s]', '', name)  # Remove non-alphanum (keep spaces)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return ''.join(word.capitalize() for word in cleaned.split())

    def _generate_time_offset(self) -> int:
        """Generate a reasonable time offset in seconds using context.prng"""
        return self.context.prng.randint(3600, 259200)  # 1 hour to 3 days

    def _generate_param_init_code(self, param_name: str, param_type: str, function_name: str) -> str:
        """Generate initialization code for a parameter using context.prng"""
        if param_name.lower().endswith("address"):
            return f"const {param_name} = actor.account.value; // Using actor's address"
        
        if "strategy" in param_name.lower():
            return f"const {param_name} = context.getStrategy('{param_name}'); // Get strategy from context"
        
        if "time" in param_name.lower():
            offset = self._generate_time_offset()
            return f"const {param_name} = Math.floor(Date.now() / 1000) + {offset}; // Current timestamp with offset"
        
        if param_type.startswith("uint") or param_type.startswith("int"):
            bits = param_type[4:] if param_type.startswith("uint") else param_type[3:]
            max_val = 2 ** (int(bits) if bits else 256) - 1
            return f"const {param_name} = new BigNumber(context.prng.next().toFixed()).mod({max_val}); // Random {param_type}"
        
        if param_type == "bool":
            return f"const {param_name} = context.prng.next() > 0.5; // Random boolean"
        
        if param_type == "string":
            return f"const {param_name} = `{function_name}_${{context.prng.next().toString(36).substring(2, 8)}}`; // Random string"
        
        if param_type.startswith("bytes"):
            size = int(param_type[5:]) if param_type[5:] else 32
            return (
                f"const {param_name} = ethers.hexlify(Uint8Array.from("
                f"Array.from({{length: {size}}}, () => Math.floor(context.prng.next() * 256)))); // Random bytes"
            )
        
        return f"const {param_name} = context.getParam('{param_name}') || '{param_name}_default'; // Get from context or use default"

    def _clean_generated_code(self, code: str) -> str:
        """Clean and format generated TypeScript code"""
        code = code.replace("```typescript", "").replace("```", "").strip()
        lines = code.split('\n')
        imports = []
        other_lines = []
        seen_imports = set()
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import"):
                if stripped not in seen_imports:
                    seen_imports.add(stripped)
                    imports.append(line)
            else:
                other_lines.append(line)
        
        imports.sort()
        return '\n'.join(imports + other_lines)

    def _generate_action_file(self, action_name: str, contract_name: str, 
                            function_name: str, summary: str):
        """Generate action file using LLM with enhanced validation"""
        filename = f"{self._sanitize_for_filename(action_name)}.ts"
        filepath = os.path.join(self.actions_dir, filename)
        
        # Return if file already exists
        if os.path.exists(filepath):
            return
            
        sanitized_class_name = self._sanitize_for_classname(action_name)
        class_name = sanitized_class_name + "Action"
        
        # Get ABI for the contract
        contract_abi = self.compiler.get_contract_abi(contract_name)
        if not contract_abi:
            raise Exception(f"ABI not found for contract: {contract_name}")
        
        # Find the function in ABI
        function_abi = None
        for item in contract_abi.get("abi", []):
            if item.get("name") == function_name:
                function_abi = item
                break
            # Fallback for unnamed items like constructor, fallback, receive
            if "name" not in item and item["type"] == function_name:
                function_abi = item
                break
        
        if not function_abi:
            raise Exception(f"Function {function_name.capitalize()} not found in contract {contract_name} ABI")
        
        # Generate parameter initialization code and validation rules
        param_inits = []
        param_names = []
        validation_rules = []
        param_types = {}

        for input_param in function_abi.get("inputs", []):
            param_name = input_param['name']
            param_type = input_param['type']
            param_names.append(param_name)
            param_types[param_name] = param_type
            param_inits.append(self._generate_param_init_code(param_name, param_type, function_name))
            validation_rules.append(self._generate_validation_rule(param_name, param_type))
        
        # Enhanced LLM prompt with more context
        prompt = self._build_llm_prompt(
            action_name, class_name, contract_name, 
            function_name, summary, param_names,
            param_types, param_inits, validation_rules
        )
        
        try:
            analyzer = ThreeStageAnalyzer(ActionInstruction)
            action_instructions = analyzer.ask_llm(prompt)
            code = action_instructions.to_dict()["content"]
            code = self._clean_generated_code(code)
            # code = ask_openai(prompt)
            code = self._clean_generated_code(code)
            
            # Validate the generated code
            self._validate_generated_code(code, function_name, param_names)
            
            with open(filepath, "w") as f:
                f.write(code)
                
            return {"file_path": filepath, "existing": False}
                
        except Exception as e:
            print(f"Error generating {action_name}: {str(e)}")
            # Fall back to template generation
            with open(filepath, "w") as f:
                f.write(self._get_fallback_template(
                    class_name, action_name, 
                    contract_name, function_name,
                    param_names, param_inits,
                    validation_rules
                ))
            return {"file_path": filepath, "existing": False}

    def _build_llm_prompt(self, action_name: str, class_name: str, contract_name: str,
                         function_name: str, summary: str, param_names: List[str],
                         param_types: Dict[str, str], param_inits: List[str],
                         validation_rules: List[str]) -> str:
        """Build comprehensive LLM prompt for action generation"""
        param_details = "\n".join(
            f"- {name}: {param_types[name]} (Sample init: {param_inits[i]})"
            for i, name in enumerate(param_names))
        
        validation_examples = "\n".join(
            f"- {rule}" for rule in validation_rules if rule.strip())
        
        return f"""
Generate a complete, production-ready TypeScript class for the '{action_name}' action that interacts with 
the '{function_name}' function in the '{contract_name}' smart contract.

CLASS REQUIREMENTS:
1. Class name: {class_name}
2. Must extend Action from "@svylabs/ilumina"
3. Must use context.prng for all random values
4. Must include comprehensive error handling
5. Must validate all parameters before execution
6. Must follow TypeScript best practices

CONTRACT FUNCTION DETAILS:
- Function: {function_name}
- Parameters:
{param_details}

ACTION SUMMARY:
{summary}

VALIDATION REQUIREMENTS:
{validation_examples}

CODE STRUCTURE:
1. Required imports (ethers, BigNumber, etc.)
2. Class with:
   - Constructor accepting Contract instance
   - execute() method that:
     * Initializes parameters
     * Validates parameters
     * Executes contract function
     * Handles transaction
     * Returns tx hash and params
   - validate() method that checks all parameter constraints
3. Proper TypeScript types for all parameters
4. Comprehensive logging using actor.log()

Generate the complete code following these requirements exactly. Include all necessary imports and 
ensure the code is properly formatted and ready for production use.
"""

    def _validate_generated_code(self, code: str, function_name: str, param_names: List[str]):
        """Validate the generated code meets requirements"""
        required_patterns = [
            r"extends Action",
            r"this\.contract\.connect\(actor\.account\.value\)",
            r"await tx\.wait\(\)",
            r"actor\.log\(",
            r"import \{.*ethers.*\} from \"ethers\"",
            r"async execute\(",
            r"async validate\(",
            rf"\.{function_name}\(",
            r"try\s*{",
            r"catch\s*\(error\)\s*{"
        ]
        
        for pattern in required_patterns:
            if not re.search(pattern, code, re.MULTILINE):
                raise ValueError(f"Generated code missing required pattern: {pattern}")
        
        # Verify all parameters are used
        for param in param_names:
            if not re.search(rf"\b{param}\b", code):
                raise ValueError(f"Parameter {param} not properly used in generated code")

    def _generate_validation_rule(self, param_name: str, param_type: str) -> str:
        """Generate validation rules for parameters based on their type"""
        if param_type.startswith("uint") or param_type.startswith("int"):
            bits = param_type[4:] if param_type.startswith("uint") else param_type[3:]
            max_val = 2 ** (int(bits) if bits else 256) - 1
            return (
                f"if (actionParams.{param_name}.isGreaterThan(new BigNumber({max_val}))) {{\n"
                f"    actor.log(`{param_name} exceeds maximum value for {param_type}`);\n"
                f"    return false;\n"
                f"}}"
            )
        if param_type == "address":
            return (
                f"if (!ethers.isAddress(actionParams.{param_name})) {{\n"
                f"    actor.log(`Invalid address format for {param_name}`);\n"
                f"    return false;\n"
                f"}}"
            )

        if "time" in param_name.lower():
            return (
                f"if (actionParams.{param_name} < Math.floor(Date.now() / 1000)) {{\n"
                f"    actor.log(`{param_name} cannot be in the past`);\n"
                f"    return false;\n"
                f"}}"
            )
        
        if param_type == "string":
            return (
                f"if (actionParams.{param_name}.length === 0) {{\n"
                f"    actor.log(`{param_name} cannot be empty`);\n"
                f"    return false;\n"
                f"}}"
            )
        
        if "strategy" in param_name.lower():
            return (
                f"if (!context.strategies.has(actionParams.{param_name})) {{\n"
                f"    actor.log(`Invalid strategy for {param_name}`);\n"
                f"    return false;\n"
                f"}}"
            )
        
        return ""

    def _get_fallback_template(self, class_name: str, action_name: str, 
                             contract_name: str, function_name: str,
                             param_names: List[str], param_inits: List[str],
                             validation_rules: List[str] = None) -> str:
        """Fallback template generator with proper validation support"""
        if validation_rules is None:
            validation_rules = []

        sanitized_class_name = self._sanitize_for_classname(action_name)
        param_return_lines = ",\n                    ".join(f"{name}: {name}" for name in param_names)
        validation_logic = "\n        ".join([
            "// Basic parameter validation",
            *[rule for rule in validation_rules if rule],
            "return true;"
        ])
        
        return (
            "import {{ Action, Actor }} from \"@svylabs/ilumina\";\n"
            "import type {{ RunContext }} from \"@svylabs/ilumina\";\n"
            "import type {{ Contract }} from \"ethers\";\n"
            "import {{ ethers }} from \"ethers\";\n"
            "import BigNumber from \"bignumber.js\";\n\n"
            "export class {} extends Action {{\n"
            "    private contract: Contract;\n\n"
            "    constructor(contract: Contract) {{\n"
            "        super(\"{}\");\n"
            "        this.contract = contract;\n"
            "    }}\n\n"
            "    async execute(context: RunContext, actor: Actor, currentSnapshot: any): Promise<any> {{\n"
            "        actor.log(\"Executing {}...\");\n"
            "        try {{\n"
            "            // Initialize parameters using context.prng\n"
            "            {}\n\n"
            "            // Validate parameters before execution\n"
            "            if (!(await this.validate(context, actor, currentSnapshot, currentSnapshot, {{\n"
            "                {}\n"
            "            }}))) {{\n"
            "                throw new Error('Parameter validation failed');\n"
            "            }}\n\n"
            "            const tx = await this.contract.connect(actor.account.value)\n"
            "                .{}({});\n"
            "            await tx.wait();\n"
            "            actor.log(`{} executed successfully. TX hash: ${{tx.hash}}`);\n"
            "            return {{\n"
            "                txHash: tx.hash,\n"
            "                params: {{\n"
            "                    {}\n"
            "                }}\n"
            "            }};\n"
            "        }} catch (error) {{\n"
            "            actor.log(`Error in {}: ${{error}}`);\n"
            "            throw error;\n"
            "        }}\n"
            "    }}\n\n"
            "    async validate(context: RunContext, actor: Actor,\n"
            "                 previousSnapshot: any, newSnapshot: any,\n"
            "                 actionParams: any): Promise<boolean> {{\n"
            "        actor.log(\"Validating {}...\");\n"
            "        {}\n"
            "    }}\n"
            "}}"
        ).format(
            class_name,
            sanitized_class_name,
            action_name,
            "\n            ".join(param_inits),
            param_return_lines,
            function_name,
            ", ".join(param_names),
            action_name,
            param_return_lines,
            action_name,
            action_name,
            validation_logic
        )