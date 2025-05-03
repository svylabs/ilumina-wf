from google.cloud import datastore
from .clients import datastore_client
import datetime
import hashlib
import uuid
import json

def store_analysis_metadata(data):
    """Store submission metadata in Datastore"""
    entity = datastore.Entity(key=datastore_client.key("Submission", data["submission_id"]))
    entity.update({
        "github_repository_url": data["github_repository_url"],
        "submission_id": data["submission_id"],
        "run_id": data["run_id"],
        "step": "begin_analysis",
        "status": "completed",
        "created_at": datetime.datetime.now(),
        "updated_at": datetime.datetime.now()
    })
    datastore_client.put(entity)

    create_submission_log(entity.copy(), entity.exclude_from_indexes)

def create_submission_log(data, exclude_from_indexes):
    submission_log = datastore.Entity(key=datastore_client.key("SubmissionLog", str(uuid.uuid4())), exclude_from_indexes=list(exclude_from_indexes))
    submission_log.update(data)
    datastore_client.put(submission_log)

def update_analysis_status(submission_id, step, status, metadata=None, step_metadata=None):
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
                if key not in entity.exclude_from_indexes:
                    entity.exclude_from_indexes.add(key)
        if entity.get("completed_steps") is None:
            entity["completed_steps"] = []
        for completed_step in entity["completed_steps"]:
            if completed_step["step"] == step:
                completed_step["updated_at"] = datetime.datetime.now()
                completed_step["status"] = status
                found = True
        if not found:
            entity["completed_steps"].append({"step": step, "updated_at": datetime.datetime.now(), "status": status})
        if (step_metadata):
            entity[step] = json.dumps(step_metadata)
            entity.exclude_from_indexes.add(step)
        entity.update(updates)

        datastore_client.put(entity)
        
        create_submission_log(entity.copy(), entity.exclude_from_indexes)
        


class UserPromptManager:
    def __init__(self, datastore_client):
        self.datastore_client = datastore_client

    def _hash_prompt(self, user_prompt):
        """Generate a hash for the user prompt."""
        return hashlib.sha256(user_prompt.encode('utf-8')).hexdigest()

    def store_latest_prompt(self, submission_id, step, user_prompt):
        """Store the latest user prompt for a specific step."""
        prompt_hash = self._hash_prompt(user_prompt)
        key = self.datastore_client.key("LatestUserPrompt", f"{submission_id}_{step}")
        entity = datastore.Entity(key=key)
        entity.update({
            "submission_id": submission_id,
            "step": step,
            "user_prompt": user_prompt,
            "prompt_hash": prompt_hash,
            "timestamp": datetime.datetime.now()
        })
        self.datastore_client.put(entity)

    def store_prompt_history(self, submission_id, step, user_prompt):
        """Store the history of user prompts for a specific step."""
        prompt_hash = self._hash_prompt(user_prompt)

        # Check if the prompt hash already exists in history
        query = self.datastore_client.query(kind="UserPromptHistory")
        query.add_filter("submission_id", "=", submission_id)
        query.add_filter("step", "=", step)
        query.add_filter("prompt_hash", "=", prompt_hash)
        existing_prompts = list(query.fetch())

        if existing_prompts:
            return  # Do not store duplicate prompts

        key = self.datastore_client.key("UserPromptHistory")
        entity = datastore.Entity(key=key)
        entity.update({
            "submission_id": submission_id,
            "step": step,
            "user_prompt": user_prompt,
            "prompt_hash": prompt_hash,
            "timestamp": datetime.datetime.now()
        })
        self.datastore_client.put(entity)

    def query_latest_prompt(self, submission_id, step):
        """Query the latest user prompt for a specific step."""
        key = self.datastore_client.key("LatestUserPrompt", f"{submission_id}_{step}")
        return self.datastore_client.get(key)

    def query_prompt_history(self, submission_id, step):
        """Query the history of user prompts for a specific step, sorted by time."""
        query = self.datastore_client.query(kind="UserPromptHistory")
        query.add_filter("submission_id", "=", submission_id)
        query.add_filter("step", "=", step)
        query.order = ["-timestamp"]
        return list(query.fetch())