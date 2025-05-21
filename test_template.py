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

# Test the contract_snapshot_provider.ts.j2 template
contract_snapshot_provider = env.get_template('contract_snapshot_provider.ts.j2')
contracts = ["Token", "LendingPool"]
output = contract_snapshot_provider.render(contracts=contracts)

with open("test_contract_snapshot_provider.ts", "w") as f:
    f.write(output)

print("Generated test_contract_snapshot_provider.ts from contract_snapshot_provider.ts.j2 with contracts:", contracts)
print("\n--- Preview of generated file ---\n")
with open("test_contract_snapshot_provider.ts") as f:
    print(f.read())