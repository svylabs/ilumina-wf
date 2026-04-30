import os
import uuid
import subprocess
import traceback
import json
import shutil
from google.cloud import datastore
from app.clients import datastore_client
from app.context import prepare_context
from app.action_validation_analyzer import ActionValidationAnalyzer
from app.implement_action_validation import ValidationActorGenerator
from jinja2 import FileSystemLoader, Environment

scaffold_templates = FileSystemLoader('scaffold')
env = Environment(loader=scaffold_templates)

def render_validation_script(context, actor_classname, actor_filename, script_name):
    template = env.get_template("validate_action.ts.j2")
    content = template.render(
        actor_classname=actor_classname,
        actor_filename=actor_filename
    )
    dst = os.path.join(context.simulation_path(), "scripts", script_name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w") as f:
        f.write(content)

def create_verification_run(submission_id, actor_name, action_name):
    import datetime
    tracking_id = str(uuid.uuid4())
    key = datastore_client.key("ActionVerificationRun", tracking_id)
    entity = datastore.Entity(key=key, exclude_from_indexes=("result",))
    entity.update({
        "tracking_id": tracking_id,
        "submission_id": submission_id,
        "actor_name": actor_name,
        "action_name": action_name,
        "status": "pending",
        "result": None,
        "created_at": datetime.datetime.utcnow().isoformat()
    })
    datastore_client.put(entity)
    return tracking_id

def get_latest_verification_run(submission_id, actor_name, action_name):
    query = datastore_client.query(kind="ActionVerificationRun")
    query.add_filter("submission_id", "=", submission_id)
    query.add_filter("actor_name", "=", actor_name)
    query.add_filter("action_name", "=", action_name)
    
    runs = list(query.fetch())
    if not runs:
        return None
        
    # Sort descending by created_at (string isoformat is lexicographically sortable)
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return runs[0]

def execute_verify_action_background(tracking_id, submission_id, actor_name, action_name):
    entity_key = datastore_client.key("ActionVerificationRun", tracking_id)
    try:
        submission_key = datastore_client.key("Submission", submission_id)
        submission = datastore_client.get(submission_key)
        
        def update_status(status_msg, result=None):
            entity = datastore_client.get(entity_key)
            if not entity: return
            entity["status"] = status_msg
            if result is not None:
                entity["result"] = json.dumps(result)
            datastore_client.put(entity)
            
        update_status("preparing workspace")
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=False)
        
        update_status("validation sequence generated")
        actors = context.actor_summary()
        actor = next((a for a in actors.actors if a.name == actor_name), None)
        if not actor: raise Exception(f"Actor {actor_name} not found")
        action = next((a for a in actor.actions if a.name == action_name), None)
        if not action: raise Exception(f"Action {action_name} not found")
        
        analyzer = ActionValidationAnalyzer(context)
        update_status("Analyzing sequence")
        validation_sequence = analyzer.analyze(actor, action, actors)
        update_status("Generated validation sequence", {"sequence": validation_sequence.to_dict()})
        
        generator = ValidationActorGenerator(context)
        generator.generate_validation_actor(action, validation_sequence)
        
        actor_sanitized = generator.scaffolder._sanitize_for_filename_actor(actor_name)
        action_sanitized = generator.scaffolder._sanitize_for_filename_actor(action_name)
        file_prefix = f"validate_{actor_sanitized}_{action_sanitized}"
        script_name = f"{file_prefix}.ts"
        sequence_name = f"sequence_{file_prefix}.json"
        
        validations_dir = context.validations_directory()
        sequence_path = os.path.join(validations_dir, sequence_name)
        with open(sequence_path, "w") as f:
            json.dump(validation_sequence.to_dict(), f, indent=2)

        base_action_sanitized = generator.scaffolder._sanitize_for_classname(action.name)
        validation_actor_classname = f"Validation{base_action_sanitized}"
        validation_actor_filename = generator.scaffolder._sanitize_for_filename_actor(validation_actor_classname)
            
        update_status("creating validation script", {"sequence": validation_sequence.to_dict()})
        render_validation_script(context, validation_actor_classname, validation_actor_filename, script_name)
        
        # Github Commit (this makes the repo persistent for future runs)
        context.commit(f"Add validation script and sequence for {action_name}")
        
        sequence_relative_path = os.path.join("validations", sequence_name)
        
        update_status("executing", {
            "sequence": validation_sequence.to_dict(),
            "script": script_name
        })
        process = subprocess.Popen(
            ["/bin/bash", "scripts/run_validation.sh", tracking_id, context.simulation_path(), script_name, sequence_relative_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        stdout, stderr = process.communicate()
        
        log_path = os.path.join(context.simulation_path(), f"result_{tracking_id}.json")
        result_data = {"stdout": stdout, "stderr": stderr}
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                result_data["log"] = json.load(f)
                
        if process.returncode != 0:
            update_status("failure", {
                "sequence": validation_sequence.to_dict(),
                "execution": result_data
            })
        else:
            update_status("success", {
                "sequence": validation_sequence.to_dict(),
                "execution": result_data
            })
            
    except Exception as e:
        entity = datastore_client.get(entity_key)
        if entity:
            entity["status"] = "error"
            entity["result"] = json.dumps({"error": str(e), "traceback": traceback.format_exc()})
            datastore_client.put(entity)
