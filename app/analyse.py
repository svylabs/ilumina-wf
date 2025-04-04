from .context import RunContext
from .actor import ActorAnalyzer
from .download import Downloader
from .summarizer import ProjectSummarizer
from .models import Project
from .simulation import SimulationEngine
from .deployer import ContractDeployer
import datetime

class Analyzer:
    STEPS = [
        "download",
        "summarize_project",
        "analyze_actors",
        "setup_environment",
        "run_simulations",
        "compile_contracts",
        "deploy_contracts"
    ]

    def __init__(self, context):
        self.context = context
        self.current_step_index = 0
        self.results = {}

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
        elif step == "setup_environment":
            self.setup_test_environment()
        elif step == "run_simulations":
            self.run_simulations()
        elif step == "compile_contracts":
            self.compile_contracts()
        elif step == "deploy_contracts":
            self.deploy_contracts()
        
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

    def setup_test_environment(self):
        self.results["test_environment"] = {
            "status": "configured",
            "tools": ["hardhat", "ganache"],
            "networks": ["localhost", "sepolia"]
        }

    def run_simulations(self):
        simulation = SimulationEngine(self.context)
        results = simulation.run()
        self.results["simulations"] = results

    def compile_contracts(self):
        """Compile smart contracts and store ABIs"""
        deployer = ContractDeployer(self.context)
        compiled_data = deployer.compile_contracts()
        self.results["compilation"] = {
            "status": "completed",
            "compiler": compiled_data["compiler"],
            "contracts": list(compiled_data["contracts"].keys()),
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        # Store full compilation details separately
        self.context.gcs.write_json(
            f"{self.context.project_root()}/compilation.json",
            compiled_data
        )

    def deploy_contracts(self):
        """Deploy compiled contracts to blockchain"""
        # Load compilation results
        compiled_data = self.context.gcs.read_json(
            f"{self.context.project_root()}/compilation.json"
        )
        
        deployer = ContractDeployer(self.context)
        deployment_data = deployer.deploy_contracts(compiled_data, "sepolia")
        
        self.results["deployment"] = {
            "status": "completed",
            "network": "sepolia",
            "deployed_contracts": deployment_data["deployed_contracts"],
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        # Store full deployment details separately
        deployer.save_deployment_results(deployment_data)

    def save_progress(self):
        step = self.STEPS[self.current_step_index]
        log_file = f"{self.context.logs_path()}/{step}.json"
        self.context.gcs.write_json(log_file, self.results.get(step, {}))
        
        # Save complete results
        self.context.gcs.write_json(
            f"{self.context.project_root()}/results.json",
            self.results
        )
        
        # Save context with current step
        context_data = {
            "current_step": step,
            "current_step_index": self.current_step_index,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        self.context.gcs.write_json(
            f"{self.context.project_root()}/progress.json",
            context_data
        )