from argparse import Namespace
from pathlib import Path
import os
import shutil
import subprocess
import json
import re
from typing import Optional, Callable, List, Dict, Any

import pulumi.automation as automation
from colorama import Fore, Style

from bli.utils.config import Config, get_stack_name, setup_gcloud, setup_proxy
from bli.utils.templating import render_template
from bli.utils.pulumi_utils import run_pulumi_command

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

def extract_failing_resources(output: str) -> List[str]:
    """Extract failing resource URNs from command output."""
    failing_urns = []
    
    # Look for URNs in error messages
    urn_pattern = r'urn:pulumi:[^:]+::[^:]+::[^:]+:[^:]+::([^:]+)'
    not_found_lines = [line for line in output.split('\n') if 
                        ('not found' in line.lower() or 
                         'does not exist' in line.lower() or 
                         'notfound' in line.lower() or 
                         'deleting failed' in line.lower())]
    
    for line in not_found_lines:
        urn_matches = re.findall(urn_pattern, line)
        if urn_matches:
            for match in urn_matches:
                full_urn = line[line.find('urn:pulumi'):].split()[0].rstrip(':,')
                failing_urns.append(full_urn)
    
    # If we couldn't extract full URNs, try to at least get resource names
    if not failing_urns:
        resource_pattern = r'([A-Za-z0-9_-]+)\s+\*\*deleting failed\*\*'
        for line in output.split('\n'):
            resource_matches = re.findall(resource_pattern, line)
            if resource_matches:
                failing_urns.extend(resource_matches)
    
    return failing_urns

