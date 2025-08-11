import os
import re
import subprocess
import sys  # Added import for sys module
import shutil
from argparse import Namespace
from pathlib import Path

from colorama import Fore, Style

class BLIError(Exception):
    """Custom exception class for BLI errors."""
    pass

def interpret_pulumi_error(error_text: str) -> str:
    """Convert Pulumi errors into BLI-specific error messages."""
    # Map of regex patterns to user-friendly messages
    error_mappings = [
        # Login errors
        (r"error: could not unmarshal.*Configuration key '(.+)' is not namespaced", 
         "Invalid configuration in Pulumi.yaml. Configuration keys must be properly namespaced."),
        (r"error: no stack selected", 
         "No Pulumi stack is selected. Run 'bli init -s <stack-name>' to create and select a stack."),
        (r"error: could not log in.*", 
         "Failed to log in to Pulumi backend. Check your network connection and Pulumi CLI installation."),
        # Stack errors
        (r"error: stack '(.+)' already exists", 
         "Stack already exists. Use a different stack name or run commands on the existing stack."),
        (r"error: failed to create stack: (.+)", 
         "Stack creation failed. Make sure you have the right permissions and valid stack name."),
        # General errors
        (r"error: no project file found in", 
         "No Pulumi project found in the current directory. Run 'bli init' first."),
        (r"error: failed to load project: (.+)", 
         "Failed to load Pulumi project. Check your Pulumi.yaml file for errors."),
    ]
    
    # Try to match the error text to a pattern
    for pattern, message in error_mappings:
        match = re.search(pattern, error_text)
        if match:
            return message
    
    # Default message if no specific pattern matches
    return f"Pulumi error: {error_text}"

def run_pulumi_command(command: list, cwd: str, suppress_output: bool = False) -> subprocess.CompletedProcess:
    """Run a Pulumi command with better error handling."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        if not suppress_output and result.stdout.strip():
            print(result.stdout.strip())
        return result
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if hasattr(e, 'stderr') and e.stderr else str(e)
        user_friendly_error = interpret_pulumi_error(error_msg)
        
        raise BLIError(f"{user_friendly_error}\n\nCommand: {' '.join(command)}")

def initialize_pulumi_stack(work_dir: Path, stack_name: str) -> None:
    """Initialize a new Pulumi stack using YAML format."""
    print(f"Initializing Pulumi stack in: {work_dir}")
    
    # Get absolute path
    abs_work_dir = work_dir.absolute()
    
    # Create directory if it doesn't exist
    abs_work_dir.mkdir(parents=True, exist_ok=True)
    
    # First, check if there's any existing Pulumi.yaml and rename it temporarily
    pulumi_yaml_path = abs_work_dir / "Pulumi.yaml"
    temp_backup = None
    
    if pulumi_yaml_path.exists():
        temp_backup = abs_work_dir / "Pulumi.yaml.backup"
        pulumi_yaml_path.rename(temp_backup)
        print(f"{Fore.YELLOW}Found existing Pulumi.yaml, temporarily backed up to {temp_backup}{Style.RESET_ALL}")
    
    try:
        # Try to login to the local file-based backend
        print("Logging in to Pulumi backend...")
        result = subprocess.run(
            ["pulumi", "login", "file://~", "--non-interactive"],
            cwd=str(abs_work_dir),
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"{Fore.RED}Login failed with error: {result.stderr.strip()}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Trying alternative login approach...{Style.RESET_ALL}")
            
            # Try alternative approach - use file:// without the ~
            result = subprocess.run(
                ["pulumi", "login", "file://", "--non-interactive"],
                cwd=str(abs_work_dir),
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                raise Exception(f"Failed to login to Pulumi backend: {result.stderr.strip()}")
        
        print(f"{Fore.GREEN}✓{Style.RESET_ALL} Successfully logged in to Pulumi backend")
        
        # Now create the Pulumi.yaml file
        project_name = stack_name.replace('-', '_').lower()
        pulumi_yaml_content = f"""name: {project_name}
