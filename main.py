from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
from google.cloud import datastore, tasks_v2
from functools import wraps
import json
import datetime
import logging
import sys
from app.analyse import Analyzer
from app.context import prepare_context, RunContext
from app.storage import GCSStorage
from app.github import GitHubAPI

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

# Cloud Tasks config
PROJECT_ID = os.getenv("GCS_PROJECT_ID", "ilumina-451416")
QUEUE_ID = os.getenv("TASK_QUEUE_ID", "analysis-tasks")
LOCATION = os.getenv("TASK_LOCATION", "us-central1")
TASK_HANDLER_URL = os.getenv("TASK_HANDLER_URL", "https://ilumina-451416.uc.r.appspot.com/analyse")

# client = tasks_v2.CloudTasksClient()
creds_path = os.getenv("GCS_CREDENTIALS_PATH")
client = tasks_v2.CloudTasksClient.from_service_account_file(creds_path)

parent = client.queue_path(PROJECT_ID, LOCATION, QUEUE_ID)

def authenticate(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or auth_header != f"Bearer {SECRET_PASSWORD}":
            return jsonify({"error": "Unauthorized access"}), 401
        return f(*args, **kwargs)
    return decorated_function

def store_analysis_metadata(data):
    """Store submission metadata in Datastore"""
    client = datastore.Client()
    entity = datastore.Entity(key=client.key("Submission", data["submission_id"]))
    entity.update({
        "github_repository_url": data["github_repository_url"],
        "submission_id": data["submission_id"],
        "status": "pending",
        "created_at": datetime.datetime.now(),
        "updated_at": datetime.datetime.now()
    })
    client.put(entity)

def create_task(data):
    """Create a Cloud Task for async processing"""
    task = {
        "http_request": {
            "http_method": "POST",
            "url": TASK_HANDLER_URL,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(data).encode(),
        }
    }
    return client.create_task(request={"parent": parent, "task": task}).name

def update_analysis_status(submission_id, status, error=None):
    """Update analysis status in Datastore"""
    client = datastore.Client()
    key = client.key("Submission", submission_id)
    entity = client.get(key)
    if entity:
        updates = {
            "status": status,
            "updated_at": datetime.datetime.now()
        }
        if error:
            updates["error"] = error
        entity.update(updates)
        client.put(entity)

@app.route('/begin_analysis', methods=['POST'])
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

@app.route('/analyse', methods=['POST'])
def analyse():
    """Process the analysis task"""
    data = request.get_json()
    app.logger.info(f"Starting analysis for {data['submission_id']}")
    
    try:
        context = prepare_context(data)
        analyzer = Analyzer(context)
        
        while analyzer.has_next_step():
            analyzer.execute_next_step()
            analyzer.save_progress()
        
        update_analysis_status(data["submission_id"], "completed")
        
        return jsonify({
            "message": "Analysis completed",
            "submission_id": data["submission_id"]
        }), 200
    except Exception as e:
        app.logger.error(f"Analysis failed: {str(e)}")
        update_analysis_status(data["submission_id"], "failed", str(e))
        return jsonify({"error": str(e)}), 500
    
@app.route('/test_predify', methods=['GET'])
def test_predify():
    try:
        # Initialize clients
        github = GitHubAPI()
        gcs = GCSStorage()
        
        # Fetch Predify repo contents
        contents = github.get_repo_contents("https://github.com/svylabs/predify")
        file_list = [item['name'] for item in contents if isinstance(item, dict)]
        
        # Store in GCS
        gcs.write_json(
            "predify_test/files.json",
            {"files": file_list}
        )
        
        return jsonify({
            "status": "success",
            "files_found": len(file_list),
            "first_5_files": file_list[:5]
        })
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "message": "Make sure your GCS service account has Storage Object Admin permissions"
        }), 500
    
@app.route('/test_upload', methods=['GET'])
def test_upload():
    """Test endpoint for GCS upload"""
    try:
        # Initialize clients
        github = GitHubAPI()
        gcs = GCSStorage()
        
        # 1. Fetch Predify repo contents
        contents = github.get_repo_contents("https://github.com/svylabs/predify")
        file_list = [item['name'] for item in contents if isinstance(item, dict)]
        
        # 2. Prepare test data
        test_data = {
            "repository": "svylabs/predify",
            "timestamp": datetime.datetime.now().isoformat(),
            "files": file_list,
            "status": "test_successful"
        }
        
        # 3. Upload to GCS
        blob_path = f"tests/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        gcs.write_json(blob_path, test_data)
        
        # 4. Verify upload
        uploaded_data = gcs.read_json(blob_path)
        
        return jsonify({
            "status": "success",
            "blob_path": blob_path,
            "uploaded_data": uploaded_data
        })
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "message": "GCS upload test failed"
        }), 500

@app.route('/api/submission/<submission_id>/summary', methods=['GET'])
@authenticate
def get_project_summary(submission_id):
    """Get project summary"""
    try:
        summary = gcs.read_json(f"workspaces/{submission_id}/summary.json")
        return jsonify(summary), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 404

@app.route('/api/submission/<submission_id>/actors', methods=['GET'])
@authenticate
def get_actor_summary(submission_id):
    """Get actor summary"""
    try:
        actors = gcs.read_json(f"workspaces/{submission_id}/actor-summary.json")
        return jsonify(actors), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 404

@app.route('/api/submission/<submission_id>/simulations', methods=['GET'])
@authenticate
def get_simulation_results(submission_id):
    """Get simulation results"""
    try:
        sims = gcs.read_json(f"workspaces/{submission_id}/simulations.json")
        return jsonify(sims), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 404
    
@app.route('/')
def home():
    return "Smart Contract Analysis Service is running", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)