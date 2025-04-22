# actions.py
#!/usr/bin/env python3
import json
import os
from pathlib import Path
from typing import Dict, List
from pydantic import BaseModel
from .context import RunContext
from .action_openai import ask_openai
from .models import Project

class ActionTemplate(BaseModel):
    name: str
    contract_name: str
    function_name: str
    execute_template: str
    validate_template: str

class ActionGenerator:
    def __init__(self, context: RunContext):
        self.context = context
        self.actions_dir = os.path.join(context.simulation_path(), "simulation", "actions")
        os.makedirs(self.actions_dir, exist_ok=True)
        
    def load_actor_summary(self) -> Dict:
        with open(os.path.join(self.context.simulation_path(), "actor_summary.json"), "r") as f:
            return json.load(f)
    
    def generate_all_actors(self):
        """Generate actor files with execute and validate methods"""
        actor_summary = self.load_actor_summary()
        
        for actor in actor_summary.get("actors", []):
            self.generate_actor_file(actor_name=actor["name"])
    
    def generate_actor_file(self, actor_name: str):
        """Generate a TypeScript file for an actor with execute and validate methods"""
        # Clean actor name for filename
        filename = actor_name.lower().replace(" ", "_") + ".ts"
        filepath = os.path.join(self.actions_dir, filename)
        
        # Skip if the file already exists
        if os.path.exists(filepath):
            print(f"Actor file already exists: {filepath}")
            return
        
        # Generate the execute and validate methods using LLM
        prompt = f"""
        Generate JUST the execute() and validate() methods for an actor:
        - Actor Name: {actor_name}
        
        Requirements:
        1. Only implement the execute() and validate() methods
        2. Use context.prng for any random number generation
        3. Include appropriate logging using actor.log()
        4. Handle potential errors
        5. Use proper TypeScript types
        6. The methods should be specific to {actor_name}
        
        Return ONLY the method implementations with no additional explanation or markdown.
        """
        
        try:
            methods_code = ask_openai(prompt, response_type="text")
            
            if not methods_code or not isinstance(methods_code, str) or not methods_code.strip():
                raise ValueError("Received empty or invalid code from ask_openai")

            # Create the actor file content
            content = f"""import {{ Action, Actor }} from "@svylabs/ilumina";
import type {{ RunContext }} from "@svylabs/ilumina";

export class {actor_name.replace(" ", "")} extends Action {{
    private contracts: any;

    constructor(contracts: any) {{
        super("{actor_name}");
        this.contracts = contracts;
    }}

    {methods_code}
}}
"""
        except Exception as e:
            print(f"Error generating methods for {actor_name}: {str(e)}")
            # Fallback template
            content = f"""import {{ Action, Actor }} from "@svylabs/ilumina";
import type {{ RunContext }} from "@svylabs/ilumina";

export class {actor_name.replace(" ", "")} extends Action {{
    private contracts: any;

    constructor(contracts: any) {{
        super("{actor_name}");
        this.contracts = contracts;
    }}

    async execute(context: RunContext, actor: Actor, currentSnapshot: any): Promise<any> {{
        actor.log("{actor_name} executing...");
        // Add execution logic here
        return {{}};
    }}

    async validate(context: RunContext, actor: Actor, 
                 previousSnapshot: any, newSnapshot: any, 
                 actionParams: any): Promise<boolean> {{
        actor.log("{actor_name} validating...");
        // Add validation logic here
        return true;
    }}
}}
"""

        # Save the generated file
        with open(filepath, "w") as f:
            f.write(content)
        
        print(f"Successfully generated actor file: {filepath}")
        
    def get_action_imports(self) -> List[str]:
        """Generate import statements for all actor files"""
        imports = []
        for file in os.listdir(self.actions_dir):
            if file.endswith(".ts") and not file.startswith("_"):
                actor_name = Path(file).stem
                imports.append(f"import * as {actor_name} from './actions/{actor_name}';")
        return imports