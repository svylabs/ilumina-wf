import logging
import os
import subprocess
import json
from datetime import datetime, timezone
from .context import RunContext
from .actor import ActorAnalyzer
from .download import Downloader
from .summarizer import ProjectSummarizer
from .models import Project
from .simulation import SimulationEngine
from .deployer import ContractDeployer
from .git_utils import GitUtils
from .github import GitHubAPI

logger = logging.getLogger(__name__)

class Analyzer:
    STEPS = [
        "download",
        "summarize_project",
        "analyze_actors",
        "setup_simulation_environment",
        "compile_contracts",
        "run_simulations"
    ]

    def __init__(self, context):
        self.context = context
        self.current_step_index = 0
        self.results = {}
        self.simulation_repo_path = f"/tmp/simulation_{self.context.submission_id}"

    def has_next_step(self):
        return self.current_step_index < len(self.STEPS)
    
    def execute_next_step(self):
        step = self.STEPS[self.current_step_index]
        
        if step == "download":
            self.download_repository()
        elif step == "summarize_project":
            self.summarize_project()
        elif step == "analyze_actors":
            self.analyze_actors()
        elif step == "setup_simulation_environment":
            self.setup_simulation_environment()
        elif step == "compile_contracts":
            self.compile_contracts()
        elif step == "run_simulations":
            self.run_simulations()
        
        self.current_step_index += 1

    def download_repository(self):
        downloader = Downloader(self.context)
        downloader.download()
        self.results["download"] = {"status": "success"}

    def summarize_project(self):
        summarizer = ProjectSummarizer(self.context)
        summarizer.summarize()
        self.results["project_summary"] = summarizer.project_summary.to_dict()

    def analyze_actors(self):
        project_summary = Project(**self.results["project_summary"])
        actor_analyzer = ActorAnalyzer(self.context, project_summary)
        actors = actor_analyzer.analyze()
        self.results["actor_analysis"] = actors.to_dict()

    def setup_simulation_environment(self):
        """Setup simulation environment"""
        try:
            # 1. Git clone template
            self._clone_simulation_template()
            
            # 2. npm install
            self._install_simulation_dependencies()
            
            # 3. Set git origin
            self._setup_simulation_git_origin()
            
            # 4. Git push
            self._push_simulation_to_origin()
            
            self.results["simulation_setup"] = {"status": "completed"}
            
        except Exception as e:
            logger.error(f"Simulation setup failed: {str(e)}")
            self.results["simulation_setup"] = {
                "status": "failed",
                "error": str(e)
            }
            raise

    def compile_contracts(self):
        """Compile project contracts"""
        try:
            deployer = ContractDeployer(self.context)
            compiled_data = deployer.compile_contracts()
            
            self.results["compilation"] = {
                "status": "completed",
                "compiler": compiled_data["compiler"],
                "contracts": list(compiled_data["contracts"].keys()),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            # Store full compilation details
            self.context.gcs.write_json(
                f"{self.context.project_root()}/compilation.json",
                compiled_data
            )
            
        except Exception as e:
            logger.error(f"Contract compilation failed: {str(e)}")
            self.results["compilation"] = {
                "status": "failed",
                "error": str(e)
            }
            raise

    def run_simulations(self):
        """Run simulations after both steps complete"""
        if (self.results.get("simulation_setup", {}).get("status") == "completed" and
            self.results.get("compilation", {}).get("status") == "completed"):
            
            # Copy compiled contracts to simulation repo
            compiled_data = self.context.gcs.read_json(
                f"{self.context.project_root()}/compilation.json"
            )
            self._setup_simulation_contracts(compiled_data)
            
            # Run simulations
            simulation = SimulationEngine(self.context)
            results = simulation.run()
            self.results["simulations"] = results

    def _clone_simulation_template(self):
        """Clone simulation template repository"""
        template_repo = os.getenv(
            "SIMULATION_TEMPLATE_REPO",
            "https://github.com/svylabs-com/ilumina-scaffolded-template.git"
        )
        
        GitUtils.clone_repository(
            template_repo,
            self.simulation_repo_path
        )
        self.results["simulation_setup"] = {"clone": "completed"}

    def _install_simulation_dependencies(self):
        """Install npm dependencies for simulation"""
        result = subprocess.run(
            ["npm", "install"],
            cwd=self.simulation_repo_path,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"npm install failed: {result.stderr}")
        
        self.results["simulation_setup"]["dependencies"] = "installed"

    def _setup_simulation_git_origin(self):
        """Create new repo and set origin"""
        repo_name = f"{self.context.repo_name}-simulation"
        repo_data = GitHubAPI().create_repository(
            name=repo_name,
            private=True,
            description=f"Simulation for {self.context.repo_name}"
        )
        
        subprocess.run(
            ["git", "remote", "add", "origin", repo_data["clone_url"]],
            cwd=self.simulation_repo_path,
            check=True
        )
        self.simulation_repo_url = repo_data["clone_url"]
        self.results["simulation_setup"]["git_origin"] = "configured"

    def _push_simulation_to_origin(self):
        """Push simulation code to new repository"""
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=self.simulation_repo_path,
            check=True
        )
        self.results["simulation_setup"]["push"] = "completed"

    def _setup_simulation_contracts(self, compiled_data):
        """Setup contracts in simulation environment"""
        contracts_dir = os.path.join(self.simulation_repo_path, "contracts")
        os.makedirs(contracts_dir, exist_ok=True)
        
        # Write ABIs to simulation repo
        for contract_name, data in compiled_data["contracts"].items():
            with open(os.path.join(contracts_dir, f"{contract_name}.json"), "w") as f:
                json.dump({
                    "abi": data["abi"],
                    "bytecode": data["bytecode"]
                }, f)

    def save_progress(self):
        """Save current progress to GCS"""
        self.context.gcs.write_json(
            f"{self.context.project_root()}/results.json",
            self.results
        )
        
        self.context.gcs.write_json(
            f"{self.context.logs_path()}/progress.json",
            {
                "current_step": self.STEPS[self.current_step_index] if self.current_step_index < len(self.STEPS) else "completed",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )