import os
import shutil
import subprocess
import tempfile
import json
import re
from argparse import Namespace
from pathlib import Path
from typing import Optional, Dict, List, Any, Set, Tuple

from colorama import Fore, Style

from bli.utils.config import Config, get_stack_name, setup_gcloud, setup_proxy
from bli.utils.templating import render_template

def format_dot_output(dot_content: str) -> None:
    """
    Format a DOT graph into a more readable text representation.
    
    Args:
        dot_content: DOT graph content as string
    """
    # Parse nodes
    nodes = {}
    node_pattern = r'Resource(\d+) \[label="([^"]+)"\];'
    for match in re.finditer(node_pattern, dot_content):
        node_id = f"Resource{match.group(1)}"
        node_label = match.group(2)
        nodes[node_id] = node_label
    
    # Parse edges
    edges = []
    edge_pattern = r'Resource(\d+) -> Resource(\d+)'
    for match in re.finditer(edge_pattern, dot_content):
        source_id = f"Resource{match.group(1)}"
        target_id = f"Resource{match.group(2)}"
        # Try to extract label if present
        label = ""
        label_match = re.search(fr'{source_id} -> {target_id}\s*\[.*?label = "([^"]+)"', dot_content)
        if label_match:
            label = label_match.group(1)
        edges.append((source_id, target_id, label))
    
    # Format nodes for display
    formatted_nodes = {}
    for node_id, node_label in nodes.items():
        # Extract relevant parts from URN
        if node_label.startswith("urn:pulumi:"):
            parts = node_label.split("::")
            if len(parts) >= 3:
                resource_type = parts[-2] if len(parts) >= 5 else ""
                resource_name = parts[-1]
                
                if resource_type:
                    display_name = f"{Fore.GREEN}{resource_name}{Style.RESET_ALL} ({Fore.CYAN}{resource_type}{Style.RESET_ALL})"
                else:
                    display_name = f"{Fore.GREEN}{resource_name}{Style.RESET_ALL}"
                
                formatted_nodes[node_id] = display_name
        else:
            formatted_nodes[node_id] = f"{Fore.GREEN}{node_label}{Style.RESET_ALL}"
    
    # Print resources
    print(f"\n{Fore.BLUE}Resources:{Style.RESET_ALL}")
    for node_id, display_name in formatted_nodes.items():
        print(f"  {display_name}")
    
    # Print dependencies
    if edges:
        print(f"\n{Fore.BLUE}Dependencies:{Style.RESET_ALL}")
        for source_id, target_id, label in edges:
            source_name = formatted_nodes.get(source_id, source_id)
            target_name = formatted_nodes.get(target_id, target_id)
            
            if label:
                relationship = f"  {source_name} → {target_name} ({Fore.YELLOW}{label}{Style.RESET_ALL})"
            else:
                relationship = f"  {source_name} → {target_name}"
            
            print(relationship)

