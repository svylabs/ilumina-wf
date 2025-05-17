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

actors = env.get_template('actors.ts.j2')
print(actors.render(
    actors=[
        {
            "name": "Borrower",
            "file_name": "borrower.ts",
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
        },
        {
            "name": "Lender",
            "file_name": "lender.ts",
            "actions": [
                {
                    "name": "Lend",
                    "file_name": "lend.ts",
                    "probability": 0.5
                },
                {
                    "name": "Withdraw",
                    "file_name": "withdraw.ts",
                    "probability": 0.5
                }
            ]
        }
    ]
))