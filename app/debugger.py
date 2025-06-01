from .context import RunContext
class Debugger:
    def __init__(self, context: RunContext):
        self.context  = context

    def debug(self):
        """
           Build a debugging context: 
             - error messages
             - simulation repo tree
           Debugging flow:
            - Ask LLM to analyze repo tree and error message and ask LLM what file it needs to debug the error.
             - Based on the file, provide LLM with file content and context how it was generated.
             - Ask LLM to generate a fix for the error.
             - Apply the fix to the file.
             - Commit
             - Run the tests again.

            Define models:
                - DebuggingContext
                    - error_message
                    - repo_tree: dict
                    
                - DebugResponse
                    - possible_problems: list[str]
                    - possible_fixes: list[str]
                    - files_requested: list[str]

                - AdditionalDebuggingContext
                    - files: list[FileContent]

                - FileContent
                    - file_path: str
                    - content: str
                    - generation_context: str

                - FileFix
                    - file_path: str
                    - fixs: list[str]

                - Fixes
                    fixes: list[FileFix]
                

        """
        pass