def display_simple_tree(dot_content: str, resources: List[Dict[str, Any]], resource_details: bool = False, verbose: bool = False):
    """
    Display a simple tree representation of the resource graph.
    
    Args:
        dot_content: DOT graph content as string
        resources: List of resource objects with details
        resource_details: Whether to show detailed resource information
        verbose: Whether to show verbose debug information
    """
    print(f"\n{Fore.CYAN}Resource Dependency Tree:{Style.RESET_ALL}")
    
    # For troubleshooting in verbose mode
    if verbose:
        print(f"{Fore.YELLOW}Debug: Raw DOT content sample:{Style.RESET_ALL}")
        print(dot_content[:500] + "..." if len(dot_content) > 500 else dot_content)
    
    # Step 1: Parse nodes
    nodes = {}
    node_pattern = r'Resource(\d+) \[label="([^"]+)"\];'
    for match in re.finditer(node_pattern, dot_content):
        node_id = f"Resource{match.group(1)}"
        node_label = match.group(2)
        nodes[node_id] = node_label
    
    if verbose:
        print(f"{Fore.YELLOW}Debug: Found {len(nodes)} nodes{Style.RESET_ALL}")
    
    # Step 2: Parse edges - more flexible pattern
    edges = []
    # First try the most specific pattern with color and possible label
    edge_pattern = r'Resource(\d+) -> Resource(\d+)(?: \[color[^]]*\])?;'
    for match in re.finditer(edge_pattern, dot_content):
        source_id = f"Resource{match.group(1)}"
        target_id = f"Resource{match.group(2)}"
        edges.append((source_id, target_id))
    
    if verbose:
        print(f"{Fore.YELLOW}Debug: Found {len(edges)} edges{Style.RESET_ALL}")
    
    # Step 3: Identify the stack resource (typically the root)
    stack_resource = None
    for node_id, label in nodes.items():
        if "::Stack::" in label:
            stack_resource = node_id
            break
    
    if not stack_resource and nodes:
        # If no stack resource found, use the first node
        stack_resource = next(iter(nodes.keys()))
    
    if not stack_resource:
        print(f"{Fore.RED}No resources found in the graph.{Style.RESET_ALL}")
        return
    
    # Step 4: Build a dependency tree
    # In Pulumi graphs, A -> B means A depends on B
    # For visualization, we want to show B as a parent of A
    dependency_map = {}
    for source, target in edges:
        # Add target as parent of source (source depends on target)
        if target not in dependency_map:
            dependency_map[target] = []
        if source not in dependency_map[target]:
            dependency_map[target].append(source)
    
    # Add all nodes to dependency_map if not already there
    for node in nodes:
        if node not in dependency_map:
            dependency_map[node] = []
    
    if verbose:
        print(f"{Fore.YELLOW}Debug: Built dependency map with {len(dependency_map)} entries{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Debug: Stack resource is {stack_resource}: {nodes.get(stack_resource, 'Unknown')}{Style.RESET_ALL}")
    
    # Step 5: Display the tree
    def print_node(node_id, prefix="", is_last=True, visited=None):
        if visited is None:
            visited = set()
        
        # Cycle detection
        if node_id in visited:
            if is_last:
                print(f"{prefix}└── {Fore.YELLOW}(cycle back to {nodes.get(node_id, node_id)}){Style.RESET_ALL}")
            else:
                print(f"{prefix}├── {Fore.YELLOW}(cycle back to {nodes.get(node_id, node_id)}){Style.RESET_ALL}")
            return
        
        visited.add(node_id)
        
        # Format node label
        node_label = nodes.get(node_id, node_id)
        display_name = node_label
        
        if node_label.startswith("urn:pulumi:"):
            parts = node_label.split("::")
            if len(parts) >= 5:
                resource_type = parts[-2]
                resource_name = parts[-1]
                display_name = f"{resource_name} ({resource_type})"
        
        # Get resource details
        detail_str = ""
        if resource_details:
            for resource in resources:
                if resource.get("urn") == node_label:
                    resource_id = resource.get("id", "")
                    if resource_id:
                        detail_str = f" - ID: {Fore.YELLOW}{resource_id}{Style.RESET_ALL}"
                    break
        
        # Print the node
        if not prefix:  # Root node
            print(f"{Fore.GREEN}{display_name}{Style.RESET_ALL}{detail_str}")
        else:
            if is_last:
                print(f"{prefix}└── {Fore.GREEN}{display_name}{Style.RESET_ALL}{detail_str}")
                new_prefix = prefix + "    "
            else:
                print(f"{prefix}├── {Fore.GREEN}{display_name}{Style.RESET_ALL}{detail_str}")
                new_prefix = prefix + "│   "
        
        # Print children
        children = dependency_map.get(node_id, [])
        for i, child in enumerate(children):
            print_node(child, new_prefix, i == len(children) - 1, visited.copy())
    
    # Start with the stack resource or any node that has dependencies
    if stack_resource in dependency_map:
        print_node(stack_resource)
    else:
        # Plan B: Just print all resources
        print(f"{Fore.YELLOW}Could not build proper tree structure. Listing all resources:{Style.RESET_ALL}")
        for node_id, label in nodes.items():
            display_name = label
            if label.startswith("urn:pulumi:"):
                parts = label.split("::")
                if len(parts) >= 5:
                    resource_type = parts[-2]
                    resource_name = parts[-1]
                    display_name = f"{resource_name} ({resource_type})"
            print(f"• {Fore.GREEN}{display_name}{Style.RESET_ALL}")

