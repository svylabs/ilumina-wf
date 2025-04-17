import re
from pathlib import Path

def find_object_bounds(content: str, start_pattern: str) -> tuple[int, int]:
    """Find the start and end bounds of an object like config = { ... }"""
    pattern = re.compile(start_pattern)
    match = pattern.search(content)
    if not match:
        return -1, -1

    start = match.start()
    i = match.end() - 1
    brace_count = 0

    while i < len(content):
        if content[i] == '{':
            brace_count += 1
        elif content[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                return start, i + 1
        i += 1
    return -1, -1

def parse_and_modify_hardhat_config(config_path: str, new_networks_config: str) -> tuple[Path, str]:
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"{config_path} does not exist.")

    content = config_file.read_text()

    # Extract Solidity version
    solidity_version_match = re.search(
        r"solidity\s*:\s*(?:\{[^}]*version\s*:\s*[\"'](\d+\.\d+\.\d+)[\"'])|[\"'](\d+\.\d+\.\d+)[\"']",
        content,
        re.DOTALL
    )
    solidity_version = solidity_version_match.group(1) or solidity_version_match.group(2) if solidity_version_match else None

    # Try to find and replace existing networks
    networks_bounds = find_object_bounds(content, r"networks\s*:\s*\{")
    if networks_bounds != (-1, -1):
        start, end = networks_bounds
        content_modified = content[:start] + f"networks: {new_networks_config}" + content[end:]
    else:
        # Try module.exports = {
        if "module.exports" in content:
            content_modified = re.sub(
                r"(module\.exports\s*=\s*\{)",
                rf"\1\n  networks: {new_networks_config},",
                content,
                flags=re.DOTALL
            )
        # Try export default { }
        elif re.search(r"export\s+default\s+\{", content):
            content_modified = re.sub(
                r"(export\s+default\s+\{)",
                rf"\1\n  networks: {new_networks_config},",
                content,
                flags=re.DOTALL
            )
        # Try named config object: const config = {
        elif re.search(r"const\s+config\s*:\s*HardhatUserConfig\s*=\s*\{", content):
            start, end = find_object_bounds(content, r"const\s+config\s*:\s*HardhatUserConfig\s*=\s*\{")
            if start == -1 or end == -1:
                raise ValueError("Could not find config object bounds.")

            insert_point = end - 1
            # Check if the last non-whitespace character before the closing brace is a comma
            before_closing = content[:insert_point].rstrip()
            needs_comma = not before_closing.endswith(',')

            insertion = (",\n  " if needs_comma else "\n  ") + f"networks: {new_networks_config}"
            content_modified = content[:insert_point] + insertion + content[insert_point:]

        else:
            raise ValueError("Could not find a suitable config object or export to modify.")
        
    config_name = f"hardhat.config.simulation{config_file.suffix}"

    # Write to new file
    output_path = config_file.with_name(config_name)
    output_path.write_text(content_modified)
    return output_path, config_name
    #return content_modified

hardhat_network = """
{
    hardhat: {
        accounts: {
            count: 500, // Adjust this number for hundreds of accounts
            accountsBalance: "1000000000000000000000" // 1000 ETH per account
        }
    }
}
"""


if __name__ == "__main__":
    # Example usage
    config_path = "/Users/sg/Documents/workspace/svylabs/stablebase/hardhat.config.js"  # Path to your Hardhat config file
    new_networks_config = hardhat_network  # New networks configuration
    
    result = parse_and_modify_hardhat_config(config_path, new_networks_config)
    print(result)
