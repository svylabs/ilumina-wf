import os
import tempfile
import subprocess
import json
import uuid
from google.cloud import datastore
from datetime import datetime

def run_action_validation_async(sequence_input: dict, context=None, task_id=None):
    """
    Run validation asynchronously and store results in Datastore
    """
    try:
        # Initialize Datastore client
        datastore_client = datastore.Client()
        
        # Create/update task entity
        task_key = datastore_client.key("ValidationTask", task_id or str(uuid.uuid4()))
        task = datastore.Entity(key=task_key)
        task.update({
            "status": "running",
            "started_at": datetime.utcnow(),
            "sequence": sequence_input,
            "submission_id": context.submission_id if context else None
        })
        datastore_client.put(task)
        
        # Run validation in background
        result = run_action_validation(sequence_input, context)
        
        # Update task with results (store large fields as unindexed)
        task.update({
            "status": result["status"],
            "completed_at": datetime.utcnow(),
            "result": {k: v for k, v in result.items() if k not in ["stdout", "stderr", "log"]},
            "log_path": result.get("log_path")
        })
        if "stdout" in result:
            task["stdout"] = result["stdout"]
            task.exclude_from_indexes.add("stdout")
        if "stderr" in result:
            task["stderr"] = result["stderr"]
            task.exclude_from_indexes.add("stderr")
        if "log" in result:
            task["log"] = result["log"]
            task.exclude_from_indexes.add("log")
        datastore_client.put(task)
        
        # Return the string task id (for both string and int keys)
        return task.key.name or task.id
        
    except Exception as e:
        if 'task' in locals():
            task.update({
                "status": "error",
                "error": str(e)
            })
            datastore_client.put(task)
        raise

def run_action_validation(sequence_input: dict, context=None) -> dict:
    """Synchronous validation logic (now called by async wrapper)"""
    if context is not None and (sequence_input is None or sequence_input == {}):
        sequence = get_latest_validation_sequence(context)
    elif isinstance(sequence_input, dict) and 'sequence' in sequence_input:
        sequence = sequence_input['sequence']
    else:
        sequence = sequence_input

    script_path = context.validate_action_script_path()
    log_path = context.validate_action_log_path()
    
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Validation script not found at {script_path}")

    with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as tmpfile:
        json.dump(sequence, tmpfile)
        tmpfile_path = tmpfile.name

    command = [
        "npx", "ts-node", "--skip-project", script_path, tmpfile_path
    ]

    try:
        result = subprocess.run(
            command,
            cwd=context.simulation_path(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )

        log_content = None
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                log_content = f.read()
                
        os.unlink(tmpfile_path)

        return {
            "status": "success" if result.returncode == 0 else "error",
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "log": log_content,
            "log_path": log_path
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

def generate_validation_sequence(context, actor_name, action_name, contract_name, actor_index=0, params=None, out_path=None):
    """
    Generate a validation sequence JSON for a given action and store it.
    """
    # Load actor summary
    actors = context.actor_summary()
    actor = next((a for a in actors.actors if a.name == actor_name), None)
    if not actor:
        raise ValueError(f"Actor '{actor_name}' not found in actor_summary.json")
    action = next((a for a in actor.actions if a.name == action_name), None)
    if not action:
        raise ValueError(f"Action '{action_name}' not found for actor '{actor_name}'")

    # Build the sequence step
    step = {
        "action_name": getattr(action, "class_name", f"{action_name}Action"),
        "actor_index": actor_index,
        "contract_name": contract_name,
        "params": params or {}
    }
    sequence = {
        "description": f"Validation sequence for {actor_name}.{action_name} on {contract_name}",
        "sequence": [step]
    }

    # Store the sequence
    if not out_path:
        out_path = os.path.join(context.simulation_path(), "validation_sequence.json")
    with open(out_path, "w") as f:
        json.dump(sequence, f, indent=2)
    # Commit the new validation sequence to the simulation repo
    try:
        context.commit(f"Add validation sequence for {actor_name}.{action_name} on {contract_name}")
    except Exception as e:
        print(f"[generate_validation_sequence] Commit failed: {e}")
    return out_path

def get_latest_validation_sequence(context):
    """
    Loads the latest validation sequence from the default path for the given context.
    """
    path = os.path.join(context.simulation_path(), "validation_sequence.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No validation sequence found at {path}")
    with open(path, "r") as f:
        return json.load(f)