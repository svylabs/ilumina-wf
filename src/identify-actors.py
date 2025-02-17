from lib.context import RunContext, example_contexts
from lib.lib import Project
from lib.openai import ask_openai
import json

class Action:
    name: str
    summary: str
    contract: str
    function_name: str
    probability: float

class Actor:
    name: str
    summary: str
    actions: list[Action]

class ActorAnalyzer:
    
    def __init__(self, context):
        self.context = context
        self.project_summary = None

    def analyze(self):
        self.prepare()
        print("Analyzing actors for the contracts")

    def save(self):
        with open(self.context.cws() + "/summary.json", "w") as f:
            f.write(json.dumps(self.project_summary.to_dict()))

    def load_summary(self):
        if (os.path.exists(self.context.summary_path())):
            with open(self.context.summary_path(), "r") as f:
                content = json.loads(f.read())
                #print(json.dumps(content))
                return Project.load(content)
        return None
    
    def analysis_exists(self):
        return os.path.exists(self.context.cws() + "/summary.json")

if __name__ == "__main__":
    context = example_contexts[0]
    summary = Project.load_summary(context.summary_path())
    print(summary.summary)


