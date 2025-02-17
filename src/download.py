#!/usr/bin/env python3
import subprocess as process
import os
from lib.context import RunContext, example_contexts

class Git:

    def __init__(self, run_context):
        self.context = run_context
        self.run_id = self.context.run_id
        if (os.path.exists(self.context.cwd()) == False):
            process.run(["mkdir", self.context.cwd()])

    def convert_url(self, url):
        # Convert the URL to SSH
        parts = url.split("https://github.com/")
        return "git@github.com:" + parts[1] + ".git"


    def clone(self):
        # Clone the repository
        #git@github.com:svylabs/predify.git
        ssh_url = self.convert_url(self.context.repo)
        print(ssh_url)
        #process.run(["mkdir", str(self.run_id)], cwd=self.cwd)
        process.run(["git", "clone", ssh_url], cwd=self.context.cwd())
        pass

if __name__ == "__main__":
    git = Git(example_contexts[0])
    git.clone()