def get_stack_resources(work_dir: Path, stack_name: str, env: Dict) -> List[Dict[str, Any]]:
    """
    Get detailed information about stack resources.
    
    Args:
        work_dir: Working directory path
        stack_name: Name of the Pulumi stack
        env: Environment variables
    
    Returns:
        List of resource objects with details
    """
    try:
        # Export the stack to get resource details
        result = subprocess.run(
            ["pulumi", "stack", "export", "--stack", stack_name],
            cwd=str(work_dir),
            env=env,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            return []
        
        # Parse the JSON output
        stack_data = json.loads(result.stdout)
        
        # Extract resources
        resources = []
        if "deployment" in stack_data and "resources" in stack_data["deployment"]:
            resources = stack_data["deployment"]["resources"]
        
        return resources
    except Exception:
        return []

def process_pulumi_graph(
    dir_path: Path,
    build_path: Path,
    config: Config,
    graph_format: str = "dot",
    save_to_file: Optional[Path] = None,
    verbose: bool = False,
    tree_view: bool = False,
    resource_details: bool = False,
    pretty_print: bool = False,
) -> None:
    """Generate a dependency graph for a Pulumi stack.
    
    Args:
        dir_path: Path to the directory containing Pulumi project
        build_path: Path to build directory where temporary files are stored
        config: Configuration object with stack settings
        graph_format: Output format (dot, json, or yaml)
        save_to_file: Optional file path to save the graph output
        verbose: If True, show verbose output
        tree_view: If True, display as a console tree
        resource_details: If True, show detailed resource information
        pretty_print: If True, display in a formatted text view
    """
    if verbose:
        print(f"Processing Pulumi graph in: {dir_path}")
    
    # Get absolute build path
    abs_build_path = build_path.absolute()
    
    # Create build directory
    abs_build_path.mkdir(parents=True, exist_ok=True)
    pulumi_state_path = abs_build_path / ".pulumi"
    pulumi_state_path.mkdir(parents=True, exist_ok=True)
    
    # Set environment variables - ensure Pulumi uses the right state directory
    os.environ["PULUMI_HOME"] = str(pulumi_state_path)
    os.environ["PULUMI_CONFIG_PASSPHRASE"] = ""
    
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
            ["pulumi", "login", "file://"],
            ["pulumi", "login", "--local"]
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
                    print(f"{Fore.GREEN}Login successful{Style.RESET_ALL}")
                    break
                elif verbose:
                    print(f"{Fore.YELLOW}Login attempt failed{Style.RESET_ALL}")
            except Exception as e:
                if verbose:
                    print(f"{Fore.YELLOW}Login exception: {str(e)}{Style.RESET_ALL}")
        
        if not login_success:
            print(f"{Fore.RED}Failed to login to Pulumi. Cannot generate graph.{Style.RESET_ALL}")
            return
            
        # Check if stack exists
        try:
            if verbose:
                print(f"Checking if stack '{config.stack_name}' exists...")
            
            stack_ls_result = subprocess.run(
                ["pulumi", "stack", "ls"],
                cwd=str(abs_build_path),
                env=env,
                capture_output=True,
                text=True
            )
            
            stack_exists = False
            if stack_ls_result.returncode == 0:
                # Parse the output to look specifically for our stack
                lines = stack_ls_result.stdout.strip().split('\n')
                for line in lines:
                    if config.stack_name in line:
                        stack_exists = True
                        if verbose:
                            print(f"{Fore.GREEN}Found stack: {line.strip()}{Style.RESET_ALL}")
                        break
            
            if not stack_exists:
                print(f"{Fore.RED}Stack '{config.stack_name}' not found. Cannot generate graph.{Style.RESET_ALL}")
                return
                
        except Exception as e:
            print(f"{Fore.RED}Error checking for stack: {str(e)}{Style.RESET_ALL}")
            return
        
        # Select stack
        select_result = subprocess.run(
            ["pulumi", "stack", "select", config.stack_name],
            cwd=str(abs_build_path),
            env=env,
            capture_output=True,
            text=True
        )
        
        if select_result.returncode != 0:
            print(f"{Fore.RED}Failed to select stack '{config.stack_name}'. Error: {select_result.stderr.strip()}{Style.RESET_ALL}")
            return
        
        print(f"{Fore.CYAN}Generating resource dependency graph for stack '{config.stack_name}'...{Style.RESET_ALL}")
        
        # Get resource details if requested
        resources = []
        if resource_details or tree_view or pretty_print:
            resources = get_stack_resources(abs_build_path, config.stack_name, env)
            if verbose and resources:
                print(f"{Fore.GREEN}Retrieved details for {len(resources)} resources{Style.RESET_ALL}")
        
        # Create a temporary file for the graph output
        fd, temp_path = tempfile.mkstemp(suffix='.dot')
        os.close(fd)
        temp_file = Path(temp_path)
        
        # Generate the graph to the temporary file
        graph_cmd = ["pulumi", "stack", "graph", str(temp_file), "--stack", config.stack_name]
        
        result = subprocess.run(
            graph_cmd,
            cwd=str(abs_build_path),
            env=env,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"{Fore.RED}Failed to generate graph. Error: {result.stderr.strip() if result.stderr else 'Unknown error'}{Style.RESET_ALL}")
            # Clean up temporary file
            try:
                temp_file.unlink()
            except Exception:
                pass
            return
            
        # Read the DOT file
        try:
            with open(temp_file, 'r') as f:
                dot_content = f.read()
        except Exception as read_error:
            print(f"{Fore.RED}Error reading graph: {str(read_error)}{Style.RESET_ALL}")
            return
        
        # Handle output
        if save_to_file:
            # Copy the graph to the requested output file
            try:
                shutil.copy2(temp_file, save_to_file)
                print(f"{Fore.GREEN}Graph saved to: {save_to_file}{Style.RESET_ALL}")
                
                # Print visualization guidance
                print(f"{Fore.CYAN}To visualize the DOT graph, you can use tools like Graphviz:{Style.RESET_ALL}")
                print(f"  $ dot -Tpng {save_to_file} -o graph.png")
                print(f"  $ dot -Tsvg {save_to_file} -o graph.svg")
            except Exception as copy_error:
                print(f"{Fore.RED}Error saving graph to file: {str(copy_error)}{Style.RESET_ALL}")
        
        # Display as requested format
        if tree_view:
            # Use simplified tree display
            display_simple_tree(dot_content, resources, resource_details, verbose)
        elif pretty_print:
            # Use pretty formatter
            format_dot_output(dot_content)
        elif not save_to_file:
            # Just print the DOT content
            print("\n" + dot_content)
            print(f"\n{Fore.GREEN}Graph generated successfully{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Tip: Use --tree flag for a tree view or --pretty for a formatted view{Style.RESET_ALL}")
        
        # Clean up temporary file
        try:
            temp_file.unlink()
        except Exception:
            pass
            
    except Exception as e:
        print(f"{Fore.RED}Error: {str(e)}{Style.RESET_ALL}")
        raise

def graph_command(args: Namespace) -> None:
    """Execute the graph command."""
    # Ensure paths are absolute
    abs_work_dir = args.work_dir.absolute()
    abs_build_dir = abs_work_dir / "build"
    
    # Check available flags
    verbose = getattr(args, 'verbose', False)
    tree_view = getattr(args, 'tree', False)
    resource_details = getattr(args, 'details', False)
    pretty_print = getattr(args, 'pretty', False)
    
    # Print paths only in verbose mode
    if verbose:
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
    
    # Handle output file
    output_file = None
    if args.output:
        output_file = Path(args.output)
        if not output_file.is_absolute():
            output_file = abs_work_dir / output_file
    
    # Process the directory
    process_pulumi_graph(
        abs_work_dir, 
        abs_build_dir, 
        config, 
        args.format, 
        output_file,
        verbose,
        tree_view,
        resource_details,
        pretty_print
    )