from google.cloud import datastore, tasks, storage
import os
from google.cloud import run_v2

# Initialize Google Datastore client
def get_datastore_client():
    if os.getenv("USE_CREDENTIAL_FILE") == "true":
        credentials_path = os.getenv("GCS_CREDENTIALS_PATH", "devaccount.json")
        return datastore.Client.from_service_account_json(credentials_path)
    else:
        return datastore.Client()  # Default initialization

# Initialize Google Cloud Tasks client
def get_taskstore_client():
    if os.getenv("USE_CREDENTIAL_FILE") == "true":
        credentials_path = os.getenv("GCS_CREDENTIALS_PATH", "devaccount.json")
        return tasks.CloudTasksClient.from_service_account_file(credentials_path)
    else:
        return tasks.CloudTasksClient()  # Default initialization

# Initialize Google Cloud Storage client
def get_storage_client():
    if os.getenv("USE_CREDENTIAL_FILE") == "true":
        credentials_path = os.getenv("GCS_CREDENTIALS_PATH", "devaccount.json")
        return storage.Client.from_service_account_json(credentials_path)
    else:
        return storage.Client()  # Default initialization
    
def get_run_client():
    if os.getenv("USE_CREDENTIAL_FILE") == "true":
        credentials_path = os.getenv("GCS_CREDENTIALS_PATH", "devaccount.json")
        return run_v2.JobsClient.from_service_account_file(credentials_path)
    else:
        return run_v2.JobsClient()  # Default initialization

datastore_client = get_datastore_client()
tasks_client = get_taskstore_client()
storage_client = get_storage_client()
run_client = get_run_client()