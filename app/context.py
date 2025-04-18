import os
import glob
import uuid
import subprocess
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

    # Clone the main repository
    clone_repo(repo, context.cws())

    # Install dependencies for MAIN project
    try:
        # First clean install from lockfile if exists
        if os.path.exists(os.path.join(context.cws(), 'package-lock.json')):
            subprocess.run(["npm", "ci", "--legacy-peer-deps"],
                         cwd=context.cws(),
                         check=True,
                         capture_output=True,
                         text=True)
        else:
            # Full install with explicit required packages
            subprocess.run(
                ["npm", "install", "--legacy-peer-deps",
                 "hardhat@^2.12.0",
                 "@nomicfoundation/hardhat-toolbox@^2.0.0",
                 "ethers@^5.7.2",
                 "typescript@^4.9.5",
                 "ts-node@^10.9.1"],
                cwd=context.cws(),
                check=True,
                capture_output=True,
                text=True
            )
    except subprocess.CalledProcessError as e:
        raise Exception(f"Main project dependency installation failed:\n{e.stderr}")

    # Clone the simulation repo into the project directory if not already cloned
    simulation_repo_name = f"{context.name}-simulation-" + run_id
    simulation_repo_path = context.simulation_path()
    simulation_template_repo = os.getenv(
        "SIMULATION_TEMPLATE_REPO",
        "git@github.com:svylabs-com/ilumina-scaffolded-template.git"
    )
    clone_repo(simulation_template_repo, simulation_repo_path)

    # Install dependencies for SIMULATION project
    try:
        # First try clean install
        subprocess.run(["npm", "ci", "--legacy-peer-deps"],
                     cwd=simulation_repo_path,
                     check=True,
                     capture_output=True,
                     text=True)
        
        # Verify critical packages are installed
        verify_packages = ["hardhat", "ethers", "@nomicfoundation/hardhat-toolbox"]
        for pkg in verify_packages:
            subprocess.run(["npm", "ls", pkg],
                         cwd=simulation_repo_path,
                         check=True,
                         capture_output=True,
                         text=True)
    except subprocess.CalledProcessError as e:
        # Fallback to full install if clean install fails
        try:
            subprocess.run(
                ["npm", "install", "--legacy-peer-deps",
                 "hardhat@^2.12.0",
                 "@nomicfoundation/hardhat-toolbox@^2.0.0",
                 "ethers@^5.7.2",
                 "typescript@^4.9.5",
                 "ts-node@^10.9.1"],
                cwd=simulation_repo_path,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as fallback_error:
            raise Exception(
                f"Simulation dependency installation failed:\n"
                f"Initial error: {e.stderr}\n"
                f"Fallback error: {fallback_error.stderr}"
            )

    # Create a private GitHub repository for the simulation repo if it doesn't already exist
    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB_USERNAME")
    if not github_token or not github_username:
        raise Exception("GitHub credentials are not set in the environment variables")

    repo_name = simulation_repo_name
    github_repo_url = f"git@github.com:{github_username}/{repo_name}.git"
    create_github_repo(github_token, github_username, repo_name)

    # Set the origin of the simulation repo to the GitHub repo and push if not already set
    set_github_repo_origin_and_push(simulation_repo_path, github_repo_url)

    return context

def prepare_context_lazy(data):
    run_id = data["run_id"]
    submission_id = data["submission_id"]
    repo = data["github_repository_url"]
    workspace = "/tmp/workspaces"
    context = RunContext(submission_id, run_id, repo, workspace)

    return context
 
class RunContext:
    def __init__(self, submission_id, run_id, repo, workspace, metadata=None):
        self.submission_id = submission_id
        self.run_id = run_id
        self.repo = repo
        self.workspace = workspace
        self.name = repo.split("/")[-1]
        self.metadata = metadata if metadata else {}
        if (os.path.exists(self.cwd()) == False):
            os.makedirs(self.cwd())

    def get_run_id(self):
        return self.run_id

    def cwd(self):
        return self.workspace + "/" + self.submission_id

    def cws(self):
        return self.cwd() + "/" + self.name
    
    def simulation_path(self):
        return self.cwd() + "/" + self.name + "-simulation-" + self.run_id
    
    def ctx_path(self):
        return self.cwd() + "/context.json"
    
    def summary_path(self):
        return self.simulation_path() + "/summary.json"
    
    def actor_summary_path(self):
        return self.simulation_path() + "/actor_summary.json"
    
    def compiled_contracts_path(self):
        """Returns path to compiled contracts JSON file"""
        return os.path.join(self.cws(), "artifacts/compiled_contracts.json")
    
    # def contract_artifact_path(self, contract_name):
    #     """Returns path to individual contract artifact"""
    #     return os.path.join(self.cws(), f"artifacts/contracts/{contract_name}.sol/{contract_name}.json")

    def contract_artifact_path(self, contract_name):
        """Returns path to individual contract artifact by searching recursively"""
        artifacts_root = os.path.join(self.cws(), "artifacts")
        
        # Possible file patterns to search for
        patterns = [
            f"**/{contract_name}.sol/{contract_name}.json",  # Standard Hardhat structure
            f"**/{contract_name}.json",  # Fallback - direct artifact
            f"**/dependencies/**/{contract_name}.sol/{contract_name}.json",  # Dependencies
            f"**/lib/**/{contract_name}.sol/{contract_name}.json",  # Libraries
        ]
        
        for pattern in patterns:
            for match in glob.glob(os.path.join(artifacts_root, pattern), recursive=True):
                if os.path.exists(match):
                    return match
        
        # If not found, try flattened path as last resort
        flattened_path = os.path.join(self.cws(), "artifacts", f"{contract_name}.json")
        if os.path.exists(flattened_path):
            return flattened_path
        
        raise FileNotFoundError(f"Could not find artifact for contract {contract_name} in {artifacts_root}")
    
    def new_gcs_summary_path(self):
        version = str(uuid.uuid4())
        return version, f"summaries/{self.submission_id}/project_summary/{version}.json"
    
    def new_gcs_actor_summary_path(self):
        version = str(uuid.uuid4())
        return version, f"summaries/{self.submission_id}/actor_summary/{version}.json"
    
    def new_gcs_deployment_instructions_path(self):
        version = str(uuid.uuid4())
        return version, f"summaries/{self.submission_id}/deployment_instructions/{version}.json"
    
    def gcs_summary_path_from_version(self, version):
        return f"summaries/{self.submission_id}/project_summary/{version}.json"
    
    def gcs_actor_summary_path_from_version(self, version):
        return f"summaries/{self.submission_id}/actor_summary/{version}.json"
    
    def gcs_deployment_instructions_path_from_version(self, version):
        return f"summaries/{self.submission_id}/deployment_instructions/{version}.json"
    
    def deployment_instructions_path(self):
        return self.simulation_path() + "/deployment_instructions.json"
    
    # def commit(self, message):
    #     command = "cd " + self.simulation_path() + f" && git add . && git commit -m '{message}' && git push"
    #     ret_val = os.system(command)
    #     if ret_val != 0:
    #         raise Exception("Failed to commit changes to the simulation repo")
    
    def commit(self, message):
        simulation_path = self.simulation_path()
        try:
            # Check for changes
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=simulation_path,
                stdout=subprocess.PIPE,
                text=True
            )
            if not result.stdout.strip():
                print("No changes to commit in the simulation repo.")
                return
            # Add, commit, push
            subprocess.run(["git", "add", "."], cwd=simulation_path, check=True)
            subprocess.run(["git", "commit", "-m", message], cwd=simulation_path, check=True)
            subprocess.run(["git", "push"], cwd=simulation_path, check=True)
        except subprocess.CalledProcessError as e:
            raise Exception(f"Git command failed: {e}")
        except Exception as e:
            raise Exception(f"Failed to commit changes to the simulation repo: {e}")
    
example_contexts = [
    RunContext("s1", "1", "https://github.com/svylabs/predify", "/tmp/workspaces"),
    RunContext("s2", "2", "https://github.com/svylabs/stablebase", "/tmp/workspaces")
]
