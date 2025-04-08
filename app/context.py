
import os
import json
import uuid

APP_VERSION = "v1"

def prepare_context(data):
    run_id = data["run_id"]
    submission_id = data["submission_id"]
    repo = data["github_repository_url"]
    workspace = "/tmp/workspaces"
    context = RunContext(submission_id, run_id, repo, workspace)

    # TODO: Modify this to create the following
    # 1. Create a new repo from the template (if not available already)
    # 2. Create a private github repo
    # 2. Push the repo to github
    if (os.path.exists(context.ctx_path()) == False): 
        with open(context.ctx_path(), "w") as f:
            ctx_data = data
            ctx_data["version"] = APP_VERSION
            f.write(json.dumps(ctx_data))
    else:
        with open(context.ctx_path(), "r") as f:
            data = json.loads(f.read())
            if (data["version"] != APP_VERSION):
                raise Exception("Version mismatch")
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
