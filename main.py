from flask import Flask, request, jsonify
import requests
import os
import re
from dotenv import load_dotenv
load_dotenv(".env")
from google.cloud import datastore, tasks_v2
from functools import wraps
import json
import datetime
import logging
import sys
from app.analyse import Analyzer
from app.scaffold import Scaffolder
from app.action_generator import ActionGenerator
from app.context import prepare_context, prepare_context_lazy
from app.storage import GCSStorage, storage_blueprint, upload_to_gcs
from app.github import GitHubAPI
from app.summarizer import ProjectSummarizer
from app.models import Project
from app.deployment import DeploymentAnalyzer
from app.deployer import ContractDeployer
from app.actor import ActorAnalyzer
from app.git_utils import GitUtils
import shutil
from app.clients import datastore_client, tasks_client, storage_client
# from app.submission import store_analysis_metadata, update_analysis_status
from app.tools import authenticate
import uuid
import traceback
from google.protobuf import timestamp_pb2
from app.submission import UserPromptManager
from app.hardhat_config import parse_and_modify_hardhat_config, hardhat_network
import subprocess
from app.simulation_runner import SimulationRunner, SimulationRun
from app.snapshot_datastructure_analyzer import SnapshotDataStructureAnalyzer
from app.snapshot_code_generator import SnapshotCodeGenerator
from app.action_analyzer import ActionAnalyzer
from app.compiler import Compiler
from app.submission import (
    store_analysis_metadata, 
    update_analysis_status,
    update_action_analysis_status,
    get_action_analyses,
    update_snapshot_analysis_status,
    UserPromptManager
)

# Ensure logs are written to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# Debug: Log all environment variables
#for key, value in os.environ.items():
#    print(f"ENV {key}: {value}")

# Initialize services
gcs = GCSStorage()
github_api = GitHubAPI()
user_prompt_manager = UserPromptManager(datastore_client)

PROJECT_ID = os.getenv("GCS_PROJECT_ID", "ilumina-451416")
QUEUE_ID = os.getenv("TASK_QUEUE_ID", "analysis-tasks")
LOCATION = os.getenv("TASK_LOCATION", "us-central1")
TASK_HANDLER_URL = "https://ilumina-wf-tt2cgoxmbq-uc.a.run.app/api"

SECRET_PASSWORD = os.getenv("API_SECRET", "my_secure_password")

parent = tasks_client.queue_path(PROJECT_ID, LOCATION, QUEUE_ID)

from functools import wraps
from flask import request, jsonify
from google.cloud import datastore

# Annotation to inject submission from Datastore
def inject_analysis_params(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        data = request.get_json()
        submission_id = data.get("submission_id")
        if not submission_id:
            return jsonify({"error": "Missing submission_id"}), 400

        key = datastore_client.key("Submission", submission_id)
        submission = datastore_client.get(key)

        request_context = data.get("request_context")
        if request_context == None:
            request_context = "bg"

        user_prompt = data.get("user_prompt")

        if not submission:
            return jsonify({"error": "Submission not found"}), 404

        # Pass the submission, request_context, and user_prompt to the wrapped function
        return f(submission, request_context, user_prompt, *args, **kwargs)

    return decorated_function

def create_split_and_monitor_task(submission_id, simulation_batch_id, begin_delay=5):
    """Create a task to split and monitor simulation results"""
    url = TASK_HANDLER_URL + "/submission/" + submission_id + "/simulations/batch/split"
    scheduled_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=begin_delay)
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(scheduled_time)
    task = {
        "http_request": {
            "http_method": "POST",
            "url": url,
            "headers": {"Content-Type": "application/json", "Authorization": f"Bearer {SECRET_PASSWORD}"},
            "body": json.dumps({"batch_id": simulation_batch_id}).encode(),
        },
        "schedule_time": timestamp
    }
    return tasks_client.create_task(request={"parent": parent, "task": task}).name

def create_run_simulation_task(submission_id, data):
    num_simulations = data.get("num_simulations", 1) 
    url = TASK_HANDLER_URL + "/submission/" + submission_id + "/simulations/new"
    if num_simulations > 1:
        url = TASK_HANDLER_URL + "/submission/" + submission_id + "/simulations/batch/new"
    print(url, data)
    task = {
        "http_request": {
            "http_method": "POST",
            "url": url,
            "headers": {"Content-Type": "application/json", "Authorization": f"Bearer {SECRET_PASSWORD}"},
            "body": json.dumps(data).encode(),
        }
    }
    return tasks_client.create_task(request={"parent": parent, "task": task}).name

def create_task(data, forward_params=None):
    api_suffix = "/analyze"
    if forward_params:
        for key, value in forward_params.items():
            data[key] = value
    if "step" in data and data["step"] != "begin_analysis":
        api_suffix = "/" + data["step"]
    """Create a Cloud Task for async processing"""
    scheduled_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=10)
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(scheduled_time)
    task = {
        "http_request": {
            "http_method": "POST",
            "url": TASK_HANDLER_URL + api_suffix,
            "headers": {"Content-Type": "application/json", "Authorization": f"Bearer {SECRET_PASSWORD}"},
            "body": json.dumps(data).encode(),
        },
        "schedule_time": timestamp,
    }
    return tasks_client.create_task(request={"parent": parent, "task": task}).name

@app.route('/api/submission/<submission_id>', methods=['GET'])
@authenticate
def get_submission(submission_id):
    """Fetch submission from Datastore"""
    key = datastore_client.key("Submission", submission_id)
    submission = datastore_client.get(key)
    if not submission:
        return jsonify({"error": "Submission not found"}), 404

    message = ""
    if submission.get("status") == "error":
        message = submission.get("message", "Unknown error")

    # Fetch latest prompts for each step
    steps = ["analyze_project", "analyze_actors", "analyze_deployment"]
    latest_prompts = {}
    for step in steps:
        latest_prompt = user_prompt_manager.query_latest_prompt(submission_id, step)
        if latest_prompt:
            latest_prompts[step] = latest_prompt.get("user_prompt")
    step_metadata = {}
    for step in submission.get("completed_steps", []):
        step_metadata[step["step"]] = submission.get(step["step"])
    return jsonify({
        "submission_id": submission["submission_id"],
        "github_repository_url": submission["github_repository_url"],
        "run_id": submission["run_id"],
        "created_at": submission["created_at"],
        "updated_at": submission["updated_at"],
        "step": submission.get("step"),
        "status": submission.get("status"),
        "completed_steps": submission.get("completed_steps", []),
        "message": message,
        "latest_prompts": latest_prompts,
        "step_metadata": step_metadata
    }), 200

