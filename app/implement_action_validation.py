#!/usr/bin/env python3
import os
import json
from jinja2 import FileSystemLoader, Environment
from app.models import Action, ActionValidation
from app.context import RunContext
from app.scaffold import Scaffolder

scaffold_templates = FileSystemLoader('scaffold')
env = Environment(loader=scaffold_templates)

class ValidationActorGenerator:
    def __init__(self, context: RunContext, force=False):
        self.context = context
        self.force = force
        self.actors = self.context.actor_summary()
        self.scaffolder = Scaffolder(context)

    def generate_validation_actor(self, base_action: Action, validation: ActionValidation):
        actor_template = env.get_template("validation_actor.ts.j2")
        
        # Determine the name of this dedicated validation actor
        base_action_sanitized = self.scaffolder._sanitize_for_classname(base_action.name)
        validation_actor_name = f"Validation{base_action_sanitized}"
        file_name = self.scaffolder._sanitize_for_filename_actor(validation_actor_name)
        
        # Extract unique actions from the sequence
        unique_actions = {}
        
        for step in validation.smoke_test_sequence:
            key = (step.contract_name, step.function_name)
            if key not in unique_actions:
                original_action = self.actors.find_action(step.contract_name, step.function_name)
                if original_action:
                    unique_actions[key] = original_action
                else:
                    # If action not found precisely, create a mock from available info
                    # This is defensive, normally it should be found in actor_summary
                    pass
        
        # Ensure the base action is included even if it was omitted from the sequence explicitly
        base_key = (base_action.contract_name, base_action.function_name)
        if base_key not in unique_actions:
             unique_actions[base_key] = base_action
             
        actions_data = []
        deployed_contracts = self.context.deployed_contracts()
        deployment_instruction = self.context.deployment_instructions()
        
        for act in unique_actions.values():
            action_name = self.scaffolder._sanitize_for_classname(act.name)
            deployed_contract = self.scaffolder._get_deployed_contract(
                act.contract_name, 
                deployed_contracts, 
                deployment_instruction
            )
            actions_data.append({
                "name": action_name,
                "file_name": self.scaffolder._sanitize_for_filename(act.contract_name, act.name),
                "contract": deployed_contract,
                "probability": 1.0  # Validation uses deterministic sequences, probability defaults to 1.0
            })
            
        actor_dict = {
            "name": validation_actor_name,
            "file_name": file_name,
            "actions": actions_data
        }
        
        actor_content = actor_template.render(actor=actor_dict)
        
        out_path = os.path.join(self.context.actors_directory(), f"{file_name}.ts")
        with open(out_path, "w") as f:
            f.write(actor_content)
            
        self.context.commit(f"Generated validation actor: {validation_actor_name}")
        return out_path

if __name__ == "__main__":
    from app.context import prepare_context
    context = prepare_context({
        "run_id": "1747743579",
        "submission_id": "b2467fc4-e77a-4529-bcea-09c31cb2e8fe",
        "github_repository_url": "https://github.com/svylabs/stablebase",
        "plan": "paid"
    }, needs_parallel_workspace=False)
    
    from app.action_validation_analyzer import ActionValidationAnalyzer
    analyzer = ActionValidationAnalyzer(context)
    actors = context.actor_summary()
    if not actors or not actors.actors:
        print(f"Failed to load actors from {context.actor_summary_path()}, please ensure the workspace is fully scaffolded before running this test script!")
        import sys
        sys.exit(1)
    
    # Pick a sample action
    actor = actors.actors[0]
    action = actor.actions[6] if len(actor.actions) > 6 else actor.actions[0]
    
    # Get the validation sequence for it
    validation_sequence = analyzer.analyze(actor, action, actors)
    
    # Run the generator
    generator = ValidationActorGenerator(context)
    out_path = generator.generate_validation_actor(action, validation_sequence)
    
    print(f"Successfully generated validation actor for {action.name} at {out_path}")
