#!/usr/bin/env python3
import json
import os
from pathlib import Path
from typing import Dict, List
from pydantic import BaseModel
from .context import RunContext
from .openai import ask_openai
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
    
    def generate_all_actions(self):
        """Generate action files for all actors and actions"""
        actor_summary = self.load_actor_summary()
        
        for actor in actor_summary.get("actors", []):
            for action in actor.get("actions", []):
                self.generate_action_file(
                    action_name=action["name"],
                    contract_name=action["contract_name"],
                    function_name=action["function_name"],
                    summary=action["summary"]
                )
    
    def generate_action_file(self, action_name: str, contract_name: str, 
                             function_name: str, summary: str):
        """Generate a TypeScript action file for a specific action"""
        # Clean action name for filename
        filename = action_name.lower().replace(" ", "_") + ".ts"
        filepath = os.path.join(self.actions_dir, filename)
        
        # Ensure the actions directory exists
        if not os.path.exists(self.actions_dir):
            os.makedirs(self.actions_dir, exist_ok=True)

        # Skip if the file already exists
        if os.path.exists(filepath):
            print(f"Action file already exists: {filepath}")
            return
            
        # Generate the action template using LLM
        prompt = f"""
        Generate a TypeScript action class for a blockchain simulation with these parameters:
        - Action Name: {action_name}
        - Contract Name: {contract_name}
        - Function Name: {function_name}
        - Description: {summary}
        
        Requirements:
        1. Extend the Action class from @svylabs/ilumina
        2. Implement execute() and validate() methods
        3. Use context.prng for any random number generation
        4. Include proper type imports
        5. Add appropriate logging
        6. The class name should follow PascalCase convention (e.g., {action_name.replace(' ', '')}Action)
        
        Return ONLY the complete TypeScript code with no additional explanation or markdown.
        """
        
        try:
            # Get the generated code from LLM
            code = ask_openai(prompt, type="text", task="code_generation")
            
            # Validate the response
            if not code.strip():
                raise ValueError("Received empty code from ask_openai")

            # Save the generated file
            with open(filepath, "w") as f:
                f.write(code)
            
            print(f"Generated action file: {filepath}")
        except Exception as e:
            print(f"Error generating action file for {action_name}: {e}")
        
    def get_action_imports(self) -> List[str]:
        """Generate import statements for all action files"""
        imports = []
        for file in os.listdir(self.actions_dir):
            if file.endswith(".ts") and not file.startswith("_"):
                action_name = Path(file).stem
                class_name = "".join([word.capitalize() for word in action_name.split("_")]) + "Action"
                imports.append(f"import {{ {class_name} }} from './actions/{action_name}';")
        return imports