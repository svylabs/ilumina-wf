import os
from datetime import datetime
from app.storage import GCSStorage

def prepare_context(data):
    """Initialize and store context in GCS"""
    run_id = data["run_id"]
    submission_id = data["submission_id"]
    repo_url = data["github_repository_url"]
    
    gcs = GCSStorage()
    context = RunContext(submission_id, run_id, repo_url, gcs)
    
    # Store context metadata in GCS
    ctx_data = {
        **data,
        "created_at": datetime.now().isoformat()
    }
    context.write_context_file(ctx_data)
    
    return context

class RunContext:
    def __init__(self, submission_id, run_id, repo_url, gcs):
        self.submission_id = submission_id
        self.run_id = run_id
        self.repo_url = repo_url
        self.gcs = gcs
        self.repo_name = repo_url.split("/")[-1]

    # GCS Path Definitions
    def project_root(self):
        return f"workspaces/{self.submission_id}"

    def logs_path(self):
        return f"{self.project_root()}/logs"

    def summary_path(self):
        return f"{self.project_root()}/summary.json"

    def actor_summary_path(self):
        return f"{self.project_root()}/actor-summary.json"

    def simulation_path(self):
        return f"{self.project_root()}/simulations.json"

    def write_context_file(self, data):
        """Write context metadata to GCS"""
        self.gcs.write_json(f"{self.project_root()}/context.json", data)

    def initialize_run_log(self):
        """Create initial run log in GCS"""
        self.gcs.write_json(f"{self.logs_path()}/init.log", {
            "status": "started",
            "timestamp": datetime.now().isoformat()
        })