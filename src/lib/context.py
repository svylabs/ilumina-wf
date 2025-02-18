class RunContext:
    def __init__(self, run_id, repo, workspace):
        self.run_id = run_id
        self.repo = repo
        self.workspace = workspace
        self.name = repo.split("/")[-1]

    def get_run_id(self):
        return self.run_id

    def cwd(self):
        return self.workspace + "/" + self.run_id

    def cws(self):
        return self.cwd() + "/" + self.name
    
    def summary_path(self):
        return self.cws() + "/summary.json"
    
    def actor_summary_path(self):
        return self.cws() + "/actor_summary.json"
    
example_contexts = [
    RunContext("1", "https://github.com/svylabs/predify", "/tmp/workspaces"),
    RunContext("2", "https://github.com/svylabs/stablebase", "/tmp/workspaces")
]
