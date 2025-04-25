# actions.py
#!/usr/bin/env python3
import json
import os
import re
from pathlib import Path
from typing import Dict, List
from .context import RunContext
from .action_openai import ask_openai

class ActionGenerator:
    def __init__(self, context: RunContext):
        self.context = context
        self.actions_dir = os.path.join(context.simulation_path(), "simulation", "actions")
        os.makedirs(self.actions_dir, exist_ok=True)
        
    def generate_all_actions(self):
        """Generate action files for all actors and actions"""
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
    
    # def _sanitize_class_name(self, action_name: str) -> str:
    #     """Sanitize the action name to create a valid class name."""
    #     sanitized_name = re.sub(r'[^\w\s]', '', re.sub(r'\(.*?\)', '', action_name))  # Remove special characters and parentheses
    #     return re.sub(r'\s+', '', sanitized_name)  # Remove spaces
    
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
        
        # Strict template for the prompt
        prompt = f"""
        Generate a TypeScript class for action '{action_name}' with EXACTLY this structure:
        
        import {{ Action, Actor }} from "@svylabs/ilumina";
        import type {{ RunContext }} from "@svylabs/ilumina";

        export class {class_name} extends Action {{
            private contracts: any;
            
            constructor(contracts: any) {{
                super("{sanitized_class_name}");
                this.contracts = contracts;
            }}

            async execute(context: RunContext, actor: Actor, currentSnapshot: any): Promise<any> {{
                // Implementation for {action_name}
                // Using contract: {contract_name}
                // Calling function: {function_name}
                // Description: {summary}
            }}

            async validate(context: RunContext, actor: Actor, 
                         previousSnapshot: any, newSnapshot: any, 
                         actionParams: any): Promise<boolean> {{
                // Validation for {action_name}
            }}
        }}

        Requirements:
        1. MUST maintain this exact structure
        2. Only include the two specified imports
        3. constructor must call super("{sanitized_class_name}")
        4. execute() must use this.contracts.{contract_name}
        5. validate() must return boolean
        6. Use actor.log() for logging
        7. Include proper error handling
        8. NO additional interfaces or types
        9. NO extra imports
        10. NO markdown formatting
        """
        
        try:
            code = ask_openai(prompt)
            code = self._clean_generated_code(code)
            
            # Log the raw generated code for debugging
            print(f"Generated code for {action_name}:\n{code}")
            
            # Verify the structure using flexible checks
            required_lines = [
                f'export class {class_name} extends Action {{',
                f'super("{sanitized_class_name}");',
                'async execute(context: RunContext, actor: Actor, currentSnapshot: any): Promise<any> {',
                'async validate(context: RunContext, actor: Actor, previousSnapshot: any, newSnapshot: any, actionParams: any): Promise<boolean> {'
            ]
            
            for line in required_lines:
                if not any(line in code_line for code_line in code.splitlines()):
                    raise ValueError(f"Generated code missing required line: {line}")
                    
        except Exception as e:
            print(f"Error generating {action_name}: {str(e)}")
            code = self._get_fallback_template(class_name, action_name, contract_name, function_name)
        
        with open(filepath, "w") as f:
            f.write(code)

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
                               contract_name: str, function_name: str) -> str:
        sanitized_class_name = self._sanitize_for_classname(action_name)
        
        return f"""import {{ Action, Actor }} from "@svylabs/ilumina";
import type {{ RunContext }} from "@svylabs/ilumina";

export class {class_name} extends Action {{
    private contracts: any;
    
    constructor(contracts: any) {{
        super("{sanitized_class_name}");
        this.contracts = contracts;
    }}

    async execute(context: RunContext, actor: Actor, currentSnapshot: any): Promise<any> {{
        actor.log("Executing {action_name}...");
        try {{
            const result = await this.contracts.{contract_name}.connect(actor.account.value)
                .{function_name}();
            return {{ txHash: result.hash }};
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