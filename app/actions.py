#!/usr/bin/env python3
import json
import os
import re
import random
from pathlib import Path
from typing import Dict, List, Optional
from .context import RunContext
from .action_openai import ask_openai
from .compiler import Compiler

class ActionGenerator:
    def __init__(self, context: RunContext):
        self.context = context
        self.actions_dir = os.path.join(context.simulation_path(), "simulation", "actions")
        os.makedirs(self.actions_dir, exist_ok=True)
        self.compiler = Compiler(context)
        
    def generate_all_actions(self):
        """Generate action files for all actors and actions"""
        # First compile contracts to get ABIs
        self.compiler.compile()

        with open(os.path.join(self.context.simulation_path(), "actor_summary.json"), "r") as f:
            actors = json.load(f)["actors"]
        
        for actor in actors:
            for action in actor["actions"]:
                self._generate_action_file(
                    action["name"],
                    action["contract_name"],
                    action["function_name"],
                    action["summary"]
                )

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
        """Generate a reasonable time offset in seconds"""
        return random.randint(3600, 259200)  # 1 hour to 3 days

    def _generate_param_init_code(self, param_name: str, param_type: str, function_name: str) -> str:
        """Generate initialization code for a parameter"""
        if param_name.lower().endswith("address"):
            return f"const {param_name} = actor.account.value; // Using actor's address"
        
        if "strategy" in param_name.lower():
            return f"const {param_name} = context.getStrategy('{param_name}'); // Get strategy from context"
        
        if "time" in param_name.lower():
            offset = self._generate_time_offset()
            return f"const {param_name} = Math.floor(Date.now() / 1000) + {offset}; // Current timestamp with offset"
        
        if param_type.startswith("uint") or param_type.startswith("int"):
            MAX_UINT256 = 2**256 - 1
            return f"const {param_name} = BigNumber.from(Math.floor(Math.random() * {MAX_UINT256})); // Random {param_type}"
        
        if param_type == "bool":
            return f"const {param_name} = Math.random() > 0.5; // Random boolean"
        
        if param_type == "string":
            return f"const {param_name} = `{function_name}_${{Math.random().toString(36).substring(2, 8)}}`; // Random string"
        
        if param_type.startswith("bytes"):
            size = param_type[5:] or "32"
            return f"const {param_name} = ethers.utils.hexlify(ethers.utils.randomBytes({size})); // Random bytes"
        
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
        filename = f"{self._sanitize_for_filename(action_name)}.ts"
        filepath = os.path.join(self.actions_dir, filename)
        
        if os.path.exists(filepath):
            return
            
        sanitized_class_name = self._sanitize_for_classname(action_name)
        class_name = sanitized_class_name + "Action"
        
        contract_abi = self.compiler.get_contract_abi(contract_name)
        if not contract_abi:
            raise Exception(f"ABI not found for contract: {contract_name}")
        
        function_abi = next(
            (item for item in contract_abi["abi"] 
             if item["type"] == "function" and item["name"] == function_name),
            None
        )
        
        if not function_abi:
            raise Exception(f"Function {function_name} not found in contract {contract_name} ABI")
        
        param_inits = []
        param_names = []
        for input_param in function_abi.get("inputs", []):
            param_name = input_param['name']
            param_type = input_param['type']
            param_names.append(param_name)
            param_inits.append(self._generate_param_init_code(param_name, param_type, function_name))
        
        param_init_lines = "\n                ".join(param_inits)
        param_return_lines = ",\n                            ".join(f"{name}: {name}" for name in param_names)
        
        prompt = (
            "Generate a TypeScript class for action '{}' with EXACTLY this structure:\n\n"
            "import {{ Action, Actor }} from \"@svylabs/ilumina\";\n"
            "import type {{ RunContext }} from \"@svylabs/ilumina\";\n"
            "import type {{ Contract }} from \"ethers\";\n"
            "import {{ BigNumber, ethers }} from \"ethers\";\n\n"
            "export class {} extends Action {{\n"
            "    private contract: Contract;\n\n"
            "    constructor(contract: Contract) {{\n"
            "        super(\"{}\");\n"
            "        this.contract = contract;\n"
            "    }}\n\n"
            "    async execute(context: RunContext, actor: Actor, currentSnapshot: any): Promise<any> {{\n"
            "        actor.log(`Executing {}...`);\n"
            "        try {{\n"
            "            // Initialize parameters\n"
            "            {}\n\n"
            "            const tx = await this.contract.connect(actor.account.value)\n"
            "                .{}({});\n\n"
            "            await tx.wait();\n"
            "            actor.log(`{} executed successfully. TX hash: ${{tx.hash}}`);\n"
            "            return {{\n"
            "                txHash: tx.hash,\n"
            "                params: {{\n"
            "                    {}\n"
            "                }}\n"
            "            }};\n"
            "        }} catch (error) {{\n"
            "            actor.log(`Error executing {}: ${{error}}`);\n"
            "            throw error;\n"
            "        }}\n"
            "    }}\n\n"
            "    async validate(context: RunContext, actor: Actor,\n"
            "                 previousSnapshot: any, newSnapshot: any,\n"
            "                 actionParams: any): Promise<boolean> {{\n"
            "        actor.log(`Validating {}...`);\n"
            "        return true;\n"
            "    }}\n"
            "}}\n\n"
            "Requirements:\n"
            "1. MUST maintain this exact structure\n"
            "2. Include all parameter initializations\n"
            "3. Use proper TypeScript types\n"
            "4. Include proper error handling\n"
            "5. Return both txHash and parameters used"
        ).format(
            action_name,
            class_name,
            sanitized_class_name,
            action_name,
            param_init_lines,
            function_name,
            ", ".join(param_names),
            action_name,
            param_return_lines,
            action_name,
            action_name
        )
        
        try:
            code = ask_openai(prompt)
            code = self._clean_generated_code(code)
            
            required_patterns = [
                r"this\.contract\.connect\(actor\.account\.value\)",
                r"await tx\.wait\(\)",
                r"actor\.log\(",
                r"import \{ (BigNumber|ethers) .* from \"ethers\""
            ]
            
            for pattern in required_patterns:
                if not re.search(pattern, code):
                    raise ValueError(f"Generated code missing required pattern: {pattern}")
            
            with open(filepath, "w") as f:
                f.write(code)
                
        except Exception as e:
            print(f"Error generating {action_name}: {str(e)}")
            with open(filepath, "w") as f:
                f.write(self._get_fallback_template(
                    class_name, action_name, 
                    contract_name, function_name,
                    param_names, param_inits
                ))

    def _get_fallback_template(self, class_name: str, action_name: str, 
                             contract_name: str, function_name: str,
                             param_names: List[str], param_inits: List[str]) -> str:
        sanitized_class_name = self._sanitize_for_classname(action_name)
        param_return_lines = ",\n                    ".join(f"{name}: {name}" for name in param_names)
        
        return (
            "import {{ Action, Actor }} from \"@svylabs/ilumina\";\n"
            "import type {{ RunContext }} from \"@svylabs/ilumina\";\n"
            "import type {{ Contract }} from \"ethers\";\n"
            "import {{ BigNumber, ethers }} from \"ethers\";\n\n"
            "export class {} extends Action {{\n"
            "    private contract: Contract;\n\n"
            "    constructor(contract: Contract) {{\n"
            "        super(\"{}\");\n"
            "        this.contract = contract;\n"
            "    }}\n\n"
            "    async execute(context: RunContext, actor: Actor, currentSnapshot: any): Promise<any> {{\n"
            "        actor.log(\"Executing {}...\");\n"
            "        try {{\n"
            "            // Initialize parameters\n"
            "            {}\n\n"
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
            "        return true;\n"
            "    }}\n"
            "}}"
        ).format(
            class_name,
            sanitized_class_name,
            action_name,
            "\n            ".join(param_inits),
            function_name,
            ", ".join(param_names),
            action_name,
            param_return_lines,
            action_name,
            action_name
        )