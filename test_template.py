from jinja2 import FileSystemLoader, Environment

scaffold_templates = FileSystemLoader('scaffold')
env = Environment(loader=scaffold_templates)

action = env.get_template('action.ts.j2')
print(action.render(
    action_name="Borrow"
))

actor = env.get_template('actor.ts.j2')
print(actor.render(
    actor={
        "name": "Borrower",
        "actions": [
            {
                "name": "Borrow",
                "file_name": "borrow.ts",
                "probability": 0.7
            },
            {
                "name": "Repay",
                "file_name": "repay.ts",
                "probability": 0.3
            }
        ]
    }
))