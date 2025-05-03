import os
import glob
import uuid
import subprocess
from .github_utils import create_github_repo, set_github_repo_origin_and_push
from .filesystem_utils import ensure_directory_exists, clone_repo
from .models import Project, Actors
from .hardhat_config import parse_and_modify_hardhat_config, hardhat_network

APP_VERSION = "v1"

def _extract_error_details(stderr, stdout):
    """Extract meaningful error details from deployment output"""
    error_lines = []
    for line in (stderr + stdout).split('\n'):
        if 'error' in line.lower() or 'fail' in line.lower():
            error_lines.append(line.strip())
    return '\n'.join(error_lines[-5:]) if error_lines else "Unknown deployment error"


def compile_contracts(context):
    contract_path = context.cws()
    simulation_path = context.simulation_path()
    print(f"Simulation path: {simulation_path}")
    print(f"Contract path: {contract_path}")
        
    # Verify contract directory exists
    if not os.path.exists(contract_path):
        raise FileNotFoundError(f"Contract directory not found at {contract_path}")
    

    hardhat_config_path = os.path.join(contract_path, "hardhat.config.js")
    hardhat_config_path_ts = os.path.join(contract_path, "hardhat.config.ts")
    simulation_config = "hardhat.config.simulation.js"
    if os.path.exists(hardhat_config_path):
        _,simulation_config = parse_and_modify_hardhat_config(hardhat_config_path, hardhat_network)
    if os.path.exists(hardhat_config_path_ts):
        _,simulation_config = parse_and_modify_hardhat_config(hardhat_config_path_ts, hardhat_network)

    # 1. Install dependencies with --legacy-peer-deps to resolve conflicts
    install_command = f"cd {contract_path} && npm install --legacy-peer-deps"
    # install_command = (
    #     f"cd {contract_path} && "
    #     "npm install --save-dev ts-node typescript @typechain/hardhat @nomicfoundation/hardhat-toolbox "
    #     "@nomicfoundation/hardhat-ethers ethers && "
    #     "npm install --legacy-peer-deps"
    # )
    install_process = subprocess.Popen(
        install_command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )
    install_stdout, install_stderr = install_process.communicate(timeout=300)  # 5 minute timeout
    
    if install_process.returncode != 0:
        raise RuntimeError(f"Dependency installation failed: {_extract_error_details(install_stderr, install_stdout)}")

    # 2. Compile the contracts
    # compile_command = f"cd {contract_path} && npx hardhat compile"
    compile_command = f"cd {contract_path} && npx hardhat compile --config {simulation_config}"
    compile_process = subprocess.Popen(
        compile_command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )
    compile_stdout, compile_stderr = compile_process.communicate(timeout=300)
    
    if compile_process.returncode != 0:
        raise RuntimeError(f"Contract compilation failed: {_extract_error_details(compile_stderr, compile_stdout)}")

        

def prepare_context(data, optimize=True):
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
    # Create a private GitHub repository for the simulation repo if it doesn't already exist
    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB_USERNAME")
    if not github_token or not github_username:
        raise Exception("GitHub credentials are not set in the environment variables")

    repo_name = simulation_repo_name
    github_repo_url = f"git@github.com:{github_username}/{repo_name}.git"
    already_exists = create_github_repo(github_token, github_username, repo_name)
    if already_exists:
        clone_repo(github_repo_url, simulation_repo_path)
    else:
        clone_repo(simulation_template_repo, simulation_repo_path)

    # Install dependencies for SIMULATION project
    try:
        # First try clean install
        subprocess.run(["npm", "ci", "--legacy-peer-deps"],
                     cwd=simulation_repo_path,
                     check=True,
                     capture_output=True,
                     text=True)

    except subprocess.CalledProcessError as e:
        # Fallback to full install if clean install fails
        subprocess.run(
            ["npm", "install", "--legacy-peer-deps"],
            cwd=simulation_repo_path,
            check=True,
            capture_output=True,
            text=True
        )

    # Set the origin of the simulation repo to the GitHub repo and push if not already set
    set_github_repo_origin_and_push(simulation_repo_path, github_repo_url)

    # Compile the contracts to generate ABIs
    if optimize == False:
        compile_contracts(context)

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
    
    def contract_artifact_path(self, contract_name):
        """Search for any JSON file containing the contract name in artifacts/contracts."""
        artifacts_root = os.path.join(self.cws(), "artifacts/contracts")
        if not os.path.exists(artifacts_root):
            raise FileNotFoundError(f"Artifacts directory not found: {artifacts_root}")

        # Search for JSON files containing the contract name
        for root, _, files in os.walk(artifacts_root):
            for file in files:
                # if file.endswith(".json"):
                if file.endswith(".json") and not file.endswith(".dbg.json") and not file.endswith(".metadata.json"):
                    file_path = os.path.join(root, file)
                    # print(f"Found JSON file in context: {file_path}")  # Print the JSON file path
                    if contract_name in file:
                        return file_path

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
        

    def project_summary(self):
        return Project.load_summary(self.summary_path())
        
    def actor_summary(self):
        return Actors.load_summary(self.actor_summary_path())

    
example_contexts = [
    RunContext("s1", "1", "https://github.com/svylabs/predify", "/tmp/workspaces"),
    RunContext("s2", "2", "https://github.com/svylabs/stablebase", "/tmp/workspaces")
]
