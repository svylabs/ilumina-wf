
from google.cloud import datastore
from .clients import datastore_client
import datetime

def store_analysis_metadata(data):
    """Store submission metadata in Datastore"""
    entity = datastore.Entity(key=datastore_client.key("Submission", data["submission_id"]))
    entity.update({
        "github_repository_url": data["github_repository_url"],
        "submission_id": data["submission_id"],
        "run_id": data["run_id"],
        "created_at": datetime.datetime.now(),
        "updated_at": datetime.datetime.now()
    })
    datastore_client.put(entity)

def update_analysis_status(submission_id, step, status, metadata=None):
    """Update analysis status in Datastore"""
    key = datastore_client.key("Submission", submission_id)
    entity = datastore_client.get(key)
    if entity:
        updates = {
            "step": step,
            "status": status,
            "updated_at": datetime.datetime.now()
        }
        if (metadata):
            for key, value in metadata.items():
                updates[key] = value
        entity.update(updates)
        datastore_client.put(entity)