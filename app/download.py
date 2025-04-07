#!/usr/bin/env python3
import subprocess as process
import os
from app.context import RunContext, example_contexts
import sys
import shutil

class Downloader:

    def __init__(self, run_context):
        self.context = run_context
        self.run_id = self.context.run_id

    def convert_url(self, url):
        # Convert the URL to SSH
        parts = url.split("https://github.com/")
        return "git@github.com:" + parts[1] + ".git"
    

    def cleanup(self):
        try:
            shutil.rmtree(self.context.cws())
        except Exception as e:
            print(f"Cleanup warning: {str(e)}")


    def download(self):
        # Clone the repository
        #git@github.com:svylabs/predify.git
        if (os.path.exists(self.context.cws())):
            print("Workspace already exists")
            return
        ssh_url = self.convert_url(self.context.repo)
        print(ssh_url)
        #process.run(["mkdir", str(self.run_id)], cwd=self.cwd)
        process.run(["git", "clone", ssh_url], cwd=self.context.cwd())

if __name__ == "__main__":
    context_num = 0
    try:
        context_num = int(sys.argv[1])
    except:
        pass
    downloader = Downloader(example_contexts[context_num])
    downloader.download()