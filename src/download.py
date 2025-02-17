#!/usr/bin/env python3
import subprocess as process
import os

class Git:
    cwd = "/tmp/workspaces"

    def __init__(self, run_id):
        self.run_id = run_id
        if (os.path.exists(self.cwd) == False):
            process.run(["mkdir", self.cwd])

    def convert_url(self, url):
        # Convert the URL to SSH
        parts = url.split("https://github.com/")
        return "git@github.com:" + parts[1] + ".git"


    def clone(self, url):
        # Clone the repository
        #git@github.com:svylabs/predify.git
        ssh_url = self.convert_url(url)
        print(ssh_url)
        process.run(["mkdir", str(self.run_id)], cwd=self.cwd)
        process.run(["git", "clone", ssh_url], cwd=self.cwd + "/" + str(self.run_id))
        pass

if __name__ == "__main__":
    git = Git("1")
    git.clone("https://github.com/svylabs/predify")