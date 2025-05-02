# actions.py
#!/usr/bin/env python3
import json
import os
import re
from pathlib import Path
from typing import Dict, List
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

    def _generate_action_file(self, action_name: str, contract_name: str, 
                            function_name: str, summary: str):
        filename = f"{self._sanitize_for_filename(action_name)}.ts"
        filepath = os.path.join(self.actions_dir, filename)
        
        if os.path.exists(filepath):
            return
            
        sanitized_class_name = self._sanitize_for_classname(action_name)
        class_name = sanitized_class_name + "Action"
        
        # Get ABI for the contract
        contract_abi = self.compiler.get_contract_abi(contract_name)
        if not contract_abi:
            raise Exception(f"ABI not found for contract: {contract_name}")
        
        # Find the function in ABI
        function_abi = next(
            (item for item in contract_abi["abi"] 
             if item["type"] == "function" and item["name"] == function_name),
            None
        )
        
        if not function_abi:
            raise Exception(f"Function {function_name} not found in contract {contract_name} ABI")
        
        # Generate parameter types for TypeScript
        input_types = ", ".join(
            f"{input['name']}: {self._solidity_to_ts_type(input['type'])}"
            for input in function_abi.get("inputs", [])
        )
        
        # Generate parameter names for the function call
        param_names = ", ".join(
            input['name'] for input in function_abi.get("inputs", [])
        )
        
        # Generate prompt with ABI-aware implementation
        prompt = f"""
        Generate a TypeScript class for action '{action_name}' with EXACTLY this structure:
        
        import {{ Action, Actor }} from "@svylabs/ilumina";
        import type {{ RunContext }} from "@svylabs/ilumina";
        import type {{ Contract }} from "ethers";

        export class {class_name} extends Action {{
            private contract: Contract;
            
            constructor(contract: Contract) {{
                super("{sanitized_class_name}");
                this.contract = contract;
            }}

            async execute(context: RunContext, actor: Actor, currentSnapshot: any): Promise<any> {{
                actor.log(`Executing {action_name}...`);
                try {{
                    // Call contract function with parameters
                    const tx = await this.contract.connect(actor.account.value)
                        .{function_name}({param_names});
                    
                    await tx.wait(); // Wait for transaction confirmation
                    actor.log(`{action_name} executed successfully. TX hash: ${{tx.hash}}`);
                    return {{ txHash: tx.hash }};
                }} catch (error) {{
                    actor.log(`Error executing {action_name}: ${{error}}`);
                    throw error;
                }}
            }}

            async validate(context: RunContext, actor: Actor, 
                         previousSnapshot: any, newSnapshot: any, 
                         actionParams: any): Promise<boolean> {{
                actor.log(`Validating {action_name}...`);
                // Add validation logic here
                return true;
            }}
        }}

        Requirements:
        1. MUST maintain this exact structure
        2. Use this.contract.connect(actor.account.value) for all contract calls
        3. Include proper parameter handling based on ABI
        4. Include proper error handling
        5. Use actor.log() for all logging
        6. validate() must return boolean
        7. Wait for transaction confirmation with await tx.wait()
        """
        
        try:
            code = ask_openai(prompt)
            code = self._clean_generated_code(code)
            
            # Additional validation to ensure proper contract call syntax
            required_patterns = [
                r"this\.contract\.connect\(actor\.account\.value\)",
                r"await tx\.wait\(\)",
                r"actor\.log\("
            ]
            
            for pattern in required_patterns:
                if not re.search(pattern, code):
                    raise ValueError(f"Generated code missing required pattern: {pattern}")
            
            with open(filepath, "w") as f:
                f.write(code)
                
        except Exception as e:
            print(f"Error generating {action_name}: {str(e)}")
            # Fallback to basic implementation
            with open(filepath, "w") as f:
                f.write(self._get_fallback_template(
                    class_name, action_name, 
                    contract_name, function_name,
                    input_types, param_names
                ))

    def _clean_generated_code(self, code: str) -> str:
        """Remove unwanted formatting and duplicates"""
        # Remove markdown code blocks
        code = code.replace("```typescript", "").replace("```", "").strip()
        # Normalize whitespace for better verification
        code = '\n'.join(line.strip() for line in code.splitlines())
        # Remove duplicate imports
        lines = code.split('\n')
        unique_lines = []
        seen_imports = set()
        
        for line in lines:
            if line.strip().startswith("import"):
                if line not in seen_imports:
                    seen_imports.add(line)
                    unique_lines.append(line)
            else:
                unique_lines.append(line)
        
        return '\n'.join(unique_lines)

    def _get_fallback_template(self, class_name: str, action_name: str, 
                             contract_name: str, function_name: str,
                             input_types: str = "", param_names: str = "") -> str:
        sanitized_class_name = self._sanitize_for_classname(action_name)
        
        return f"""import {{ Action, Actor }} from "@svylabs/ilumina";
import type {{ RunContext }} from "@svylabs/ilumina";
import type {{ Contract }} from "ethers";

export class {class_name} extends Action {{
    private contract: Contract;
    
    constructor(contract: Contract) {{
        super("{sanitized_class_name}");
        this.contract = contract;
    }}

    async execute(context: RunContext, actor: Actor, currentSnapshot: any): Promise<any> {{
        actor.log("Executing {action_name}...");
        try {{
            const tx = await this.contract.connect(actor.account.value)
                .{function_name}({param_names});
            await tx.wait();
            actor.log(`{action_name} executed successfully. TX hash: ${{tx.hash}}`);
            return {{ txHash: tx.hash }};
        }} catch (error) {{
            actor.log(`Error in {action_name}: ${{error}}`);
            throw error;
        }}
    }}

    async validate(context: RunContext, actor: Actor, 
                 previousSnapshot: any, newSnapshot: any, 
                 actionParams: any): Promise<boolean> {{
        actor.log("Validating {action_name}...");
        return true;
    }}
}}"""