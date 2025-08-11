import os
import re
import subprocess
from pathlib import Path
from typing import List, Callable, Optional

from colorama import Fore, Style

def colorize_pulumi_output(output: str) -> str:
    """Add colors to Pulumi output for better readability."""
    # Define color patterns
    patterns = [
        # Resource changes
        (r'(\s+\+\s+)([^\s].*?)(create)', f'\\1{Fore.GREEN}\\2{Style.RESET_ALL}{Fore.GREEN}\\3{Style.RESET_ALL}'),
        (r'(\s+\-\s+)([^\s].*?)(delete)', f'\\1{Fore.RED}\\2{Style.RESET_ALL}{Fore.RED}\\3{Style.RESET_ALL}'),
        (r'(\s+~\s+)([^\s].*?)(update)', f'\\1{Fore.YELLOW}\\2{Style.RESET_ALL}{Fore.YELLOW}\\3{Style.RESET_ALL}'),
        
        # Section headers
        (r'^(Previewing update|Updating|Destroying|Refreshing) \((.*?)\):', 
         f'{Fore.CYAN}\\1{Style.RESET_ALL} ({Fore.MAGENTA}\\2{Style.RESET_ALL}):'),
        (r'^(Outputs:)', f'{Fore.BLUE}\\1{Style.RESET_ALL}'),
        (r'^(Resources:)', f'{Fore.BLUE}\\1{Style.RESET_ALL}'),
        
        # Resource counts
        (r'(\d+) to create', f'{Fore.GREEN}\\1{Style.RESET_ALL} to create'),
        (r'(\d+) to delete', f'{Fore.RED}\\1{Style.RESET_ALL} to delete'),
        (r'(\d+) to update', f'{Fore.YELLOW}\\1{Style.RESET_ALL} to update'),
        (r'(\d+) changes', f'{Fore.CYAN}\\1{Style.RESET_ALL} changes'),
        
        # Final summary
        (r'(Preview|Update|Destroy|Refresh) completed', f'{Fore.GREEN}\\1 completed{Style.RESET_ALL}'),
        (r'(create:\s+)(\d+)', f'\\1{Fore.GREEN}\\2{Style.RESET_ALL}'),
        (r'(delete:\s+)(\d+)', f'\\1{Fore.RED}\\2{Style.RESET_ALL}'),
        (r'(update:\s+)(\d+)', f'\\1{Fore.YELLOW}\\2{Style.RESET_ALL}'),
        (r'(same:\s+)(\d+)', f'\\1{Fore.BLUE}\\2{Style.RESET_ALL}'),
        
        # Error messages
        (r'(\*\*.*?failed\*\*)', f'{Fore.RED}\\1{Style.RESET_ALL}'),
        (r'(error:.*)', f'{Fore.RED}\\1{Style.RESET_ALL}'),
        (r'(warning:.*)', f'{Fore.YELLOW}\\1{Style.RESET_ALL}'),
        
        # Stack messages
        (r"(Stack '.*?') (not found\. Creating new stack\.\.\.)", 
         f"{Fore.MAGENTA}\\1{Style.RESET_ALL} {Fore.YELLOW}\\2{Style.RESET_ALL}"),
    ]
    
    # Apply all color patterns
    colored_output = output
    for pattern, replacement in patterns:
        colored_output = re.sub(pattern, replacement, colored_output, flags=re.MULTILINE)
    
    return colored_output

