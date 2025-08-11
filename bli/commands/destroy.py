from argparse import Namespace
from pathlib import Path
import os
import shutil
import subprocess
from typing import Optional

from colorama import Fore, Style

from bli.utils.config import Config, get_stack_name, setup_gcloud, setup_proxy
from bli.utils.pulumi_utils import run_pulumi_command, colorize_pulumi_output, fix_state_for_missing_resources
from bli.utils.templating import render_template
from bli.commands.clear import clear_lock_file

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

def process_pulumi_destroy(
    dir_path: Path,
    build_path: Path,
    config: Config,
    verbose: bool = False,
) -> None:
    """Process a Pulumi stack destruction."""
    if verbose:
        print(f"Processing Pulumi destroy in: {dir_path}")
    
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
                if verbose:
                    print(f"Copied file: {entry.name}")
            except Exception as e:
                if verbose:
                    print(f"{Fore.YELLOW}Warning copying {entry.name}: {str(e)}{Style.RESET_ALL}")
    
    # Render Pulumi.yaml if it exists using the templating utility
    if (dir_path / "Pulumi.yaml").exists():
        try:
            render_template(
                dir_path / "Pulumi.yaml",
                abs_build_path / "Pulumi.yaml",
                config,
                verbose
            )
            print(f"{Fore.GREEN}Rendered Pulumi.yaml template{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}Error rendering template: {str(e)}. Trying direct copy.{Style.RESET_ALL}")
            try:
                shutil.copy2(dir_path / "Pulumi.yaml", abs_build_path / "Pulumi.yaml")
                print(f"Copied Pulumi.yaml (unprocessed)")
            except Exception as copy_error:
                print(f"{Fore.RED}Failed to copy Pulumi.yaml: {str(copy_error)}{Style.RESET_ALL}")
    
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
                if verbose:
                    print(f"Attempting login with: {' '.join(login_cmd)}")
                
                result = subprocess.run(
                    login_cmd,
                    cwd=str(abs_build_path),
                    env=env,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    login_success = True
                    print(f"{Fore.GREEN}Login successful with command: {' '.join(login_cmd)}{Style.RESET_ALL}")
                    break
                elif verbose:
                    print(f"{Fore.YELLOW}Login attempt failed with: {' '.join(login_cmd)}{Style.RESET_ALL}")
                    print(f"Error: {result.stderr.strip()}")
            except Exception as e:
                if verbose:
                    print(f"{Fore.YELLOW}Login exception: {str(e)}{Style.RESET_ALL}")
        
        # If all attempts failed, try just --local without URL
        if not login_success:
            # Try an alternative login approach
            simple_login_cmd = ["pulumi", "login", "--local"]
            try:
                if verbose:
                    print(f"Attempting login with: {' '.join(simple_login_cmd)}")
                
                result = subprocess.run(
                    simple_login_cmd,
                    cwd=str(abs_build_path),
                    env=env,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    login_success = True
                    print(f"{Fore.GREEN}Login successful with command: {' '.join(simple_login_cmd)}{Style.RESET_ALL}")
                else:
                    if verbose:
                        print(f"{Fore.YELLOW}Login attempt failed with: {' '.join(simple_login_cmd)}{Style.RESET_ALL}")
                        print(f"Error: {result.stderr.strip()}")
            except Exception as e:
                if verbose:
                    print(f"{Fore.YELLOW}Login exception: {str(e)}{Style.RESET_ALL}")
        
        # Check if stack exists
        stack_exists = False
        try:
            if verbose:
                print(f"Looking for stack '{config.stack_name}' in current project...")
            
            # First check if Pulumi.yaml exists in the build directory
            if not (abs_build_path / "Pulumi.yaml").exists():
                print(f"{Fore.YELLOW}Warning: No Pulumi.yaml found in {abs_build_path}. Creating a minimal one.{Style.RESET_ALL}")
                # Create a basic Pulumi.yaml file
                with open(abs_build_path / "Pulumi.yaml", "w") as f:
                    f.write("name: bli-project\nruntime: yaml\ndescription: BLI Project\n")
            
            # Try to list stacks
            stack_ls_result = subprocess.run(
                ["pulumi", "stack", "ls"],
                cwd=str(abs_build_path),
                env=env,
                capture_output=True,
                text=True
            )
            
            # Check if the specific stack exists in the output
            found_in_list = False
            if stack_ls_result.returncode == 0:
                # Parse the output to look specifically for our stack
                lines = stack_ls_result.stdout.strip().split('\n')
                for line in lines:
                    if config.stack_name in line:
                        found_in_list = True
                        if verbose:
                            print(f"{Fore.GREEN}Found stack in list: {line.strip()}{Style.RESET_ALL}")
                        break
                
                if verbose and not found_in_list:
                    print(f"{Fore.YELLOW}Stack '{config.stack_name}' not found in stack listing{Style.RESET_ALL}")
            elif verbose:
                print(f"{Fore.YELLOW}Error listing stacks: {stack_ls_result.stderr.strip()}{Style.RESET_ALL}")
            
            # Make additional check for the stack's state file directly
            stack_state_dir = pulumi_state_path / "stacks"
            stack_state_path = None
            
            if stack_state_dir.exists():
                state_files_found = False
                for path in stack_state_dir.glob(f"*{config.stack_name}*"):
                    state_files_found = True
                    if path.is_file() and "stack.json" in str(path):
                        stack_state_path = path
                        stack_exists = True
                        print(f"{Fore.GREEN}Found stack state file for '{config.stack_name}'{Style.RESET_ALL}")
                        break
                    elif path.is_dir():
                        state_file = path / "stack.json"
                        if state_file.exists():
                            stack_state_path = state_file
                            stack_exists = True
                            print(f"{Fore.GREEN}Found stack state file for '{config.stack_name}'{Style.RESET_ALL}")
                            break
                
                if verbose and not state_files_found:
                    print(f"{Fore.YELLOW}No state files found for stack '{config.stack_name}' in {stack_state_dir}{Style.RESET_ALL}")
            
            # Check output of stack ls
            if not stack_exists and found_in_list:
                stack_exists = True
                print(f"{Fore.GREEN}Found stack '{config.stack_name}' in Pulumi stack list{Style.RESET_ALL}")
                
            if not stack_exists:
                print(f"{Fore.RED}Stack '{config.stack_name}' not found. Cannot destroy a non-existent stack.{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}Checked in {stack_state_dir} and in the Pulumi stack listing.{Style.RESET_ALL}")
                return
                
        except Exception as e:
            print(f"{Fore.RED}Error checking for stack: {str(e)}{Style.RESET_ALL}")
            return
        
        # Select stack if it exists
        if stack_exists:
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
            else:
                print(f"{Fore.RED}Failed to select stack: {select_result.stderr.strip()}{Style.RESET_ALL}")
                return
            
            # Try to fix any state issues before destroying
            try:
                print(f"{Fore.CYAN}Refreshing state before destroy...{Style.RESET_ALL}")
                # Use refresh with ignore-remote-errors to handle missing resources
                refresh_result = subprocess.run(
                    ["pulumi", "refresh", "--yes", "--stack", config.stack_name, "--skip-preview"],
                    cwd=str(abs_build_path),
                    env=env,
                    capture_output=True,
                    text=True
                )
                
                # Even if refresh fails, we'll still attempt to destroy
                if refresh_result.returncode != 0 and verbose:
                    print(f"{Fore.YELLOW}Refresh completed with warnings or errors. Continuing with destroy...{Style.RESET_ALL}")
            except Exception as e:
                if verbose:
                    print(f"{Fore.YELLOW}Refresh failed: {str(e)}. Continuing with destroy...{Style.RESET_ALL}")
            
            # First attempt - try destroy with normal options
            print(f"{Fore.CYAN}Destroying stack '{config.stack_name}'...{Style.RESET_ALL}")
            
            # Ask for confirmation
            confirmation = input(f"{Fore.YELLOW}WARNING: This will destroy all resources in stack '{config.stack_name}'.\nAre you sure you want to continue? (yes/no): {Style.RESET_ALL}")
            if confirmation.lower() not in ["yes", "y"]:
                print(f"{Fore.GREEN}Destroy operation cancelled.{Style.RESET_ALL}")
                return
            
            # Try to destroy the stack
            destroy_success = False
            try:
                destroy_result = subprocess.run(
                    ["pulumi", "destroy", "--yes", "--stack", config.stack_name, "--skip-preview"],
                    cwd=str(abs_build_path),
                    env=env,
                    capture_output=True,
                    text=True
                )
                
                destroy_output = destroy_result.stdout + destroy_result.stderr
                
                # Check for common errors and handle them
                if destroy_result.returncode == 0:
                    print(f"{Fore.GREEN}Stack successfully destroyed{Style.RESET_ALL}")
                    destroy_success = True
                
                # Print the colorized output
                colored_output = colorize_pulumi_output(destroy_output)
                print(colored_output)
                
            except Exception as e:
                print(f"{Fore.RED}Error during destroy: {str(e)}{Style.RESET_ALL}")
            
            # If destroy failed, try with --refresh-only first, then destroy again
            if not destroy_success:
                print(f"{Fore.YELLOW}First destroy attempt failed. Trying with refresh-only...{Style.RESET_ALL}")
                try:
                    # First run a refresh-only update
                    subprocess.run(
                        ["pulumi", "up", "--refresh-only", "--yes", "--stack", config.stack_name],
                        cwd=str(abs_build_path),
                        env=env,
                        capture_output=not verbose
                    )
                    
                    # Then try destroying again
                    print(f"{Fore.CYAN}Retrying destroy...{Style.RESET_ALL}")
                    destroy_result = subprocess.run(
                        ["pulumi", "destroy", "--yes", "--stack", config.stack_name, "--skip-preview"],
                        cwd=str(abs_build_path),
                        env=env,
                        capture_output=True,
                        text=True
                    )
                    
                    destroy_output = destroy_result.stdout + destroy_result.stderr
                    colored_output = colorize_pulumi_output(destroy_output)
                    print(colored_output)
                    
                    if destroy_result.returncode == 0:
                        print(f"{Fore.GREEN}Stack successfully destroyed on second attempt{Style.RESET_ALL}")
                        destroy_success = True
                    
                except Exception as e:
                    print(f"{Fore.RED}Error during second destroy attempt: {str(e)}{Style.RESET_ALL}")
            
            # If destroy is still failing, attempt to forcefully remove the stack
            if not destroy_success:
                print(f"{Fore.YELLOW}Destroy failed. Do you want to force-remove the stack? This will remove the stack metadata without destroying resources.{Style.RESET_ALL}")
                force_remove = input(f"{Fore.YELLOW}Force remove stack? (yes/no): {Style.RESET_ALL}")
                
                if force_remove.lower() in ["yes", "y"]:
                    try:
                        # Force remove the stack
                        remove_result = subprocess.run(
                            ["pulumi", "stack", "rm", "--yes", "--force", config.stack_name],
                            cwd=str(abs_build_path),
                            env=env,
                            capture_output=True,
                            text=True
                        )
                        
                        if remove_result.returncode == 0:
                            print(f"{Fore.GREEN}Stack metadata forcefully removed. Note that cloud resources may still exist.{Style.RESET_ALL}")
                        else:
                            print(f"{Fore.RED}Failed to force-remove stack: {remove_result.stderr.strip()}{Style.RESET_ALL}")
                    except Exception as e:
                        print(f"{Fore.RED}Error during force-remove: {str(e)}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}Force-remove cancelled. Stack remains with possible resource leaks.{Style.RESET_ALL}")
            
            # If destroy was successful, offer to remove the stack metadata
            if destroy_success:
                print(f"{Fore.CYAN}Do you want to remove the stack metadata? This will completely remove the stack from Pulumi.{Style.RESET_ALL}")
                remove_stack = input(f"{Fore.YELLOW}Remove stack metadata? (yes/no): {Style.RESET_ALL}")
                
                if remove_stack.lower() in ["yes", "y"]:
                    try:
                        # Remove the stack
                        remove_result = subprocess.run(
                            ["pulumi", "stack", "rm", "--yes", config.stack_name],
                            cwd=str(abs_build_path),
                            env=env,
                            capture_output=True,
                            text=True
                        )
                        
                        if remove_result.returncode == 0:
                            print(f"{Fore.GREEN}Stack metadata removed. Cleanup complete.{Style.RESET_ALL}")
                        else:
                            print(f"{Fore.RED}Failed to remove stack metadata: {remove_result.stderr.strip()}{Style.RESET_ALL}")
                    except Exception as e:
                        print(f"{Fore.RED}Error removing stack metadata: {str(e)}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}Stack metadata preserved. You can reuse this stack in the future.{Style.RESET_ALL}")
        
    except Exception as e:
        print(f"{Fore.RED}Error: {str(e)}{Style.RESET_ALL}")
        raise

def destroy_command(args: Namespace) -> None:
    """Execute the destroy command."""
    # Ensure paths are absolute
    abs_work_dir = args.work_dir.absolute()
    abs_build_dir = abs_work_dir / "build"
    
    # Check if verbose flag exists in args
    verbose = getattr(args, 'verbose', False)
    
    # Always print paths for better debugging
    print(f"Using work directory: {abs_work_dir}")
    print(f"Using build directory: {abs_build_dir}")
    
    # Ensure build directory exists
    abs_build_dir.mkdir(parents=True, exist_ok=True)
    
    # Check for existing Pulumi state in common locations
    standard_pulumi_home = Path.home() / ".pulumi"
    if verbose and standard_pulumi_home.exists():
        print(f"Found standard Pulumi home directory at: {standard_pulumi_home}")
    
    # First, look for state in work_dir
    work_dir_pulumi = abs_work_dir / ".pulumi"
    if work_dir_pulumi.exists():
        if verbose:
            print(f"Found Pulumi state directory in work directory: {work_dir_pulumi}")
        # Use this as our state directory
        pulumi_dir = work_dir_pulumi
    else:
        # Use build directory for state
        pulumi_dir = abs_build_dir / ".pulumi"
        pulumi_dir.mkdir(parents=True, exist_ok=True)
        if verbose:
            print(f"Created Pulumi state directory: {pulumi_dir}")
    
    # Set environment variables BEFORE any Pulumi operations
    os.environ["PULUMI_HOME"] = str(pulumi_dir)
    os.environ["PULUMI_CONFIG_PASSPHRASE"] = ""
    os.environ["PULUMI_SKIP_UPDATE_CHECK"] = "true"  # Skip update checks
    
    if verbose:
        print(f"PULUMI_HOME set to: {os.environ['PULUMI_HOME']}")
    
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
                if verbose:
                    print(f"Copied Pulumi file: {entry.name}")
            except Exception as e:
                if verbose:
                    print(f"Failed to copy {entry.name}: {str(e)}")
    
    # Process the directory
    process_pulumi_destroy(abs_work_dir, abs_build_dir, config, verbose)