@app.route('/api/begin_analysis', methods=['POST'])
@authenticate
def begin_analysis():
    """Start a new analysis task"""
    data = request.get_json()

    if not data or "github_repository_url" not in data or "submission_id" not in data:
        return jsonify({"error": "Invalid data format"}), 400

    # Check if the repository URL is accessible
    repo_url = data["github_repository_url"]
    try:
        response = requests.get(repo_url)
        if response.status_code != 200:
            return jsonify({"error": "Repository URL is not accessible"}), 400
    except Exception as e:
        return jsonify({"error": "Failed to access repository URL"}), 400

    data["run_id"] = data.get("run_id", str(int(datetime.datetime.now().timestamp())))
    data["step"] = "begin_analysis"
    data["status"] = "success"

    store_analysis_metadata(data)
    task_name = create_task(data)
    # Update the submission with the task name

    return jsonify({
        "message": "Analysis started",
        "task_name": task_name,
        "submission_id": data["submission_id"],
        "run_id": data["run_id"]
    }), 200

# Modify the APIs to use prepare_context for creating RunContext
@app.route('/api/analyze', methods=['POST'])
@authenticate
def analyze():
    """Determine the next step and enqueue it (full workflow orchestration)."""
    try:
        data = request.get_json()
        submission_id = data.get("submission_id")
        step_from_request = data.get("step")

        forward_params = {}
        if "request_context" in data:
            forward_params["request_context"] = data["request_context"]
        if "user_prompt" in data:
            forward_params["user_prompt"] = data["user_prompt"]

        if not submission_id:
            return jsonify({"error": "Missing submission_id"}), 400

        # Get the current context using prepare_context
        submission = datastore_client.get(datastore_client.key("Submission", submission_id))

        if not submission:
            return jsonify({"error": "Submission not found"}), 404

        # Check the status and step
        step = submission.get("step")
        status = submission.get("status")
        print(f"{submission}")

        next_step = step
        if step_from_request != None and step_from_request != "begin_analysis":
            next_step = step_from_request
        else:
            if step == None or step == "begin_analysis":
                next_step = "analyze_project"
            elif step == "analyze_project":
                if status is not None and status == "success":
                    next_step = "analyze_actors"
            elif step == "analyze_actors":
                if status is not None and status == "success":
                    next_step = "analyze_deployment"
            elif step == "analyze_deployment":
                if status is not None and status == "success":
                    next_step = "implement_deployment_script"
            elif step == "implement_deployment_script":
                if status is not None and status == "success":
                    next_step = "verify_deployment_script"
            elif step == "verify_deployment_script":
                if status is not None and status == "error":
                    next_step = "debug_deploy_script"
                elif status is not None and status == "success":
                    next_step = "scaffold"
            elif step == "debug_deployment_script":
                if status is not None and status != "success":
                    next_step = "verify_deployment_script"
            elif step == "scaffold":
                if status is not None and status == "success":
                    next_step = "analyze_all_actions"
            elif step == "analyze_all_actions":
                if status is not None and status == "success":
                    next_step = "analyze_all_snapshots"
            elif step == "analyze_all_snapshots":
                if status is not None and status == "success":
                    next_step = "implement_snapshots"
            elif step == "implement_snapshots":     
                if status is not None and status == "success":
                    next_step = "implement_all_actions"
            elif step == "implement_all_actions":
                if status is not None and status == "success":
                    next_step = ""
        
        if next_step == "analyze_project":
            create_task({"submission_id": submission_id, "step": "analyze_project"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: analyze_project"}), 200
        elif next_step == "analyze_actors":
            create_task({"submission_id": submission_id, "step": "analyze_actors"}, forward_params=forward_params)
            # Update the submission with the task name
            return jsonify({"message": "Enqueued step: analyze_actors"}), 200
        elif next_step == "analyze_deployment":
            create_task({"submission_id": submission_id, "step": "analyze_deployment"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: analyze_deployment"}), 200
        elif next_step == "implement_deployment_script":
            create_task({"submission_id": submission_id, "step": "implement_deployment_script"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: implement_deployment_script"}), 200
        elif next_step == "verify_deployment_script":
            create_task({"submission_id": submission_id, "step": "verify_deployment_script"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: verify_deployment_script"}), 200
        elif next_step == "debug_deploy_script":
            create_task({"submission_id": submission_id, "step": "debug_deploy_script"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: debug_deploy_script"}), 200
        elif next_step == "scaffold":
            create_task({"submission_id": submission_id, "step": "scaffold"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: scaffold"}), 200
        elif next_step == "analyze_all_actions":
            create_task({"submission_id": submission_id, "step": "analyze_all_actions"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: analyze_all_actions"}), 200
        elif next_step == "analyze_all_snapshots":
            create_task({"submission_id": submission_id, "step": "analyze_all_snapshots"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: analyze_all_snapshots"}), 200
        elif next_step == "implement_snapshots":
            # This is handled per contract after analyze_snapshot
            create_task({"submission_id": submission_id, "step": "implement_snapshots"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: implement_snapshots"}), 200
        elif next_step == "implement_all_actions":
            create_task({"submission_id": submission_id, "step": "implement_all_actions"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: implement_all_actions"}), 200
        elif next_step == "implement_action":
            # This is handled per action after implement_all_actions
            create_task({"submission_id": submission_id, "step": "implement_action"}, forward_params=forward_params)
            return jsonify({"message": "Enqueued step: implement_action"}), 200
        elif next_step == "run_simulation":
            description = data.get("description")
            branch = data.get("branch")
            num_simulations = data.get("num_simulations", 1)
            actor_config = data.get("actor_config")
            create_run_simulation_task(submission_id, {
                "description": description,
                "branch": branch,
                "num_simulations": num_simulations,
                "actor_config": actor_config
            })
            return jsonify({"message": "Created a task to run simulation."}), 200
        else:
            return jsonify({"message": "All steps are completed"}), 200

    except Exception as e:
        app.logger.error("Error in analyze endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/analyze_project', methods=['POST'])
@authenticate
@inject_analysis_params
def analyze_project(submission, request_context, user_prompt):
    """Perform the project analysis step"""
    try:
        # Update status to in_progress
        update_analysis_status(submission["submission_id"], "analyze_project", "in_progress", user_prompt=user_prompt)

        # Store user prompt if available
        if (user_prompt):
            user_prompt_manager.store_latest_prompt(submission["submission_id"], "analyze_project", user_prompt)
            user_prompt_manager.store_prompt_history(submission["submission_id"], "analyze_project", user_prompt)

        # Get the current context using prepare_context
        context = prepare_context(submission, needs_parallel_workspace=False)

        # Perform the project analysis
        analyzer = Analyzer(context)
        project_summary = analyzer.summarize(user_prompt=user_prompt)
        
        version, path = context.new_gcs_summary_path()

        # Upload actors summary to Google Cloud Storage
        upload_to_gcs(path, context.summary_path())
        
        if request_context == "bg":
            # Update the task queue
            update_analysis_status(submission["submission_id"], "analyze_project", "success", metadata={"summary_version": version})
            create_task({"submission_id": submission["submission_id"]})
        else:
            step = "None"
            if "step" in submission:
                step = submission["step"]
            update_analysis_status(submission["submission_id"], step, "success", metadata={"summary_version": version})
            return jsonify({"summary": project_summary.to_dict()}), 200

        return jsonify({"message": "Project analysis completed"}), 200

    except Exception as e:
        # Update status to error
        update_analysis_status(submission["submission_id"], "analyze_project", "error", metadata={"message": str(e)})
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze_actors', methods=['POST'])
@authenticate
@inject_analysis_params
def analyze_actors(submission, request_context, user_prompt):
    """Perform the actor analysis step"""
    try:
        # Update status to in_progress
        update_analysis_status(submission["submission_id"], "analyze_actors", "in_progress")

        # Store user prompt if available
        if user_prompt:
            user_prompt_manager.store_latest_prompt(submission["submission_id"], "analyze_actors", user_prompt)
            user_prompt_manager.store_prompt_history(submission["submission_id"], "analyze_actors", user_prompt)

        # Get the current context using prepare_context
        context = prepare_context(submission, needs_parallel_workspace=False)

        # Perform the actor analysis
        analyzer = Analyzer(context)
        actors = analyzer.identify_actors(user_prompt=user_prompt)

        version, path = context.new_gcs_actor_summary_path()

        # Upload actors summary to Google Cloud Storage
        upload_to_gcs(path, context.actor_summary_path())

        if request_context == "bg": 
            # Update the task queue
            update_analysis_status(submission["submission_id"], "analyze_actors", "success", metadata={"actor_version": version})
            create_task({"submission_id": submission["submission_id"]})
        else:
            step = "None"
            if "step" in submission:
                step = submission["step"]
            update_analysis_status(submission["submission_id"], step, "success", metadata={"actor_version": version})
            return jsonify({"actors": actors.to_dict()}), 200
        return jsonify({"message": "Actor analysis completed"}), 200

    except Exception as e:
        # Update status to error
        update_analysis_status(submission["submission_id"], "analyze_actors", "error", metadata={"message": str(e)})
        return jsonify({"error": str(e)}), 500

@app.route('/api/scaffold', methods=['POST'])
@authenticate
@inject_analysis_params
def scaffold(submission, request_context, user_prompt):
    """Generate action files for identified actors"""
    try:
        request_data = request.get_json()
        # Get the current context using prepare_context
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=False)
        update_analysis_status(submission["submission_id"], "scaffold", "in_progress")

        # Initialize AllActionGenerator
        scaffolder = Scaffolder(context, force=request_data.get("force", False))

        # Generate all actions
        scaffolder.scaffold()

        update_analysis_status(submission["submission_id"], "scaffold", "success")

        # WORKFLOW: After scaffold, enqueue analyze_all_actions
        if request_context == "bg":
            create_task({
                "submission_id": submission["submission_id"],
                "step": "analyze"
            })
        return jsonify({"message": "Scaffold completed, analyze_all_actions enqueued"}), 200

    except Exception as e:
        update_analysis_status(submission["submission_id"], "scaffold", "error", metadata={"message": str(e)}, step_metadata={
            "log": traceback.format_exc()
        })
        return jsonify({"error": str(e)}), 200

@app.route('/api/implement_action', methods=['POST'])
@authenticate
@inject_analysis_params
def implement_action(submission, request_context, user_prompt):
    """Generate a single action file for a specific actor and action (with parallel workspace)."""
    try:
        data = request.get_json()
        contract_name = data.get('contract_name')
        function_name = data.get('function_name')
        parallel_workspace_id = data.get("parallel_workspace_id") or str(uuid.uuid4())
        if not contract_name or not function_name:
            return jsonify({"error": "Both actor_name and action_name are required"}), 400
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=True, parallel_workspace_id=parallel_workspace_id)
        update_action_analysis_status(
            submission["submission_id"],
            contract_name,
            function_name,
            "implement",
            "in_progress"
        )
        actors = context.actor_summary()
        action = actors.find_action(contract_name, function_name)
        if not action:
            return jsonify({"error": f"Action {function_name} for contract {contract_name} not found"}), 404
        action_generator = ActionGenerator(action, context)
        action_generator.generate_action()
        update_action_analysis_status(
            submission["submission_id"],
            contract_name,
            function_name,
            "implement",
            "success"
        )
        if request_context == "bg":
            # After success, enqueue implement_all_actions for this contract
            create_task({
                "submission_id": submission["submission_id"],
                "step": "check_contract_actions_implemented"
            })
        return jsonify({
            "message": f"Action '{action.name}' for contract: {action.contract_name} - {action.function_name} generated successfully"
        }), 200
    except Exception as e:
        update_action_analysis_status(
            submission["submission_id"],
            contract_name,
            function_name,
            "implement",
            "error"
        )
        return jsonify({"error": str(e)}), 500
    
    
@app.route('/api/analyze_snapshot', methods=['POST'])
@authenticate
@inject_analysis_params
def analyze_snapshot(submission, request_context, user_prompt):
    """Analyze/generate snapshot data structure for a single contract (with parallel workspace)."""
    try:
        data = request.get_json()
        contract_name = data.get("contract_name")
        parallel_workspace_id = data.get("parallel_workspace_id") or str(uuid.uuid4())
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=True, parallel_workspace_id=parallel_workspace_id)
        update_snapshot_analysis_status(
            submission["submission_id"],
            contract_name,
            "analyze",
            "in_progress"
        )
        analyzer = SnapshotDataStructureAnalyzer(context)
        analyzer.analyze(contract_name)
        # After success, enqueue implement_snapshot for this contract
        if request_context == "bg":
            create_task({
                "submission_id": submission["submission_id"],
                "step": "check_contract_snapshots_analyzed"
            })
        update_snapshot_analysis_status(
            submission["submission_id"],
            contract_name,
            "analyze",
            "success"
        )
        return jsonify({
            "message": f"Snapshot data structure generated for contract {contract_name}",
            "contract_name": contract_name
        }), 200
    except Exception as e:
        app.logger.error("Error in analyze_snapshot", exc_info=e)
        update_snapshot_analysis_status(
            submission["submission_id"],
            contract_name,
            "analyze",
            "error"
        )
        return jsonify({"error": str(e)}), 500

@app.route('/api/implement_snapshots', methods=['POST'])
@authenticate
@inject_analysis_params
def implement_snapshots(submission, request_context, user_prompt):
    """Generate snapshot code for all or specific contracts (with parallel workspace)."""
    try:
        data = request.get_json()
        update_analysis_status(
            submission["submission_id"],
            "implement_snapshots",
            "in_progress"
        )
        parallel_workspace_id = data.get("parallel_workspace_id") or str(uuid.uuid4())
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=True, parallel_workspace_id=parallel_workspace_id)
        generator = SnapshotCodeGenerator(context)
        generator.generate()
        query = datastore_client.query(kind="SubmissionSnapshotAnalysis")
        query.add_filter("submission_id", "=", submission["submission_id"])
        snapshots = list(query.fetch())
        for snapshot in snapshots:
            contract_name = snapshot["contract_name"]
            update_snapshot_analysis_status(
                submission["submission_id"],
                contract_name,
                "implement",
                "success"
            )
        update_analysis_status(
            submission["submission_id"],
            "implement_snapshots",
            "success"
        )
        if request_context == "bg":
            # After success, enqueue implement_all_actions for this contract
            create_task({
                "submission_id": submission["submission_id"],
                "step": "analyze"
            })
        return jsonify({"message": "Implemented snapshots"}), 200
    except Exception as e:
        app.logger.error("Error in implement_snapshot", exc_info=e)
        update_analysis_status(
            submission["submission_id"],
            "implement_snapshots",
            "error",
            metadata={"message": str(e)}
        )
        return jsonify({"error": str(e)}), 500

@app.route('/api/implement_all_actions', methods=['POST'])
@authenticate
@inject_analysis_params
def implement_all_actions(submission, request_context, user_prompt):
    """Enqueue implement_action for all actions (parallel workspace)."""
    try:
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=False)
        actors = context.actor_summary()
        update_analysis_status(
            submission["submission_id"],
            "implement_all_actions",
            "in_progress"
        )
        count = 0
        for actor in actors.actors:
            for action in actor.actions:
                parallel_workspace_id = str(uuid.uuid4())
                update_action_analysis_status(
                    submission["submission_id"],
                    action.contract_name,
                    action.function_name,
                    "implement",
                    "in_progress"
                )
                create_task({
                    "submission_id": submission["submission_id"],
                    "actor_name": getattr(actor, "name", None),
                    "action_name": getattr(action, "function_name", None),
                    "step": "implement_action",
                    "parallel_workspace": True,
                    "parallel_workspace_id": parallel_workspace_id
                })
                count += 1
        return jsonify({"message": f"Created tasks for implementing {count} actions", "status": "success"}), 200
    except Exception as e:
        app.logger.error("Error in implement_all_actions endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze_deployment', methods=['POST'])
@authenticate
@inject_analysis_params
def analyze_deployment(submission, request_context, user_prompt):
    """Perform the deployment analysis step"""
    try:
        # Update status to in_progress
        update_analysis_status(submission["submission_id"], "analyze_deployment", "in_progress")

        # Store user prompt if available
        if user_prompt:
            user_prompt_manager.store_latest_prompt(submission["submission_id"], "analyze_deployment", user_prompt)
            user_prompt_manager.store_prompt_history(submission["submission_id"], "analyze_deployment", user_prompt)

        # Get the current context using prepare_context
        context = prepare_context(submission, needs_parallel_workspace=False)

        # Perform the deployment analysis
        analyzer = Analyzer(context)
        deployment_instructions = analyzer.generate_deployment_instructions(user_prompt=user_prompt)
        version, path = context.new_gcs_deployment_instructions_path()

        # Upload deployment instructions to Google Cloud Storage
        upload_to_gcs(path, context.deployment_instructions_path())
        if request_context == "bg":
            # Update the task queue
            update_analysis_status(submission["submission_id"], "analyze_deployment", "success", metadata={"deployment_instruction_version": version})
            create_task({"submission_id": submission["submission_id"]})
        else:
            step = "None"
            if "step" in submission:
                step = submission["step"]
            update_analysis_status(submission["submission_id"], step, "success", metadata={"deployment_instruction_version": version})
            return jsonify({"deployment_instructions": deployment_instructions.to_dict()}), 200

        return jsonify({"message": "Deployment analysis completed"}), 200

    except Exception as e:
        # Update status to error
        update_analysis_status(submission["submission_id"], "analyze_deployment", "error", metadata={"message": str(e)})
        return jsonify({"error": str(e)}), 500

@app.route('/api/implement_deployment_script', methods=['POST'])
@authenticate
@inject_analysis_params
def implement_deployment_script(submission, request_context, user_prompt):
    try:
        update_analysis_status(
            submission["submission_id"],
            "implement_deployment_script",
            "in_progress"
        )
        """Execute and verify the deployment script"""
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=False)
        # Initialize DeploymentAnalyzer
        deployer = DeploymentAnalyzer(context)
        
        # 3. Generate deploy.ts
        deployer.implement_deployment_script_v2()
        update_analysis_status(
            submission["submission_id"],
            "implement_deployment_script",
            "success"
        )
        if (request_context == "bg"):
            create_task({"submission_id": submission["submission_id"]})
        return jsonify({
            "message": "Deployment script implemented successfully",
            "log": "Deployment script implemented successfully"
        }), 200
    except Exception as e:
        app.logger.error("Error in implement_deployment_script endpoint", exc_info=e)
        update_analysis_status(
            submission["submission_id"],
            "implement_deployment_script",
            "error",
            metadata={"message": str(e)}
        )
        return jsonify({"error": str(e)}), 200
    
def _extract_error_details(stderr, stdout):
    """Extract meaningful error details from deployment output"""
    error_lines = []
    for line in (stderr + stdout).split('\n'):
        if 'error' in line.lower() or 'fail' in line.lower():
            error_lines.append(line.strip())
    return '\n'.join(error_lines[-5:]) if error_lines else "Unknown deployment error"


@app.route('/api/submission_logs/<submission_id>', methods=['GET'])
@authenticate
def get_submission_logs(submission_id):
    """Fetch all logs for a given submission ID, ordered by updated time."""
    query = datastore_client.query(kind="SubmissionLog")
    query.add_filter("submission_id", "=", submission_id)
    query.order = ["-updated_at"]

    logs = list(query.fetch())
    if not logs:
        return jsonify({"error": "No logs found for the given submission ID"}), 404

    return jsonify({"logs": logs}), 200

@app.route('/')
def home():
    return "Smart Contract Analysis Service is running", 200

# Universal error handler to log exceptions with full stack trace
@app.errorhandler(Exception)
def handle_exception(e):
    # Log the exception with full stack trace
    app.logger.error("Exception occurred", exc_info=e)
    
    # Return a generic error response
    return jsonify({"error": "An unexpected error occurred."}), 500

# Register the storage blueprint
app.register_blueprint(storage_blueprint)

@app.route('/api/verify_deployment_script', methods=['POST'])
@authenticate
@inject_analysis_params
def verify_deploy_script(submission, request_context, user_prompt):
    """Verify the deployment script without executing it."""
    try:
        update_analysis_status(
            submission["submission_id"],
            "verify_deployment_script",
            "in_progress"
        )
        # Get the current context using prepare_context
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=False)

        # Initialize DeploymentAnalyzer
        deployer = DeploymentAnalyzer(context)

        # Verify the deployment script
        result = deployer.verify_deployment_script()

        # Process the result based on returncode
        if result[0] == 0:  # Success
            update_analysis_status(
                submission["submission_id"],
                "verify_deployment_script",
                "success",
                step_metadata={
                    "log": list(result)  # contract addresses
                }
            )
            if request_context == "bg":
                create_task({"submission_id": submission["submission_id"]})
            return jsonify({
                "success": True,
                "log": list(result)  # stdout
            }), 200
        else:  # Failure
            update_analysis_status(
                submission["submission_id"],
                "verify_deployment_script",
                "error",
                step_metadata={
                    "log": list(result)  # stderr or error message
                }
            )
            if request_context == "bg":
                create_task({"submission_id": submission["submission_id"]})
            return jsonify({
                "success": False,
                "log": list(result)  # stdout
            }), 200

    except Exception as e:
        app.logger.error("Error in verify_deploy_script endpoint", exc_info=e)
        update_analysis_status(
                submission["submission_id"],
                "verify_deployment_script",
                "error",
                step_metadata={
                    "log": [-1, {}, "", str(e)]  # stderr or error message
                }
            )
        return jsonify({
            "success": False,
            "log":   [-1, {}, "", str(e)]  # stderr or error message
        }), 200

@app.route('/api/debug_deploy_script', methods=['POST'])
@authenticate
@inject_analysis_params
def debug_deploy_script(submission, request_context, user_prompt):
    """Debug endpoint to provide detailed information about the submission and context."""
    try:
        update_analysis_status(
            submission["submission_id"],
            "debug_deployment_script",
            "in_progress"
        )
        # Get the current context using prepare_context
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=False)
        # Initialize DeploymentAnalyzer
        deployer = DeploymentAnalyzer(context)
        step_data = submission.get("verify_deployment_script")
        if step_data:
            step_data = json.loads(step_data)
        step_status = submission.get("completed_steps", [])
        step_status = [step for step in step_status if step["step"] == "verify_deployment_script"]
        if step_status:
            step_status = step_status[0]
        else:
            step_status = None
        new_code = deployer.debug_deployment_script(step_data, step_status)

        update_analysis_status(
            submission["submission_id"],
            "debug_deployment_script",
            "success",
            step_metadata={
                "log": new_code.change_summary
            }
        )
        if (request_context == "bg"):
            create_task({"submission_id": submission["submission_id"]})

        return jsonify({
            "success": True,
            "log": {"summary": new_code.change_summary}
        }), 200
    except Exception as e:
        app.logger.error("Error in debug_deploy_script endpoint", exc_info=e)
        update_analysis_status(
            submission["submission_id"],
            "debug_deployment_script",
            "error",
            metadata={"log": str(e)}
        )
        return jsonify({"error": str(e)}), 200

    except Exception as e:
        app.logger.error("Error in debug endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500


@app.route('/api/submission/<submission_id>/simulations/new', methods=['POST'])
@authenticate
def run_simulation(submission_id):
    """Run a simulation and track its status."""
    try:
        submission = datastore_client.get(datastore_client.key("Submission", submission_id))
        if not submission:
            return jsonify({"error": "Submission not found"}), 404
        
        data = request.get_json()
        description = data.get("description", "")
        num_simulations = data.get("num_simulations", 1)
        batch_id = data.get("batch_id")
        batch = None
        if batch_id:
            batch = datastore_client.get(datastore_client.key("SimulationRun", batch_id))
            if not batch:
                return jsonify({"error": "Batch simulation run not found"}), 404
        branch = data.get("branch", "main")
        if batch is not None:
            branch = batch.get("branch", "main")

        actor_config = data.get("actor_config")
        # Update submission with actor_config if provided
        if actor_config:
            submission["actor_config"] = actor_config
            datastore_client.put(submission)

        run_id = str(uuid.uuid4())
        
        run = SimulationRun(
            run_id,
            submission_id,
            "created",
            "run",
            description=description,
            branch=branch,
            actor_config=actor_config or submission.get("actor_config", {})
        )
        run.create()

        context = prepare_context_lazy(submission, needs_parallel_workspace=False)

        runner = SimulationRunner(context, run)
        job = runner.create_and_execute_cloud_run_job()
        
        return jsonify({"message": "Simulation started successfully", "simulation_id": run_id, "job_name": job}), 200

    except Exception as e:
        app.logger.error("Error in run_simulation endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 200

@app.route('/api/submission/<submission_id>/simulations/list', methods=['GET'])
@authenticate
def get_simulation_runs_for_submission(submission_id):
    """Fetch all simulation runs for a specific submission ID."""
    try:
        # Fetch the submission from the datastore
        submission = datastore_client.get(datastore_client.key("Submission", submission_id))
        if not submission:
            return jsonify({"error": "Submission not found"}), 404

        
        # Get all simulation runs for the submission
        simulation_runs = SimulationRunner.get_runs(submission_id)

        return jsonify({"simulation_runs": simulation_runs}), 200

    except Exception as e:
        app.logger.error("Error in get_simulation_runs_for_submission endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500
    

@app.route('/api/submission/<submission_id>/simulations/batch/<batch_id>/list', methods=['GET'])
@authenticate
def get_simulation_runs_for_batch(submission_id, batch_id):
    """Fetch all simulation runs for a specific submission ID."""
    try:
        # Fetch the submission from the datastore
        submission = datastore_client.get(datastore_client.key("Submission", submission_id))
        if not submission:
            return jsonify({"error": "Submission not found"}), 404

        
        # Get all simulation runs for the submission
        simulation_runs = SimulationRunner.get_runs_by_batch(submission_id, batch_id)

        return jsonify({"simulation_runs": simulation_runs}), 200

    except Exception as e:
        app.logger.error("Error in get_simulation_runs_for_submission endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500


@app.route('/api/simulation_runs/<simulation_id>/log', methods=['GET'])
@authenticate
def get_simulation_run_log(simulation_id):
    """Get a presigned link for the simulation run log."""
    try:
        # Fetch the simulation run from the datastore
        key = datastore_client.key("SimulationRun", simulation_id)
        simulation_run = datastore_client.get(key)
        if not simulation_run:
            return jsonify({"error": "Simulation run not found"}), 404

        # Generate a signed URL for the log file
        bucket = storage_client.bucket("ilumina-simulation-logs")  # Replace with your GCS bucket name
        blob = bucket.blob(f"simulation_logs/{simulation_id}.log")

        if not blob.exists():
            return jsonify({"error": "Log file not found"}), 404

        signed_url = blob.generate_signed_url(expiration=datetime.timedelta(minutes=15), 
                                              method="GET",
                                              version='v4',
                                              response_disposition='inline'
                                            )

        return jsonify({"log_url": signed_url}), 200

    except Exception as e:
        app.logger.error("Error in get_simulation_run_log endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500

@app.route('/api/submission/<submission_id>/simulations/batch/new', methods=['POST'])
@authenticate
def run_simulation_batch(submission_id):
    """Run a batch of simulations and track their status."""
    try:
        # Fetch the submission from the datastore
        submission = datastore_client.get(datastore_client.key("Submission", submission_id))
        if not submission:
            return jsonify({"error": "Submission not found"}), 404

        # Parse request data
        data = request.get_json()
        description = data.get("description", "Batch simulation run")
        num_simulations = data.get("num_simulations", 1)
        branch = data.get("branch", "main")
        actor_config = data.get("actor_config")
        
        # Update submission with actor_config if provided
        if actor_config:
            submission["actor_config"] = actor_config
            datastore_client.put(submission)

        # Validate num_simulations
        if num_simulations == 1:
            return jsonify({"error": "num_simulations must be greater than 1"}), 400

        # Create a new SimulationRun entity
        batch_id = str(uuid.uuid4())
        batch = SimulationRun(
            batch_id,
            submission_id,
            "created",
            "batch",
            description=description,
            branch=branch,
            num_simulations=num_simulations,
            actor_config=actor_config or submission.get("actor_config", {})
        )
        batch.create()
        for i in range(num_simulations):
            run_id = str(uuid.uuid4())
            run = SimulationRun(run_id, submission_id, "scheduled", "run", batch_id=batch_id, actor_config=actor_config or submission.get("actor_config", {}))
            run.create()

        batch.update_status("created", metadata={
            "total": num_simulations,
            "scheduled": num_simulations,
            "success": 0,
            "failed": 0
        })

        context = prepare_context_lazy(submission, needs_parallel_workspace=False)
        runner = SimulationRunner(context, batch)
        job = runner.create_and_execute_cloud_run_job()

        # Return success response
        return jsonify({
            "message": "Batch simulation run created successfully",
            "simulation_run_id": batch_id,
            "task_name": job,
            "status": "scheduled"
        }), 200

    except Exception as e:
        app.logger.error("Error in run_simulation_batch endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/submission/<submission_id>/simulations/batch/split', methods=['POST'])
@authenticate
def split_simulation_batch(submission_id):
    """Split a batch of simulations and create tasks for each."""
    try:
        # Fetch the submission from the datastore
        submission = datastore_client.get(datastore_client.key("Submission", submission_id))
        if not submission:
            return jsonify({"error": "Submission not found"}), 404
        
        
        # Parse request data
        data = request.get_json()
        batch_id = data.get("batch_id")
        batch = datastore_client.get(datastore_client.key("SimulationRun", batch_id))
        if not batch:
            return jsonify({"error": "Batch not found"}), 200
        
        num_simulations = batch.get("num_simulations", 1)
        branch = batch.get("branch", "main")

        # Validate num_simulations
        if num_simulations <= 1:
            return jsonify({"error": "num_simulations must be greater than 1"}), 400
        
        in_progress_runs = datastore_client.query(kind="SimulationRun")
        in_progress_runs.add_filter("submission_id", "=", submission_id)
        in_progress_runs.add_filter("status", "=", "in_progress")
        in_progress_runs.add_filter("batch_id", "=", batch_id)
        in_progress_runs = list(in_progress_runs.fetch())

        total_runs = datastore_client.query(kind="SimulationRun")
        total_runs.add_filter("submission_id", "=", submission_id)
        total_runs.add_filter("batch_id", "=", batch_id)
        total_runs = list(total_runs.fetch())

        MAX_SIMULTANEOUS_RUNS = 5
        
        if len(in_progress_runs) >= MAX_SIMULTANEOUS_RUNS:
            # max simutaneous simulation runs reached, will try to create runs again later.
            create_split_and_monitor_task(submission_id, batch_id, begin_delay=120)
            return jsonify({
                "message": "Max simultaneous simulation runs reached. Will try again later.",
                "simulation_run_id": batch_id,
                "status": "in_progress"
            }), 200
        
        max_to_create = MAX_SIMULTANEOUS_RUNS - len(in_progress_runs)
        
        if max_to_create + len(total_runs) > num_simulations:
            max_to_create = num_simulations - len(total_runs)
        if max_to_create <= 0:
            return jsonify({
                "message": "No new simulation runs can be created at this time.",
                "batch_id": batch_id,
                "status": "in_progress"
            }), 200
        else:
            for i in range(max_to_create):
                create_run_simulation_task(submission_id, {
                    "batch_id": batch_id,
                    "branch": branch,
                    "actor_config": batch.get("actor_config")
                })
            create_split_and_monitor_task(submission_id, batch_id, begin_delay=120)
        return jsonify({
            "message": f"Created {max_to_create} simulation runs.",
            "batch_id": batch_id,
            "status": "in_progress"
        }), 200

    except Exception as e:
        app.logger.error("Error in split_simulation_batch endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500

@app.route('/api/submission/<submission_id>/history', methods=['GET'])
@authenticate
def get_submission_history(submission_id):
    """Fetch the history of all actions on a submission ID."""
    try:
        # Query SubmissionLog for the given submission_id
        query = datastore_client.query(kind="SubmissionLog")
        query.add_filter("submission_id", "=", submission_id)
        #query.order = ["-created_at"]

        logs = list(query.fetch())
        logs = sorted(logs, key=lambda x: x["updated_at"], reverse=True)

        # Extract only the required fields
        history = [
            {
                "step": log.get("step"),
                "status": log.get("status"),
                "user_prompt": log.get("user_prompt", ""),
                "executed_at": log.get("updated_at"),
                "step_metadata": _get_step_metadata(log)
            }
            for log in logs
        ]

        return jsonify({"history": history}), 200

    except Exception as e:
        app.logger.error("Error in get_submission_history endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500
    
def _get_step_metadata(log):
    """Extract step metadata from the log."""
    step = log.get("step")
    match step:
        case "analyze_project":
            return log.get("summary_version", "")
        case "analyze_actors":
            return log.get("actor_version", "")
        case "analyze_deployment":
            return log.get("deployment_instruction_version", "")
        case "implement_deployment_script":
            return log.get("implement_deployment_script", "")
        case "verify_deployment_script":
            return log.get("verify_deployment_script", "")
        case "debug_deployment_script":
            return log.get("debug_deployment_script", "")
        case "scaffold":
            return log.get("scaffold", "")
        case _:
            return "" 

@app.route('/api/analyze_action', methods=['POST'])
@authenticate
@inject_analysis_params
def analyze_action(submission, request_context, user_prompt):
    """Analyze a specific action for a given contract (with parallel workspace)."""
    try:
        # Get parameters from request
        data = request.get_json()
        contract_name = data.get("contract_name")
        function_name = data.get("function_name")
        parallel_workspace_id = data.get("parallel_workspace_id") or str(uuid.uuid4())
        if not contract_name or not function_name:
            return jsonify({"error": "Both contract_name and action_name are required"}), 400

        # Get the current context
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=True, parallel_workspace_id=parallel_workspace_id)
        
        # Load the Actors file
        actors = context.actor_summary()
        if actors is None:
            return jsonify({
                "error": "Actors summary not found. Please ensure the analyze_actors step has completed successfully."
            }), 400

        # Get the action
        action = actors.find_action(contract_name, function_name)
        if not action:
            return jsonify({"error": f"Action {contract_name} {function_name} not found in actors file"}), 404

        update_action_analysis_status(submission["submission_id"], contract_name, function_name, "analyze", "in_progress")
        print (f"Analyzing.. {action.to_dict()}")
    
        # Create ActionAnalyzer and analyze the action
        analyzer = ActionAnalyzer(action, context)
        analysis_result = analyzer.analyze(action)

        # Update status to success
        update_action_analysis_status(submission["submission_id"], contract_name, function_name, "analyze", "success")

        # After success, enqueue check_contract_actions_analyzed for this contract
        create_task({
            "submission_id": submission["submission_id"],
            "contract_name": contract_name,
            "step": "check_contract_actions_analyzed"
        })
        return jsonify({"message": "Action analysis completed successfully", "status": "success"}), 200

    except Exception as e:
        # Update status to error
        app.logger.error("Error in analyze_action endpoint", exc_info=e)
        update_action_analysis_status(submission["submission_id"], contract_name, function_name, "analyze", "error", metadata={
            "message": str(e)
        })
        return jsonify({"error": str(e)}), 200

@app.route('/api/analyze_all_actions', methods=['POST'])
@authenticate
@inject_analysis_params
def analyze_all_actions(submission, request_context, user_prompt):
    """Analyze all actions for a submission by creating tasks for each action"""
    try:
        # Get the current context
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=False)
        update_analysis_status(
            submission["submission_id"],
            "analyze_all_actions",
            "in_progress"
        )
        
        # Load the Actors file
        actors = context.actor_summary()
        if actors is None:
            return jsonify({
                "error": "Actors summary not found. Please ensure the analyze_actors step has completed successfully."
            }), 400
        # For each actor and action, create a task
        count = 0
        for actor in actors.actors:
            for action in actor.actions:
                parallel_workspace_id = str(uuid.uuid4())
                # Create analyze_action task with parallel_workspace
                update_action_analysis_status(
                    submission["submission_id"],
                    action.contract_name,
                    action.function_name,
                    "analyze",
                    "scheduled"
                )
                create_task({
                    "submission_id": submission["submission_id"],
                    "contract_name": getattr(action, "contract_name", None),
                    "function_name": getattr(action, "function_name", None),
                    "step": "analyze_action",
                    "parallel_workspace": True,
                    "parallel_workspace_id": parallel_workspace_id
                })
                count += 1
        
        return jsonify({
            "message": f"Created tasks for analyzing {count} actions",
            "status": "success"
        }), 200

    except Exception as e:
        app.logger.error("Error in analyze_all_actions endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/analyze_all_snapshots', methods=['POST'])
@authenticate
@inject_analysis_params
def analyze_all_snapshots(submission, request_context, user_prompt):
    """Analyze all actions for a submission by creating tasks for each action"""
    try:
        # Get the current context
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=False)
        update_analysis_status(
            submission["submission_id"],
            "analyze_all_snapshots",
            "in_progress"
        )
        
        # Load the Actors file
        deployment_instructions = context.deployment_instructions()

        count = 0
        contracts = set()
        for instruction in deployment_instructions.sequence:
                if instruction.type == "deploy":
                    contract_name = instruction.contract
                    if contract_name and contract_name not in contracts:
                        # Create analyze_snapshot task with parallel_workspace
                        update_snapshot_analysis_status(
                            submission["submission_id"],
                            contract_name,
                            "analyze_snapshot",
                            "scheduled"
                        )
                        create_task({
                            "submission_id": submission["submission_id"],
                            "contract_name": contract_name,
                            "step": "analyze_snapshot"
                        })
                        contracts.add(contract_name)
                        count += 1
        
        return jsonify({
            "message": f"Created tasks for analyzing {count} contracts",
            "status": "success"
        }), 200

    except Exception as e:
        app.logger.error("Error in analyze_all_snapshot endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500

@app.route('/api/submission/<submission_id>/actions', methods=['GET'])
@authenticate
def get_action_analyses(submission_id):
    """Get all action analyses for a submission"""
    try:
        # Query all action analyses for this submission
        query = datastore_client.query(kind="SubmissionActionAnalysis")
        query.add_filter("submission_id", "=", submission_id)
        query.order = ["contract_name", "function_name"]
        
        action_analyses = list(query.fetch())
        
        # Transform the data for the response
        analyses = []
        for analysis in action_analyses:
            analyses.append({
                "contract_name": analysis.get("contract_name"),
                "function_name": analysis.get("function_name"),
                "status": analysis.get("status"),
                "step": analysis.get("step"),
                "updated_at": analysis.get("updated_at"),
                "metadata": {k: v for k, v in analysis.items() 
                           if k not in ["contract_name", "function_name", "status", "step", "updated_at"]}
            })
        
        return jsonify({
            "submission_id": submission_id,
            "action_analyses": analyses,
            "count": len(analyses)
        }), 200

    except Exception as e:
        app.logger.error("Error in get_action_analyses endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500

@app.route('/api/check_contract_actions_analyzed', methods=['POST'])
@authenticate
@inject_analysis_params
def check_contract_actions_analyzed(submission, request_context, user_prompt):
    """Check if all actions for a contract are analyzed, then trigger snapshot/implement steps."""
    try:
        data = request.get_json()
        submission_id = submission["submission_id"]
        # Query all actions for this contract
        query = datastore_client.query(kind="SubmissionActionAnalysis")
        query.add_filter("submission_id", "=", submission_id)
        actions = list(query.fetch())
        # Check if all actions are analyzed (status == 'success')
        all_analyzed = all(a.get("status") == "success" for a in actions)
        if all_analyzed and actions:
            update_analysis_status(
                submission_id,
                "analyze_all_actions",
                "success",
                metadata={"message": "All actions analyzed successfully"}
            )
            # Enqueue analyze_snapshot for this contract
            create_task({
                "submission_id": submission_id,
                "step": "analyze"
            })
            return jsonify({"message": f"All actions analyzed. Snapshot task enqueued."}), 200
        else:
            return jsonify({"message": f"Not all actions analyzed."}), 200
    except Exception as e:
        app.logger.error("Error in check_contract_actions_analyzed endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/check_contract_actions_implemented', methods=['POST'])
@authenticate
@inject_analysis_params
def check_contract_actions_implemented(submission, request_context, user_prompt):
    """Check if all actions for a contract are analyzed, then trigger snapshot/implement steps."""
    try:
        data = request.get_json()
        submission_id = submission["submission_id"]
        # Query all actions for this contract
        query = datastore_client.query(kind="SubmissionActionAnalysis")
        query.add_filter("submission_id", "=", submission_id)
        actions = list(query.fetch())
        # Check if all actions are analyzed (status == 'success')
        all_implemented = all(a.get("status") == "success" for a in actions)
        if all_implemented and actions:
            update_analysis_status(
                submission_id,
                "implement_all_actions",
                "success"
            )
            # Enqueue analyze_snapshot for this contract
            create_task({
                "submission_id": submission_id,
                "step": "analyze"
            })
            return jsonify({"message": f"All actions implemented."}), 200
        else:
            return jsonify({"message": f"Not all actions analyzed."}), 200
    except Exception as e:
        app.logger.error("Error in check_contract_actions_implemented endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500


@app.route('/api/check_contract_snapshots_analyzed', methods=['POST'])
@authenticate
@inject_analysis_params
def check_contract_snapshots_analyzed(submission, request_context, user_prompt):
    """Check if all actions for a contract are analyzed, then trigger snapshot/implement steps."""
    try:
        data = request.get_json()
        submission_id = submission["submission_id"]
        # Query all actions for this contract
        query = datastore_client.query(kind="SubmissionSnapshotAnalysis")
        query.add_filter("submission_id", "=", submission_id)
        snapshots = list(query.fetch())
        # Check if all actions are analyzed (status == 'success')
        all_analyzed = all(s.get("status") == "success" for s in snapshots)
        if all_analyzed and snapshots:
            update_analysis_status(
                submission_id,
                "analyze_all_snapshots",
                "success",
                metadata={"message": "All snapshots analyzed successfully"}
            )
            # Enqueue analyze_snapshot for this contract
            create_task({
                "submission_id": submission_id,
                "step": "analyze"
            })
            return jsonify({"message": f"All actions analyzed. Snapshot task enqueued."}), 200
        else:
            return jsonify({"message": f"Not all snapshots are analyzed."}), 200
    except Exception as e:
        app.logger.error("Error in check_contract_snapshots_analyzed endpoint", exc_info=e)
        return jsonify({"error": str(e)}), 500

    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)