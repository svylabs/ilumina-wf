from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
from google.cloud import datastore, tasks_v2
from functools import wraps
import json
import os
import datetime
import logging
import sys

# Ensure logs are written to stdout instead of Supervisor capturing them
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

load_dotenv()

@app.route('/')
def home():
    return "Hello from Python!"

# Define a secret password for authentication
SECRET_PASSWORD = "my_secure_password"

# Google Cloud Tasks configuration
PROJECT_ID = "ilumina-451416"
QUEUE_ID = "analysis-tasks"
LOCATION = "us-central1"
TASK_HANDLER_URL = "https://ilumina-451416.uc.r.appspot.com/analyse"  # URL where the task will be processed

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

def store_in_datastore(data):
    client = datastore.Client()
    kind = "Submission"
    submission_key = client.key(kind, data["submission_id"])
    
    entity = datastore.Entity(key=submission_key)
    entity.update({
        "github_repository_url": data["github_repository_url"],
        "submission_id": data["submission_id"],
        "status": "pending",
        "created_at": datetime.datetime.now(),
        "updated_at": datetime.datetime.now()
    })
    
    client.put(entity)

def create_task(data):
    task = {
        "http_request": {  # HTTP request to the worker
            "http_method": tasks_v2.HttpMethod.POST,
            "url": TASK_HANDLER_URL,  # The worker endpoint
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(data).encode(),
        }
    }
    response = client.create_task(request={"parent": parent, "task": task})
    return response.name

@app.route('/begin_analysis', methods=['POST'])
@authenticate
def begin_analysis():
    data = request.get_json()
    
    if not data or "github_repository_url" not in data or "submission_id" not in data:
        return jsonify({"error": "Invalid data format"}), 400
    
    store_in_datastore(data)
    task_name = create_task(data)
    
    return jsonify({"message": "Analysis started and task queued", "task_name": task_name, "data_received": data}), 200

@app.route('/analyse', methods=['POST'])
def analyse():
    data = request.get_json()
    print("Received task data:", data)
    return jsonify({"message": "Task received", "data": data}), 200

if __name__ == '__main__':
    print("GEMINI" + os.getenv("GEMINI_API_KEY"))
    app.run(host='0.0.0.0', port=8080)
