from flask import Flask, request, jsonify
import os
import re
from dotenv import load_dotenv
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

# Ensure logs are written to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
app = Flask(__name__)
app.logger.setLevel(logging.INFO)

load_dotenv()

# Initialize services
gcs = GCSStorage()
github_api = GitHubAPI()

# Authentication
SECRET_PASSWORD = os.getenv("API_SECRET", "my_secure_password")

PROJECT_ID = os.getenv("GCS_PROJECT_ID", "ilumina-451416")
QUEUE_ID = os.getenv("TASK_QUEUE_ID", "analysis-tasks")
LOCATION = os.getenv("TASK_LOCATION", "us-central1")
TASK_HANDLER_URL = os.getenv("TASK_HANDLER_URL", "https://ilumina-451416.uc.r.appspot.com/api")

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

def authenticate(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or auth_header != f"Bearer {SECRET_PASSWORD}":
            return jsonify({"error": "Unauthorized access"}), 401
        return f(*args, **kwargs)
    return decorated_function

def create_task(data):
    api_suffix = "/analyze"
    if "step" in data:
        api_suffix = "/" + data["step"]
    """Create a Cloud Task for async processing"""
    task = {
        "http_request": {
            "http_method": "POST",
            "url": TASK_HANDLER_URL + api_suffix,
            "headers": {"Content-Type": "application/json", "Authorization": f"Bearer {SECRET_PASSWORD}"},
            "body": json.dumps(data).encode(),
        }
    }
    return tasks_client.create_task(request={"parent": parent, "task": task}).name

@app.route('/api/begin_analysis', methods=['POST'])
@authenticate
def begin_analysis():
    """Start a new analysis task"""
    data = request.get_json()
    
    if not data or "github_repository_url" not in data or "submission_id" not in data:
        return jsonify({"error": "Invalid data format"}), 400
    
    data["run_id"] = data.get("run_id", str(datetime.datetime.now().timestamp()))
    
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
        if not hasattr(submission, 'step') or submission.step is None:
            create_task({"submission_id": submission_id, "step": "analyze_project"})
            return jsonify({"message": "Enqueued step: analyze_project"}), 200
        elif submission.step == "analyze_project":
            create_task({"submission_id": submission_id, "step": "analyze_actors"})
            return jsonify({"message": "Enqueued step: analyze_actors"}), 200
        elif submission.step == "analyze_actors":
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
        context = prepare_context(submission)

        # Perform the project analysis
        analyzer = Analyzer(context)
        project_summary = analyzer.summarize()
        
        # Upload project summary to Google Cloud Storage
        bucket_name = os.getenv("GCS_BUCKET_NAME", "default-bucket")
        blob_name = f"summaries/{submission['submission_id']}/project_summary.json"
        upload_to_gcs(bucket_name, blob_name, context.summary_path())
        
        if request_context == "bg":
            # Update the task queue
            create_task({"submission_id": submission.submission_id})
            update_analysis_status(submission.submission_id, "analyze_project", "success")
        else:
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

        # Upload actors summary to Google Cloud Storage
        bucket_name = os.getenv("GCS_BUCKET_NAME", "default-bucket")
        blob_name = f"summaries/{submission['submission_id']}/actors_summary.json"
        upload_to_gcs(bucket_name, blob_name, context.actor_summary_path())

        if request_context == "bg": 
        # Update the task queue
            create_task({"submission_id": submission.submission_id})
            update_analysis_status(submission.submission_id, "analyze_project", "success")
        else:
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

# Register the storage blueprint
app.register_blueprint(storage_blueprint)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)