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
    project_dir = context.cwd()
    ensure_directory_exists(project_dir)

    clone_repo(repo, context.cws())
    # compile the project

    # Clone the simulation repo into the project directory if not already cloned
    simulation_repo_name = f"{context.name}-simulation"
    simulation_repo_path = context.simulation_path()
    simulation_template_repo = os.getenv(
        "SIMULATION_TEMPLATE_REPO",
        "https://github.com/svylabs-com/ilumina-scaffolded-template.git"
    )
    clone_repo(simulation_template_repo, simulation_repo_path)

    # Create a private GitHub repository for the simulation repo if it doesn't already exist
    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB_USERNAME")
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
        return self.workspace + "/" + self.submission_id

    def cws(self):
        return self.cwd() + "/" + self.name
    
    def simulation_path(self):
        return self.cwd() + "/" + self.name + "-simulation"
    
    def ctx_path(self):
        return self.cwd() + "/context.json"
    
    def summary_path(self):
        return self.simulation_path() + "/summary.json"
    
    def actor_summary_path(self):
        return self.simulation_path() + "/actor_summary.json"
    
    def commit(self, message):
        command = "cd " + self.simulation_path() + f" && git add . && git commit -m '{message}' && git push"
        ret_val = os.system(command)
        if ret_val != 0:
            raise Exception("Failed to commit changes to the simulation repo")
    
example_contexts = [
    RunContext("s1", "1", "https://github.com/svylabs/predify", "/tmp/workspaces"),
    RunContext("s2", "2", "https://github.com/svylabs/stablebase", "/tmp/workspaces")
]
