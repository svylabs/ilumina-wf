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
from app.context import prepare_context, RunContext
from app.storage import GCSStorage
from app.github import GitHubAPI
from app.summarizer import ProjectSummarizer
from app.models import Project
from app.deployer import ContractDeployer
from app.actor import ActorAnalyzer
from app.git_utils import GitUtils
import shutil

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
TASK_HANDLER_URL = os.getenv("TASK_HANDLER_URL", "https://ilumina-451416.uc.r.appspot.com/analyse")

client = None
# client = tasks_v2.CloudTasksClient()
if os.getenv("USE_CREDENTIAL_FILE") == "true":
    creds_path = os.getenv("GCS_CREDENTIALS_PATH")
    client = tasks_v2.CloudTasksClient.from_service_account_file(creds_path)
else:
    client = tasks_v2.CloudTasksClient()
    
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
        
        while analyzer.not_done():
            analyzer.step()
            #analyzer.print_current_step()
        
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
            # "first_5_files": file_list[:5],
            "all_files": file_list
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


@app.route('/api/submission/<submission_id>/create_simulation_repo', methods=['POST'])
@authenticate
def create_simulation_repo(submission_id):
    """Create simulation repo from pre-scaffolded template"""
    try:
        data = request.get_json()
        project_name = data.get("project_name", f"project-{submission_id}")

        # Replace invalid characters with hyphens and convert to lowercase
        project_name = re.sub(r'[^a-zA-Z0-9-]', '-', project_name).lower()

        # Ensure no consecutive hyphens and strip leading/trailing hyphens
        project_name = re.sub(r'-+', '-', project_name).strip('-')

        # Create repository name
        repo_name = f"{project_name}-simulation"
        
        # 1. Create GitHub repository
        repo_data = github_api.create_repository(
            name=repo_name,
            private=True,
            description=f"Simulation repository for {project_name} (pre-scaffolded)"
        )
        
        # 2. Prepare local workspace
        repo_path = f"/tmp/{repo_name}"
        
        # 3. Clone template and initialize
        template_repo = os.getenv(
            "SIMULATION_TEMPLATE_REPO",
            "https://github.com/svylabs-com/ilumina-scaffolded-template.git"
        )
        
        GitUtils.create_from_template(
            template_url=template_repo,
            new_repo_path=repo_path,
            new_origin_url=repo_data["clone_url"],
            project_name=project_name
        )
        
        # Cleanup
        try:
            shutil.rmtree(repo_path)
        except Exception as e:
            app.logger.warning(f"Cleanup warning: {str(e)}")
        
        return jsonify({
            "status": "success",
            "repo_name": repo_name,
            "repo_url": repo_data["html_url"],
            "clone_url": repo_data["clone_url"],
            "template_source": template_repo,
            "scaffolded": False  # False because we used pre-scaffolded template
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "message": "Failed to create simulation repository"
        }), 500
    


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
        context = prepare_context(data)

        # Determine the next step
        analyzer = Analyzer(context)
        if not analyzer.is_step_done("summary"):
            create_task({"submission_id": submission_id, "step": "analyze_project"})
            return jsonify({"message": "Enqueued step: analyze_project"}), 200
        elif not analyzer.is_step_done("actors"):
            create_task({"submission_id": submission_id, "step": "analyze_actors"})
            return jsonify({"message": "Enqueued step: analyze_actors"}), 200
        elif not analyzer.is_step_done("deployment"):
            create_task({"submission_id": submission_id, "step": "analyze_deployment"})
            return jsonify({"message": "Enqueued step: analyze_deployment"}), 200
        else:
            return jsonify({"message": "All steps are completed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze_project', methods=['POST'])
@authenticate
def analyze_project():
    """Perform the project analysis step"""
    try:
        data = request.get_json()
        submission_id = data.get("submission_id")

        if not submission_id:
            return jsonify({"error": "Missing submission_id"}), 400

        # Get the current context using prepare_context
        context = prepare_context(data)

        # Perform the project analysis
        analyzer = Analyzer(context)
        analyzer.create_summary()

        # Update the task queue
        create_task({"submission_id": submission_id, "step": "analyze_actors"})

        return jsonify({"message": "Project analysis completed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze_actors', methods=['POST'])
@authenticate
def analyze_actors():
    """Perform the actor analysis step"""
    try:
        data = request.get_json()
        submission_id = data.get("submission_id")

        if not submission_id:
            return jsonify({"error": "Missing submission_id"}), 400

        # Get the current context using prepare_context
        context = prepare_context(data)

        # Perform the actor analysis
        analyzer = Analyzer(context)
        analyzer.create_actors()

        # Update the task queue
        create_task({"submission_id": submission_id, "step": "analyze_deployment"})

        return jsonify({"message": "Actor analysis completed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze_deployment', methods=['POST'])
@authenticate
def analyze_deployment():
    """Perform the deployment analysis step"""
    try:
        data = request.get_json()
        submission_id = data.get("submission_id")

        if not submission_id:
            return jsonify({"error": "Missing submission_id"}), 400

        # Get the current context using prepare_context
        context = prepare_context(data)

        # Perform the deployment analysis
        analyzer = Analyzer(context)
        analyzer.create_deployment_instructions()

        return jsonify({"message": "Deployment analysis completed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "Smart Contract Analysis Service is running", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)