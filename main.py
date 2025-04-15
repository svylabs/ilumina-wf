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
from app.context import prepare_context
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
from app.submission import store_analysis_metadata, update_analysis_status
from app.tools import authenticate
import uuid
import traceback
from google.protobuf import timestamp_pb2
from app.submission import UserPromptManager

# Ensure logs are written to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# Debug: Log all environment variables
for key, value in os.environ.items():
    print(f"ENV {key}: {value}")

# Initialize services
gcs = GCSStorage()
github_api = GitHubAPI()
user_prompt_manager = UserPromptManager(datastore_client)

PROJECT_ID = os.getenv("GCS_PROJECT_ID", "ilumina-451416")
QUEUE_ID = os.getenv("TASK_QUEUE_ID", "analysis-tasks")
LOCATION = os.getenv("TASK_LOCATION", "us-central1")
TASK_HANDLER_URL = "https://ilumina-451416.uc.r.appspot.com/api"

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

def create_task(data, forward_params=None):
    api_suffix = "/analyze"
    if forward_params:
        for key, value in forward_params.items():
            data[key] = value
    if "step" in data:
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
        "latest_prompts": latest_prompts
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
    """Determine the next step and enqueue it"""
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
        step = submission["step"]
        status = submission["status"]

        next_step = step
        if step_from_request != None:
            next_step = step_from_request
        else:
            if step == "begin_analysis":
                next_step = "analyze_project"
            elif step == "analyze_project":
                if status is not None and status == "success":
                    next_step = "analyze_actors"
            elif step == "analyze_actors":
                if status is not None and status == "success":
                    next_step = "None"
        
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
        else:
            return jsonify({"message": "All steps are completed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/analyze_project', methods=['POST'])
@authenticate
@inject_analysis_params
def analyze_project(submission, request_context, user_prompt):
    """Perform the project analysis step"""
    try:
        # Update status to in_progress
        update_analysis_status(submission["submission_id"], "analyze_project", "in_progress")

        # Store user prompt if available
        if user_prompt:
            user_prompt_manager.store_latest_prompt(submission["submission_id"], "analyze_project", user_prompt)
            user_prompt_manager.store_prompt_history(submission["submission_id"], "analyze_project", user_prompt)

        # Get the current context using prepare_context
        context = prepare_context(submission)

        # Perform the project analysis
        analyzer = Analyzer(context)
        project_summary = analyzer.summarize()
        
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
        context = prepare_context(submission)

        # Perform the actor analysis
        analyzer = Analyzer(context)
        actors = analyzer.identify_actors()

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
        return jsonify({"message": "Project analysis completed"}), 200

    except Exception as e:
        # Update status to error
        update_analysis_status(submission["submission_id"], "analyze_actors", "error", metadata={"message": str(e)})
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
        context = prepare_context(submission)

        # Perform the deployment analysis
        analyzer = Analyzer(context)
        deployment_instructions = analyzer.generate_deployment_instructions(user_prompt=user_prompt)
        version, path = context.new_gcs_deployment_instructions_path()

        # Upload deployment instructions to Google Cloud Storage
        upload_to_gcs(path, context.deployment_instructions_path())
        if request_context == "bg":
            # Update the task queue
            update_analysis_status(submission["submission_id"], "analyze_deployment", "success", metadata={"deployment_version": version})
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
    
@app.route('/api/implement-deployment-script', methods=['POST'])
@authenticate
def implement_deployment_script(submission, request_context):
    """Test endpoint for generate_deploy_ts"""
    context = prepare_context(submission)
    try:
        # Initialize DeploymentAnalyzer
        deployer = DeploymentAnalyzer(context)
        
        # Generate deploy.ts
        result_path = deployer.implement_deployment_script()
        
        # Read the generated file
        with open(result_path, 'r') as f:
            generated_code = f.read()

        return jsonify({
            "message": "deploy.ts generated successfully",
            "path": result_path,
            "code": generated_code
        }), 200

    except Exception as e:
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)