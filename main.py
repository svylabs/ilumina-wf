from flask import Flask, request, jsonify
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
def inject_submission(f):
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

        if not submission:
            return jsonify({"error": "Submission not found"}), 404

        # Pass the submission to the wrapped function
        return f(submission, request_context, *args, **kwargs)

    return decorated_function

def create_task(data):
    api_suffix = "/analyze"
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
    return jsonify({
        "submission_id": submission["submission_id"],
        "github_repository_url": submission["github_repository_url"],
        "run_id": submission["run_id"],
        "created_at": submission["created_at"],
        "updated_at": submission["updated_at"],
        "step": submission.get("step"),
        "status": submission.get("status"),
        "completed_steps": submission.get("completed_steps", [])
    }), 200

@app.route('/api/begin_analysis', methods=['POST'])
@authenticate
def begin_analysis():
    """Start a new analysis task"""
    data = request.get_json()
    
    if not data or "github_repository_url" not in data or "submission_id" not in data:
        return jsonify({"error": "Invalid data format"}), 400
    
    data["run_id"] = data.get("run_id", str(int(datetime.datetime.now().timestamp())))
    
    store_analysis_metadata(data)
    task_name = create_task(data)
    
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

        if not submission_id:
            return jsonify({"error": "Missing submission_id"}), 400

        # Get the current context using prepare_context
        submission = datastore_client.get(datastore_client.key("Submission", submission_id))

        # Ensure submission has a 'step' attribute
        if "step" not in submission or submission["step"] is None or submission["step"] == "":
            create_task({"submission_id": submission_id, "step": "analyze_project"})
            return jsonify({"message": "Enqueued step: analyze_project"}), 200
        elif submission["step"] == "analyze_project":
            create_task({"submission_id": submission_id, "step": "analyze_actors"})
            return jsonify({"message": "Enqueued step: analyze_actors"}), 200
        elif submission["step"] == "analyze_actors":
            create_task({"submission_id": submission_id, "step": "analyze_deployment"})
            return jsonify({"message": "Enqueued step: analyze_deployment"}), 200
        else:
            return jsonify({"message": "All steps are completed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/analyze_project', methods=['POST'])
@authenticate
@inject_submission
def analyze_project(submission, request_context):
    """Perform the project analysis step"""
    try:
        # Get the current context using prepare_context
        print (submission)
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
            #update_analysis_status(submission.submission_id, "analyze_project", "success")
            return jsonify({"summary": project_summary.to_dict()}), 200

        return jsonify({"message": "Project analysis completed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze_actors', methods=['POST'])
@authenticate
@inject_submission
def analyze_actors(submission, request_context):
    """Perform the actor analysis step"""
    try:
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
            update_analysis_status(submission["submission_id"], "analyze_project", "success", metadata={"actor_version": version})
            create_task({"submission_id": submission["submission_id"]})
        else:
            step = "None"
            if "step" in submission:
                step = submission["step"]
            update_analysis_status(submission["submission_id"], step, "success", metadata={"actor_version": version})
            #update_analysis_status(submission.submission_id, "analyze_project")
            # If in foreground, return the result
            return jsonify({"actors": actors.to_dict()}), 200
        return jsonify({"message": "Project analysis completed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze_deployment', methods=['POST'])
@authenticate
@inject_submission
def analyze_deployment(submission, request_context):
    """Perform the deployment analysis step"""
    try:
        # Get the current context using prepare_context
        context = prepare_context(submission)

        # Perform the deployment analysis
        analyzer = Analyzer(context)
        analyzer.create_deployment_instructions()

        return jsonify({"message": "Deployment analysis completed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

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