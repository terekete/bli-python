from argparse import Namespace
from pathlib import Path
import os
import re
import shutil
import subprocess
from typing import Optional

from colorama import Fore, Style

from bli.utils.config import Config, get_stack_name, setup_gcloud, setup_proxy
from bli.utils.pulumi_utils import run_pulumi_command
from bli.utils.templating import render_template

def clear_locks_for_stack(pulumi_home: Path, stack_name: str, verbose: bool = False) -> None:
    """Clear any lock files for the given stack."""
    locks_dir = pulumi_home / "locks" / stack_name
    if locks_dir.exists():
        if verbose:
            print(f"Clearing locks for stack '{stack_name}'...")
        try:
            for lock_file in locks_dir.glob("*.json"):
                try:
                    lock_file.unlink()
                    if verbose:
                        print(f"Removed lock file: {lock_file.name}")
                except Exception as e:
                    if verbose:
                        print(f"Could not remove lock file {lock_file.name}: {str(e)}")
        except Exception as e:
            if verbose:
                print(f"Error clearing locks: {str(e)}")

def simplify_resource_error(error_output: str) -> str:
    """Convert verbose cloud provider errors into simplified, user-friendly messages."""
    
    # Bucket already exists (GCP 409 Conflict)
    if "Error 409" in error_output and "already own it" in error_output:
        return f"{Fore.YELLOW}The resource already exists and you already own it. No changes required.{Style.RESET_ALL}"
    
    # Not found errors
    if "Error 404" in error_output and "not found" in error_output:
        return f"{Fore.YELLOW}The resource doesn't exist in the cloud provider.{Style.RESET_ALL}"
        
    # Permission errors
    if "Error 403" in error_output and ("permission" in error_output.lower() or "forbidden" in error_output.lower()):
        return f"{Fore.RED}You don't have sufficient permissions to perform this operation.{Style.RESET_ALL}"
    
    # Quota exceeded
    if "quota" in error_output.lower() and "exceed" in error_output.lower():
        return f"{Fore.RED}Quota exceeded for this resource. Please check your GCP quotas.{Style.RESET_ALL}"
    
    # Filter out help text for commands
    if "Usage:" in error_output and "Flags:" in error_output:
        lines = error_output.split('\n')
        filtered_lines = []
        in_help_section = False
        
        for line in lines:
            if "Usage:" in line:
                in_help_section = True
                # Add only the error line before usage
                for i in range(len(filtered_lines)-1, -1, -1):
                    if "error:" in filtered_lines[i].lower():
                        filtered_lines = filtered_lines[:i+1]
                        break
                continue
            elif not in_help_section or "error:" in line.lower():
                filtered_lines.append(line)
        
        return '\n'.join(filtered_lines)
    
    # Generic error - truncate the verbose parts
    if "error:" in error_output:
        # Get just the core error message
        for line in error_output.split('\n'):
            if "googleapi: Error" in line:
                parts = line.split("googleapi: Error ")
                if len(parts) > 1:
                    error_code = parts[1].split(':', 1)[0]
                    error_message = parts[1].split(':', 1)[1].split(',')[0] if ':' in parts[1] else parts[1]
                    return f"{Fore.RED}GCP Error {error_code}: {error_message}{Style.RESET_ALL}"
    
    # Return original if no simplification was possible
    return error_output

