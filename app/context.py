import os
import json
import uuid
from .github_utils import create_github_repo, set_github_repo_origin_and_push
from .filesystem_utils import ensure_directory_exists, clone_repo

APP_VERSION = "v1"

def prepare_context(data):
    run_id = data["run_id"]
    submission_id = data["submission_id"]
    repo = data["github_repository_url"]
    workspace = "/tmp/workspaces"
    context = RunContext(submission_id, run_id, repo, workspace)

    # Ensure the root workspace exists
    ensure_directory_exists(workspace)

    # Create a project directory if it doesn't exist
    project_dir = os.path.join(workspace, context.name)
    ensure_directory_exists(project_dir)

    # Clone the project repo into the project directory if not already cloned
    project_repo_path = os.path.join(project_dir, context.name)
    clone_repo(repo, project_repo_path)
    # compile the project

    # Clone the simulation repo into the project directory if not already cloned
    simulation_repo_name = f"{context.name}-simulation"
    simulation_repo_path = os.path.join(project_dir, simulation_repo_name)
    simulation_template_repo = os.getenv(
        "SIMULATION_TEMPLATE_REPO",
        "https://github.com/svylabs-com/ilumina-scaffolded-template.git"
    )
    clone_repo(simulation_template_repo, simulation_repo_path)

    # Create a private GitHub repository for the simulation repo if it doesn't already exist
    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB")
    if not github_token or not github_username:
        raise Exception("GitHub credentials are not set in the environment variables")

    repo_name = simulation_repo_name
    github_repo_url = f"https://github.com/{github_username}/{repo_name}.git"
    create_github_repo(github_token, github_username, repo_name)

    # Set the origin of the simulation repo to the GitHub repo and push if not already set
    set_github_repo_origin_and_push(simulation_repo_path, github_repo_url)

    return context

class RunContext:
    def __init__(self, submission_id, run_id, repo, workspace):
        self.submission_id = submission_id
        self.run_id = run_id
        self.repo = repo
        self.workspace = workspace
        self.name = repo.split("/")[-1]
        if (os.path.exists(self.cwd()) == False):
            os.makedirs(self.cwd())

    def get_run_id(self):
        return self.run_id

    def cwd(self):
        return self.workspace + "/" + self.run_id

    def cws(self):
        return self.cwd() + "/" + self.name
    
    def ctx_path(self):
        return self.cwd() + "/context.json"
    
    def summary_path(self):
        return self.cwd() + "/summary.json"
    
    def actor_summary_path(self):
        return self.cwd() + "/actor_summary.json"
    
example_contexts = [
    RunContext("s1", "1", "https://github.com/svylabs/predify", "/tmp/workspaces"),
    RunContext("s2", "2", "https://github.com/svylabs/stablebase", "/tmp/workspaces")
]