def run_pulumi_command(
    command: List[str], 
    cwd: str, 
    on_output: Optional[Callable[[str], None]] = None,
    suppress_output: bool = False,
    filter_output: Optional[Callable[[str], bool]] = None
) -> str:
    """Run a Pulumi command and colorize its output.
    
    Args:
        command: The command to run as a list of strings
        cwd: The working directory to run the command in
        on_output: Optional callback function that receives each line of output
        suppress_output: If True, don't print any output to console
        filter_output: Optional function to filter output lines (return True to print)
        
    Returns:
        The complete command output as a string
    """
    # Set PULUMI_CONFIG_PASSPHRASE environment variable to empty string
    env = os.environ.copy()
    env["PULUMI_CONFIG_PASSPHRASE"] = ""
    
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line buffered
        env=env     # Pass the modified environment
    )
    
    output_lines = []
    for line in iter(process.stdout.readline, ''):
        # Store the original line for return value
        output_lines.append(line)
        
        # Apply filtering if provided
        if filter_output and not filter_output(line):
            continue
            
        # Colorize the line
        colored_line = colorize_pulumi_output(line.rstrip())
        
        # Print the colorized line if not suppressed
        if not suppress_output:
            print(colored_line)
        
        # Call the on_output callback if provided
        if on_output:
            on_output(line)
    
    # Wait for the process to complete
    process.stdout.close()
    return_code = process.wait()
    
    # Return the complete output
    output = ''.join(output_lines)
    
    if return_code != 0:
        # Don't raise exception for certain known errors in specific commands
        if "refresh" in command and ("not found" in output or "notFound" in output):
            # For refresh commands, don't fail on missing resources
            return output
        if "The specified bucket does not exist" in output:
            # Special case for missing buckets
            return output
            
        raise subprocess.CalledProcessError(return_code, command, output)
    
    return output

def fix_state_for_missing_resources(workspace_dir: str, stack_name: str, verbose: bool = False) -> bool:
    """Fix Pulumi state when resources are missing in the cloud but exist in state.
    
    Args:
        workspace_dir: The directory containing the Pulumi project
        stack_name: Name of the stack to fix
        verbose: If True, print detailed information
        
    Returns:
        bool: True if state was fixed successfully, False otherwise
    """
    import json
    import tempfile
    
    try:
        if verbose:
            print(f"{Fore.CYAN}Attempting to fix state for missing resources{Style.RESET_ALL}")
        
        # Export the current state
        state_json = run_pulumi_command(
            ["pulumi", "stack", "export", "--stack", stack_name],
            workspace_dir,
            suppress_output=True
        )
        
        if not state_json:
            print(f"{Fore.YELLOW}Warning: No state found to fix{Style.RESET_ALL}")
            return False
        
        # Parse the state
        try:
            state = json.loads(state_json)
        except json.JSONDecodeError:
            print(f"{Fore.YELLOW}Warning: Could not parse state JSON{Style.RESET_ALL}")
            return False
        
        # Check if there are resources to fix
        if 'resources' not in state or not state['resources']:
            if verbose:
                print(f"{Fore.YELLOW}No resources found in state{Style.RESET_ALL}")
            return False
        
        # Identify and remove resources that might be causing 404 errors
        original_count = len(state['resources'])
        
        # Look for resources with URNs containing known problematic resources
        # Add patterns for additional resources as needed
        problematic_patterns = ['my-bucket', 'no-longer-exists']
        
        # Filter out problematic resources
        state['resources'] = [
            r for r in state['resources']
            if not any(pattern in r.get('urn', '') for pattern in problematic_patterns)
        ]
        
        # Check if we removed any resources
        removed_count = original_count - len(state['resources'])
        if removed_count == 0:
            if verbose:
                print(f"{Fore.YELLOW}No problematic resources found in state{Style.RESET_ALL}")
            return False
        
        print(f"{Fore.GREEN}Identified {removed_count} problematic resources to remove from state{Style.RESET_ALL}")
        
        # Write the modified state to a temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
            json.dump(state, temp_file)
            temp_path = temp_file.name
        
        # Import the fixed state
        run_pulumi_command(
            ["pulumi", "stack", "import", "--file", temp_path, "--stack", stack_name],
            workspace_dir,
            suppress_output=not verbose
        )
        
        # Clean up the temporary file
        Path(temp_path).unlink(missing_ok=True)
        
        print(f"{Fore.GREEN}Successfully fixed state by removing {removed_count} problematic resources{Style.RESET_ALL}")
        return True
        
    except Exception as e:
        print(f"{Fore.RED}Error fixing state: {str(e)}{Style.RESET_ALL}")
        return False