def process_pulumi_directory(
    dir_path: Path,
    build_path: Path,
    config: Config,
    inner_stack: Optional[str] = None,
    is_preview: bool = True,
    verbose: bool = False,
) -> None:
    """Process a Pulumi directory for preview."""
    if verbose:
        print(f"Processing Pulumi directory in: {dir_path}")
    
    # Get absolute build path
    abs_build_path = build_path.absolute()
    
    # Create build directory
    abs_build_path.mkdir(parents=True, exist_ok=True)
    pulumi_state_path = abs_build_path / ".pulumi"
    pulumi_state_path.mkdir(parents=True, exist_ok=True)
    
    # Set environment variables - ensure Pulumi uses the right state directory
    os.environ["PULUMI_HOME"] = str(pulumi_state_path)
    os.environ["PULUMI_CONFIG_PASSPHRASE"] = ""
    
    # Clear any locks that might exist
    clear_locks_for_stack(pulumi_state_path, config.stack_name, verbose)
    
    # Create a subprocess environment with the correct PULUMI_HOME
    env = os.environ.copy()
    
    # Copy files from dir_path to build_path
    for entry in dir_path.iterdir():
        if entry.is_file() and entry.name != "Pulumi.yaml":
            try:
                dest_path = abs_build_path / entry.name
                shutil.copy2(entry, dest_path)  # copy2 preserves metadata
            except Exception as e:
                if verbose:
                    print(f"{Fore.YELLOW}Warning copying {entry.name}: {str(e)}{Style.RESET_ALL}")
    
    # Render Pulumi.yaml if it exists
    if (dir_path / "Pulumi.yaml").exists():
        render_template(
            dir_path / "Pulumi.yaml",
            abs_build_path / "Pulumi.yaml",
            config,
            verbose
        )
    
    # Run Pulumi preview command with colorized output
    try:
        # Login to Pulumi backend
        if verbose:
            print(f"{Fore.CYAN}Logging in to Pulumi backend...{Style.RESET_ALL}")
        
        login_attempts = [
            ["pulumi", "login", "file://~", "--local"],
            ["pulumi", "login", "file://", "--local"],
            ["pulumi", "login", "file://~"],
            ["pulumi", "login", "file://"]
        ]
        
        login_success = False
        for login_cmd in login_attempts:
            try:
                result = subprocess.run(
                    login_cmd,
                    cwd=str(abs_build_path),
                    env=env,
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    login_success = True
                    if verbose:
                        print(f"{Fore.GREEN}Login successful with command: {' '.join(login_cmd)}{Style.RESET_ALL}")
                    break
                elif verbose:
                    print(f"{Fore.YELLOW}Login attempt failed with: {' '.join(login_cmd)}{Style.RESET_ALL}")
            except Exception as e:
                if verbose:
                    print(f"{Fore.YELLOW}Login exception: {str(e)}{Style.RESET_ALL}")
        
        # Check if stack exists by first looking for the stack files directly
        stack_exists = False
        try:
            # Check for stack files in the state directory
            stack_dir = pulumi_state_path / "stacks" / config.stack_name
            stack_file = stack_dir / "stack.json"
            
            if stack_dir.exists() and stack_file.exists():
                stack_exists = True
                if verbose:
                    print(f"{Fore.GREEN}Found existing stack files for '{config.stack_name}' in {stack_dir}{Style.RESET_ALL}")
            
            # If stack files don't exist, try command-line check as fallback
            if not stack_exists:
                stack_ls_result = subprocess.run(
                    ["pulumi", "stack", "ls"],
                    cwd=str(abs_build_path),
                    env=env,
                    capture_output=True,
                    text=True
                )
                
                # Check if the stack name is in the output
                if stack_ls_result.returncode == 0 and config.stack_name in stack_ls_result.stdout:
                    stack_exists = True
                    if verbose:
                        print(f"{Fore.GREEN}Found stack '{config.stack_name}' in Pulumi stack list{Style.RESET_ALL}")
            
        except Exception as e:
            if verbose:
                print(f"{Fore.YELLOW}Error checking for stack: {str(e)}{Style.RESET_ALL}")
            stack_exists = False
        
        # Create or select stack
        if not stack_exists:
            print(f"{Fore.YELLOW}Stack '{config.stack_name}' not found. Creating new stack...{Style.RESET_ALL}")
            
            if not (abs_build_path / "Pulumi.yaml").exists():
                # Create new project first
                project_name = "bli-project"
                with open(abs_build_path / "Pulumi.yaml", "w") as f:
                    f.write(f"name: {project_name}\nruntime: yaml\ndescription: BLI Project\n")
                
            # Create new stack with better error handling
            stack_init_result = subprocess.run(
                ["pulumi", "stack", "init", config.stack_name, "--non-interactive"],
                cwd=str(abs_build_path),
                env=env,
                capture_output=True,
                text=True
            )
            
            if stack_init_result.returncode == 0:
                print(f"{Fore.GREEN}Created stack: {config.stack_name}{Style.RESET_ALL}")
            else:
                # Show the actual error message
                error_output = stack_init_result.stderr if stack_init_result.stderr else stack_init_result.stdout
                if verbose:
                    print(f"{Fore.YELLOW}Stack creation output: {error_output}{Style.RESET_ALL}")
                
                # Check for common error patterns
                if "already exists" in error_output:
                    print(f"{Fore.YELLOW}Stack already exists, selecting it instead{Style.RESET_ALL}")
                elif "PULUMI_ACCESS_TOKEN" in error_output:
                    print(f"{Fore.YELLOW}Login issue detected. Trying explicit login...{Style.RESET_ALL}")
                    # Try with explicit file:// login
                    subprocess.run(
                        ["pulumi", "login", "file://"],
                        cwd=str(abs_build_path),
                        env=env,
                        capture_output=not verbose,
                        text=True
                    )
                    # Try stack creation again
                    subprocess.run(
                        ["pulumi", "stack", "init", config.stack_name, "--non-interactive"],
                        cwd=str(abs_build_path),
                        env=env,
                        capture_output=not verbose,
                        text=True
                    )
        
        # Select stack (always do this to be safe)
        select_result = subprocess.run(
            ["pulumi", "stack", "select", config.stack_name],
            cwd=str(abs_build_path),
            env=env,
            capture_output=True,
            text=True
        )
        
        if select_result.returncode == 0:
            if verbose:
                print(f"{Fore.GREEN}Selected stack: {config.stack_name}{Style.RESET_ALL}")
        elif verbose:
            print(f"{Fore.YELLOW}Stack selection output: {select_result.stderr}{Style.RESET_ALL}")
        
        # Configure stack (suppress output)
        run_pulumi_command(
            ["pulumi", "config", "set", "gcp:project", config.project_id],
            str(abs_build_path),
            suppress_output=not verbose
        )
        run_pulumi_command(
            ["pulumi", "config", "set", "project", config.project_id],
            str(abs_build_path),
            suppress_output=not verbose
        )
        
        # Execute preview - show actual Pulumi output by default
        print(f"{Fore.CYAN}Previewing changes for stack '{config.stack_name}'...{Style.RESET_ALL}")
        
        # Use direct Pulumi command to run preview and show output
        if verbose:
            # In verbose mode, show everything directly
            preview_result = subprocess.run(
                ["pulumi", "preview", "--stack", config.stack_name],
                cwd=str(abs_build_path),
                env=env,
                capture_output=False,  # Show output directly
                text=True
            )
        else:
            # In normal mode, capture and filter output
            preview_result = subprocess.run(
                ["pulumi", "preview", "--stack", config.stack_name],
                cwd=str(abs_build_path),
                env=env,
                capture_output=True,
                text=True
            )
            
            # Print the output but simplify error messages
            if preview_result.returncode == 0:
                # On success, print the full Pulumi output
                print(preview_result.stdout)
            else:
                # On error, simplify the error message
                simplified_output = simplify_resource_error(preview_result.stdout + preview_result.stderr)
                print(simplified_output)
            
    except Exception as e:
        print(f"{Fore.RED}Error: {str(e)}{Style.RESET_ALL}")
        raise

def preview_command(args: Namespace) -> None:
    """Execute the preview command."""
    # Ensure paths are absolute
    abs_work_dir = args.work_dir.absolute()
    abs_build_dir = abs_work_dir / "build"
    
    # Print paths only in verbose mode
    if args.verbose:
        print(f"Using work directory: {abs_work_dir}")
        print(f"Using build directory: {abs_build_dir}")
    
    # Ensure build directory exists
    abs_build_dir.mkdir(parents=True, exist_ok=True)
    
    # Create .pulumi directory if it doesn't exist
    pulumi_dir = abs_build_dir / ".pulumi"
    pulumi_dir.mkdir(parents=True, exist_ok=True)
    
    # Set environment variables BEFORE any Pulumi operations
    os.environ["PULUMI_HOME"] = str(pulumi_dir)
    os.environ["PULUMI_CONFIG_PASSPHRASE"] = ""
    os.environ["PULUMI_SKIP_UPDATE_CHECK"] = "true"  # Skip update checks
    
    # Verify Pulumi home directory only in verbose mode
    if args.verbose:
        try:
            result = subprocess.run(
                ["pulumi", "about"],
                env=os.environ.copy(),
                capture_output=True,
                text=True
            )
            if "PULUMI_HOME" in result.stdout:
                home_line = [line for line in result.stdout.splitlines() if "PULUMI_HOME" in line]
                print(f"Pulumi reports: {home_line[0] if home_line else 'PULUMI_HOME not found in output'}")
                
                # Check for incorrect paths in output and warn
                if str(pulumi_dir) not in ' '.join(home_line):
                    print(f"{Fore.RED}WARNING: Pulumi not using specified home directory!{Style.RESET_ALL}")
                    print(f"Expected: {pulumi_dir}")
        except Exception as e:
            print(f"Error running diagnostic: {str(e)}")
    
    # Check for locks only in verbose mode
    if args.verbose:
        locks_dir = pulumi_dir / "locks"
        if locks_dir.exists():
            print(f"Checking for locks in: {locks_dir}")
            try:
                # Walk through all stack locks
                for stack_lock_dir in locks_dir.iterdir():
                    if stack_lock_dir.is_dir():
                        print(f"Clearing locks for stack: {stack_lock_dir.name}")
                        for lock_file in stack_lock_dir.glob("*.json"):
                            try:
                                lock_file.unlink()
                                print(f"Removed lock file: {lock_file.name}")
                            except Exception as e:
                                print(f"Could not remove lock file {lock_file.name}: {str(e)}")
            except Exception as e:
                print(f"Error cleaning lock directories: {str(e)}")
    
    # Get stack name and create config
    stack_name = get_stack_name(args.stack_name, abs_work_dir)
    config = Config.from_cli(
        stack_name=stack_name,
        project_id=args.project_id,
        proxy_address=args.proxy_address,
        proxy_port=args.proxy_port,
        use_local_auth=args.use_local_auth,
        no_proxy=args.no_proxy,
        staging=args.stg,
        service=args.srv,
    )
    
    setup_proxy(config)
    setup_gcloud(config)
    
    # For extra safety, copy any Pulumi files from work dir to build dir
    for entry in abs_work_dir.glob("Pulumi.*"):
        if entry.is_file():
            target = abs_build_dir / entry.name
            try:
                shutil.copy2(entry, target)
                if args.verbose:
                    print(f"Copied Pulumi file: {entry.name}")
            except Exception as e:
                if args.verbose:
                    print(f"Failed to copy {entry.name}: {str(e)}")
    
    # Process the directory
    process_pulumi_directory(abs_work_dir, abs_build_dir, config, None, True, args.verbose)