def process_pulumi_directory(
    dir_path: Path,
    build_path: Path,
    config: Config,
    inner_stack: Optional[str] = None,
    is_preview: bool = False,
    verbose: bool = False,
) -> None:
    """Process a Pulumi directory for deployment or preview."""
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
    
    # Copy files from dir_path to build_path using shutil
    for entry in dir_path.iterdir():
        if entry.is_file() and entry.name != "Pulumi.yaml":
            dest_path = abs_build_path / entry.name
            try:
                shutil.copy2(entry, dest_path)  # copy2 preserves metadata
            except shutil.Error as e:
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
    
    # Check if we have an existing stack
    stack_exists = False
    try:
        # Run direct Pulumi command to check if stack exists
        result = subprocess.run(
            ["pulumi", "stack", "ls"],
            cwd=str(abs_build_path),
            env=env,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0 and config.stack_name in result.stdout:
            stack_exists = True
            if verbose:
                print(f"{Fore.GREEN}Found existing stack: {config.stack_name}{Style.RESET_ALL}")
        else:
            if verbose:
                print(f"{Fore.YELLOW}No existing stack found named: {config.stack_name}{Style.RESET_ALL}")
    except Exception as e:
        if verbose:
            print(f"{Fore.YELLOW}Error checking for existing stack: {str(e)}{Style.RESET_ALL}")
    
    # Define an empty program function
    def empty_program():
        pass
    
    # Initialize Pulumi backend using Automation API
    stack = None
    try:
        # First, try to login to local backend using subprocess
        if verbose:
            print(f"{Fore.CYAN}Logging in to Pulumi backend...{Style.RESET_ALL}")
        login_attempts = [
            ["pulumi", "login", "file://~", "--local"],
            ["pulumi", "login", "file://", "--local"],
            ["pulumi", "login", "file://~"],
            ["pulumi", "login", "file://"]
        ]
        
        login_success = False
        if verbose:
            print(f"{Fore.CYAN}Attempting to login to Pulumi backend...{Style.RESET_ALL}")

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
                    print(f"{Fore.GREEN}Login successful{Style.RESET_ALL}")
                    break
                elif verbose:
                    print(f"{Fore.YELLOW}Login attempt failed: {' '.join(login_cmd)}{Style.RESET_ALL}")
            except Exception as e:
                if verbose:
                    print(f"{Fore.YELLOW}Login exception: {str(e)}{Style.RESET_ALL}")

        # And update the refresh output:
        # Find this:
        print(f"{Fore.CYAN}Refreshing state...{Style.RESET_ALL}")

        # Add a try/except to handle the error you're seeing:
        print(f"{Fore.CYAN}Refreshing state...{Style.RESET_ALL}")
        try:
            # The refresh command has an issue with --ignore-remote-errors in some Pulumi versions
            # So we'll use a more compatible approach
            refresh_result = subprocess.run(
                ["pulumi", "refresh", "--yes", "--stack", config.stack_name, "--skip-preview"],
                cwd=str(abs_build_path),
                env=env,
                capture_output=True,
                text=True
            )
            
            if refresh_result.returncode == 0:
                if verbose:
                    print(f"{Fore.GREEN}Refresh completed successfully{Style.RESET_ALL}")
            else:
                if verbose:
                    print(f"{Fore.YELLOW}Refresh completed with warnings or errors{Style.RESET_ALL}")
        except Exception as e:
            if "stdout and stderr arguments may not be used with capture_output" in str(e):
                # This is a known issue with subprocess in some Python versions
                try:
                    # Try alternative approach without capture_output
                    refresh_result = subprocess.run(
                        ["pulumi", "refresh", "--yes", "--stack", config.stack_name, "--skip-preview"],
                        cwd=str(abs_build_path),
                        env=env,
                        capture_output=True,
                        text=True
                    )
                    if verbose:
                        print(f"{Fore.GREEN}Refresh completed with alternative method{Style.RESET_ALL}")
                except Exception as alt_e:
                    print(f"{Fore.YELLOW}Refresh could not be completed: {str(alt_e)}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}Refresh warnings: {str(e)}{Style.RESET_ALL}")

        # Initialize workspace
        workspace = automation.LocalWorkspace(
            work_dir=str(abs_build_path),
            pulumi_home=str(pulumi_state_path)
        )
        
        # Handle stack creation/selection
        if stack_exists:
            print(f"{Fore.CYAN}Using existing stack: {config.stack_name}{Style.RESET_ALL}")
            try:
                # First, try direct command to select stack
                select_result = subprocess.run(
                    ["pulumi", "stack", "select", config.stack_name],
                    cwd=str(abs_build_path),
                    env=env,
                    capture_output=True,
                    text=True
                )
                
                if select_result.returncode != 0 and verbose:
                    print(f"{Fore.YELLOW}Note: Failed to select stack using command line, trying automation API{Style.RESET_ALL}")
                
                # Now use automation API
                stack = automation.select_stack(
                    stack_name=config.stack_name,
                    work_dir=str(abs_build_path),
                    program=empty_program,
                )
            except Exception as e:
                if verbose:
                    print(f"{Fore.YELLOW}Error selecting stack, will try to create it: {str(e)}{Style.RESET_ALL}")
                stack_exists = False

        if not stack_exists:
            print(f"{Fore.CYAN}Stack '{config.stack_name}' not found. Creating new stack...{Style.RESET_ALL}")
            
            # Create project file if it doesn't exist
            if not (abs_build_path / "Pulumi.yaml").exists():
                project_name = "bli-project"
                with open(abs_build_path / "Pulumi.yaml", "w") as f:
                    f.write(f"name: {project_name}\nruntime: yaml\ndescription: BLI Project\n")
            
            # Try to create the stack using direct command first
            create_result = subprocess.run(
                ["pulumi", "stack", "init", config.stack_name, "--non-interactive"],
                cwd=str(abs_build_path),
                env=env,
                capture_output=True,
                text=True
            )
            
            if create_result.returncode == 0:
                print(f"{Fore.GREEN}Created stack: {config.stack_name}{Style.RESET_ALL}")
            elif "already exists" in (create_result.stdout + create_result.stderr):
                print(f"{Fore.GREEN}Stack already exists, selecting it{Style.RESET_ALL}")
            else:
                if verbose:
                    print(f"{Fore.YELLOW}Direct stack creation failed, trying automation API: {create_result.stderr}{Style.RESET_ALL}")

            # Now use automation API
            try:
                stack = automation.select_stack(
                    stack_name=config.stack_name,
                    work_dir=str(abs_build_path),
                    program=empty_program,
                )
                if verbose:
                    print(f"{Fore.GREEN}Selected existing stack: {config.stack_name}{Style.RESET_ALL}")
            except Exception:
                stack = automation.create_stack(
                    stack_name=config.stack_name,
                    work_dir=str(abs_build_path),
                    program=empty_program,
                )
                print(f"{Fore.GREEN}Created stack: {config.stack_name}{Style.RESET_ALL}")
        
        # Configure stack
        stack.set_config("gcp:project", automation.ConfigValue(value=config.project_id))
        stack.set_config("project", automation.ConfigValue(value=config.project_id))
        
        # Execute preview or update based on is_preview flag
        if is_preview:
            print(f"{Fore.CYAN}Previewing changes for stack '{config.stack_name}'...{Style.RESET_ALL}")
            preview_result = stack.preview(on_output=print if verbose else None)
            print(f"Preview completed with {len(preview_result.change_summary)} changes")
            # Print detailed change summary
            has_changes = False
            for op_type, count in preview_result.change_summary.items():
                if count > 0:
                    has_changes = True
                    print(f"  {op_type}: {count}")
            
            if not has_changes:
                print(f"{Fore.GREEN}No changes required{Style.RESET_ALL}")
        else:
            # First, try to refresh the stack to sync state with cloud
            print(f"{Fore.CYAN}Refreshing state...{Style.RESET_ALL}")
            
            # Try using --refresh flag with up command instead of separate refresh command
            refresh_output = ""
            try:
                # The refresh command has an issue with --ignore-remote-errors in some Pulumi versions
                # So we'll use a more compatible approach
                refresh_result = subprocess.run(
                    ["pulumi", "refresh", "--yes", "--stack", config.stack_name, "--skip-preview"],
                    cwd=str(abs_build_path),
                    env=env,
                    capture_output=True,
                    text=True,
                    stderr=subprocess.PIPE
                )
                
                refresh_output = refresh_result.stdout
                refresh_error = refresh_result.stderr
                
                # Check for flag error in stderr and retry without the flag if needed
                if "unknown flag" in refresh_error and "--ignore-remote-errors" in refresh_error:
                    if verbose:
                        print(f"{Fore.YELLOW}Retrying refresh without --ignore-remote-errors flag{Style.RESET_ALL}")
                    refresh_result = subprocess.run(
                        ["pulumi", "refresh", "--yes", "--stack", config.stack_name, "--skip-preview"],
                        cwd=str(abs_build_path),
                        env=env,
                        capture_output=True,
                        text=True
                    )
                    refresh_output = refresh_result.stdout + refresh_result.stderr
                
                # Check for "resource already exists" message in refresh
                if "Error 409" in refresh_output and "already own it" in refresh_output:
                    simplified = simplify_resource_error(refresh_output)
                    print(simplified)
                    return  # Exit early as resource already exists
                elif refresh_result.returncode == 0:
                    if verbose:
                        print(f"{Fore.GREEN}Refresh completed successfully{Style.RESET_ALL}")
                else:
                    if verbose:
                        print(f"{Fore.YELLOW}Refresh completed with warnings or errors{Style.RESET_ALL}")
                    
                    # Simplify error output
                    simplified = simplify_resource_error(refresh_output)
                    if simplified != refresh_output:
                        print(simplified)
                    elif verbose:
                        print(refresh_output)
                
                # Check if we need to fix missing resources in state
                if "not found" in refresh_output.lower() or "does not exist" in refresh_output.lower():
                    if verbose:
                        print(f"{Fore.YELLOW}Detected missing resources in refresh. Attempting to fix state...{Style.RESET_ALL}")
                    
                    # Extract failing resources from refresh output
                    failing_resources = extract_failing_resources(refresh_output)
                    
                    if failing_resources:
                        if verbose:
                            print(f"{Fore.YELLOW}Identified failing resources: {failing_resources}{Style.RESET_ALL}")
                        
                        # Export state
                        export_result = subprocess.run(
                            ["pulumi", "stack", "export", "--stack", config.stack_name],
                            cwd=str(abs_build_path),
                            env=env,
                            capture_output=True,
                            text=True
                        )
                        
                        if export_result.returncode == 0 and export_result.stdout:
                            try:
                                # Parse the state
                                state = json.loads(export_result.stdout)
                                
                                if 'resources' in state:
                                    original_count = len(state['resources'])
                                    
                                    # Filter out failing resources
                                    filtered_resources = []
                                    for resource in state['resources']:
                                        should_keep = True
                                        resource_urn = resource.get('urn', '')
                                        
                                        # Check if this resource matches any failing resource
                                        for failing in failing_resources:
                                            if failing in resource_urn:
                                                should_keep = False
                                                break
                                        
                                        if should_keep:
                                            filtered_resources.append(resource)
                                    
                                    state['resources'] = filtered_resources
                                    removed_count = original_count - len(filtered_resources)
                                    
                                    if removed_count > 0:
                                        if verbose:
                                            print(f"{Fore.GREEN}Removed {removed_count} problematic resources from state{Style.RESET_ALL}")
                                        
                                        # Write fixed state to file
                                        state_file = abs_build_path / "fixed-state.json"
                                        with open(state_file, 'w') as f:
                                            json.dump(state, f)
                                        
                                        # Import fixed state
                                        import_result = subprocess.run(
                                            ["pulumi", "stack", "import", "--file", str(state_file), "--stack", config.stack_name],
                                            cwd=str(abs_build_path),
                                            env=env,
                                            capture_output=True,
                                            text=True
                                        )
                                        
                                        if import_result.returncode == 0:
                                            if verbose:
                                                print(f"{Fore.GREEN}Successfully imported fixed state{Style.RESET_ALL}")
                                        elif verbose:
                                            print(f"{Fore.YELLOW}State import warning: {import_result.stderr}{Style.RESET_ALL}")
                            except Exception as json_error:
                                if verbose:
                                    print(f"{Fore.YELLOW}Error processing state JSON: {str(json_error)}{Style.RESET_ALL}")
            except Exception as refresh_error:
                if verbose:
                    print(f"{Fore.YELLOW}Refresh failed: {str(refresh_error)}{Style.RESET_ALL}")
            
            # Clear locks again before deployment
            clear_locks_for_stack(pulumi_state_path, config.stack_name, verbose)
            
            # Now try the deployment
            print(f"{Fore.CYAN}Deploying stack '{config.stack_name}'...{Style.RESET_ALL}")
            
            try:
                # First, try a direct Pulumi up command
                up_result = subprocess.run(
                    ["pulumi", "up", "--yes", "--stack", config.stack_name, "--skip-preview"],
                    cwd=str(abs_build_path),
                    env=env,
                    capture_output=True,  # Capture for error analysis
                    text=True
                )
                
                up_output = up_result.stdout + up_result.stderr
                
                # Check for resource already exists (409 Conflict) error
                if "Error 409" in up_output and "already own it" in up_output:
                    simplified = simplify_resource_error(up_output)
                    print(simplified)
                    print(f"{Fore.GREEN}Resource already exists and you own it. No action needed.{Style.RESET_ALL}")
                    # Consider this a success and return
                    return
                
                # Process and display output
                if up_result.returncode == 0:
                    print(f"{Fore.GREEN}Deployment completed successfully{Style.RESET_ALL}")
                    
                    # Extract and show only the resources section for non-verbose output
                    if not verbose:
                        resources_section = re.search(r'Resources:.*?(?=Duration|\Z)', up_output, re.DOTALL)
                        if resources_section:
                            summary = resources_section.group(0).strip()
                            print(summary)
                    else:
                        # Show full output in verbose mode
                        print(up_output)
                else:
                    # For errors, always simplify
                    simplified_output = simplify_resource_error(up_output)
                    if simplified_output != up_output:
                        print(f"Simplified error: {simplified_output}")
                        if verbose:
                            print("Raw output:")
                            print(up_output)
                    else:
                        print(up_output)
                    
                    # Check for "not found" or "does not exist" errors
                    if "not found" in up_output.lower() or "does not exist" in up_output.lower():
                        print(f"{Fore.YELLOW}Deployment failed due to missing resources.{Style.RESET_ALL}")
                        
                        # Extract failing resources for replacement
                        failing_resources = extract_failing_resources(up_output)
                        
                        if failing_resources:
                            if verbose:
                                print(f"{Fore.YELLOW}Attempting to replace resources: {failing_resources}{Style.RESET_ALL}")
                            else:
                                print(f"{Fore.YELLOW}Attempting to replace failing resources...{Style.RESET_ALL}")
                            
                            # Try replacing each failing resource
                            replace_success = False
                            for res in failing_resources:
                                try:
                                    replace_cmd = ["pulumi", "up", "--yes", "--stack", config.stack_name, "--replace", res]
                                    if verbose:
                                        print(f"Running: {' '.join(replace_cmd)}")
                                    
                                    replace_result = subprocess.run(
                                        replace_cmd,
                                        cwd=str(abs_build_path),
                                        env=env,
                                        capture_output=not verbose  # Show output directly only in verbose mode
                                    )
                                    
                                    if replace_result.returncode == 0:
                                        replace_success = True
                                        print(f"{Fore.GREEN}Successfully replaced resource{Style.RESET_ALL}")
                                        break
                                except Exception as replace_error:
                                    if verbose:
                                        print(f"{Fore.YELLOW}Error replacing resource {res}: {str(replace_error)}{Style.RESET_ALL}")
                            
                            if not replace_success:
                                # Try with refresh only as a last resort
                                print(f"{Fore.YELLOW}Resource replacement failed, trying refresh-only update...{Style.RESET_ALL}")
                                full_refresh_result = subprocess.run(
                                    ["pulumi", "up", "--yes", "--stack", config.stack_name, "--refresh-only"],
                                    cwd=str(abs_build_path),
                                    env=env,
                                    capture_output=not verbose
                                )
                                
                                if full_refresh_result.returncode == 0:
                                    print(f"{Fore.GREEN}Refresh-only update succeeded{Style.RESET_ALL}")
                                    
                                    # Try normal update again
                                    final_up_result = subprocess.run(
                                        ["pulumi", "up", "--yes", "--stack", config.stack_name],
                                        cwd=str(abs_build_path),
                                        env=env,
                                        capture_output=not verbose
                                    )
                                    
                                    if final_up_result.returncode == 0:
                                        print(f"{Fore.GREEN}Final deployment succeeded{Style.RESET_ALL}")
                                    else:
                                        print(f"{Fore.RED}Final deployment failed{Style.RESET_ALL}")
                        else:
                            # If we couldn't identify specific resources, try refresh-only
                            print(f"{Fore.YELLOW}Could not identify specific failing resources, trying refresh-only update...{Style.RESET_ALL}")
                            refresh_only_result = subprocess.run(
                                ["pulumi", "up", "--yes", "--stack", config.stack_name, "--refresh-only"],
                                cwd=str(abs_build_path),
                                env=env,
                                capture_output=not verbose
                            )
                            
                            if refresh_only_result.returncode == 0:
                                print(f"{Fore.GREEN}Refresh-only update succeeded, trying normal update...{Style.RESET_ALL}")
                                # Try normal update again
                                final_up_result = subprocess.run(
                                    ["pulumi", "up", "--yes", "--stack", config.stack_name],
                                    cwd=str(abs_build_path),
                                    env=env,
                                    capture_output=not verbose
                                )
                                
                                if final_up_result.returncode == 0:
                                    print(f"{Fore.GREEN}Final deployment succeeded{Style.RESET_ALL}")
                                else:
                                    print(f"{Fore.RED}Final deployment failed{Style.RESET_ALL}")
                    else:
                        # If it's some other error, fall back to automation API
                        print(f"{Fore.YELLOW}Direct deployment command failed, trying alternative method...{Style.RESET_ALL}")
                        up_result = stack.up(on_output=print if verbose else None)
                        print(f"Deployment completed with status: {up_result.summary.result}")
            except Exception as deploy_error:
                print(f"{Fore.RED}Deployment failed: {str(deploy_error)}{Style.RESET_ALL}")
                raise
            
    except Exception as e:
        print(f"{Fore.RED}Error: {str(e)}{Style.RESET_ALL}")
        raise

def deploy_command(args: Namespace) -> None:
    """Execute the deploy command."""
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
    
    # Verify that Pulumi is using the correct home directory - only in verbose mode
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
    
    # ONLY check for locks in our specified pulumi directory, not global ones
    locks_dir = pulumi_dir / "locks"
    if locks_dir.exists() and args.verbose:
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
    
    # Set specific command-line options for every Pulumi command
    os.environ["PULUMI_SKIP_UPDATE_CHECK"] = "true"  # Skip update checks
    
    # Run the process with 100% environment-based state path
    process_pulumi_directory(abs_work_dir, abs_build_dir, config, None, False, args.verbose)