runtime: yaml
description: A Pulumi project created with BLI

variables:
  projectName:
    fn::invoke:
      function: pulumi:getProject
  stackName:
    fn::invoke:
      function: pulumi:getStack

resources:
  # Example resource (commented out)
  # my-bucket:
  #   type: gcp:storage:Bucket
  #   properties:
  #     location: US

outputs:
  message: "Stack initialized successfully!"
"""
        pulumi_yaml_path.write_text(pulumi_yaml_content)
        print(f"{Fore.GREEN}✓{Style.RESET_ALL} Created Pulumi.yaml with project name: {project_name}")
        
        # Create a new stack
        print(f"Creating new stack: {stack_name}...")
        stack_result = subprocess.run(
            ["pulumi", "stack", "init", stack_name, "--non-interactive"],
            cwd=str(abs_work_dir),
            capture_output=True,
            text=True
        )
        
        if stack_result.returncode != 0:
            if "already exists" in stack_result.stderr:
                print(f"{Fore.YELLOW}Stack '{stack_name}' already exists. Selecting it...{Style.RESET_ALL}")
                select_result = subprocess.run(
                    ["pulumi", "stack", "select", stack_name],
                    cwd=str(abs_work_dir),
                    capture_output=True,
                    text=True
                )
                if select_result.returncode != 0:
                    raise Exception(f"Failed to select stack: {select_result.stderr.strip()}")
                print(f"{Fore.GREEN}✓{Style.RESET_ALL} Selected stack: {stack_name}")
            else:
                raise Exception(f"Failed to create stack: {stack_result.stderr.strip()}")
        else:
            print(f"{Fore.GREEN}✓{Style.RESET_ALL} Created stack: {stack_name}")
        
        # Create a stack configuration file if it doesn't exist
        stack_yaml_path = abs_work_dir / f"Pulumi.{stack_name}.yaml"
        if not stack_yaml_path.exists():
            stack_yaml_content = """# Stack-specific configuration
config:
  # Example for GCP project (uncomment and modify as needed)
  # gcp:project: my-gcp-project-id
  # gcp:region: us-central1
"""
            stack_yaml_path.write_text(stack_yaml_content)
            print(f"{Fore.GREEN}✓{Style.RESET_ALL} Created stack configuration file: Pulumi.{stack_name}.yaml")
            
        print(f"{Fore.GREEN}Stack '{stack_name}' is ready to use!{Style.RESET_ALL}")
        
    except Exception as e:
        print(f"{Fore.RED}Error initializing stack: {str(e)}{Style.RESET_ALL}")
        
        # Restore backup if it exists
        if temp_backup and temp_backup.exists():
            temp_backup.rename(pulumi_yaml_path)
            print(f"{Fore.YELLOW}Restored original Pulumi.yaml from backup{Style.RESET_ALL}")
        
        raise

def init_command(args: Namespace) -> None:
    """Execute the init command."""
    try:
        initialize_pulumi_stack(args.work_dir, args.stack_name)
    except BLIError as e:
        print(f"{Fore.RED}Error: {str(e)}{Style.RESET_ALL}")
        # Provide helpful suggestions
        print(f"\n{Fore.YELLOW}Troubleshooting tips:{Style.RESET_ALL}")
        print("1. Ensure you have the latest version of Pulumi CLI installed")
        print("2. Try with a different stack name")
        print("3. Check permissions in your home directory")
        print("4. Run 'bli depend' to verify dependencies are correctly installed")
        sys.exit(1)
    except Exception as e:
        print(f"{Fore.RED}Unexpected error: {str(e)}{Style.RESET_ALL}")
        # For unexpected errors, suggest reporting the issue
        print(f"\n{Fore.YELLOW}This appears to be an unexpected error. Please report this issue.{Style.RESET_ALL}")
        sys.exit(1)