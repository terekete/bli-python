#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path
from io import StringIO

import colorama
from colorama import Fore, Style

from bli.commands.clear import clear_command
from bli.commands.deploy import deploy_command
from bli.commands.destroy import destroy_command
from bli.commands.init import init_command
from bli.commands.preview import preview_command
from bli.commands.graph import graph_command
from bli.utils import dependencies

# Initialize colorama
colorama.init()

ASCII_ART = """
BLI Command Line
"""

# Custom argument parser that provides colorized help output
class BLIArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        """Print a cleaner error message for missing arguments"""
        # Print the ASCII art first
        print(f"{Fore.MAGENTA}{ASCII_ART}{Style.RESET_ALL}")
        
        command = os.path.basename(sys.argv[0])
        
        if "required" in message:
            # Customize the "required argument" message
            print(f"{Fore.RED}Error: Missing required arguments{Style.RESET_ALL}")
            print(f"\nTo see usage information, run: {Fore.CYAN}{self.prog} --help{Style.RESET_ALL}\n")
        else:
            # For other errors, use a cleaner format but keep the original message
            print(f"{Fore.RED}Error: {message}{Style.RESET_ALL}")
            print(f"\nTo see usage information, run: {Fore.CYAN}{self.prog} --help{Style.RESET_ALL}\n")
        
        sys.exit(1)
    
    def print_help(self, file=None):
        """Override print_help to colorize the output"""
        # Capture the standard help output
        help_io = StringIO()
        super().print_help(help_io)
        help_text = help_io.getvalue()
        
        # Colorize different parts of the help text
        lines = help_text.split('\n')
        colorized_lines = []
        
        for line in lines:
            if line.startswith('usage:'):
                # Colorize usage line
                parts = line.split(' ', 1)
                if len(parts) > 1:
                    colorized_lines.append(f"{Fore.YELLOW}{parts[0]}{Style.RESET_ALL} {parts[1]}")
                else:
                    colorized_lines.append(f"{Fore.YELLOW}{line}{Style.RESET_ALL}")
            elif ':' in line and line[0] != ' ':
                # Colorize section headers (positional arguments, optional arguments)
                colorized_lines.append(f"{Fore.GREEN}{line}{Style.RESET_ALL}")
            elif line.strip().startswith('-'):
                # Colorize argument flags
                parts = line.split('  ', 1)
                if len(parts) > 1:
                    indent = ' ' * (len(line) - len(line.lstrip()))
                    flags = parts[0].strip()
                    desc = parts[1]
                    
                    # Check if this is a required argument
                    if "(required)" in desc:
                        desc_colored = desc.replace("(required)", f"{Fore.RED}(required){Style.RESET_ALL}")
                        colorized_lines.append(f"{indent}{Fore.CYAN}{flags}{Style.RESET_ALL}  {desc_colored}")
                    else:
                        colorized_lines.append(f"{indent}{Fore.CYAN}{flags}{Style.RESET_ALL}  {desc}")
                else:
                    colorized_lines.append(line)
            elif line.startswith('Example:'):
                # Colorize examples
                parts = line.split(':', 1)
                if len(parts) > 1:
                    colorized_lines.append(f"{Fore.MAGENTA}{parts[0]}:{Style.RESET_ALL}{parts[1]}")
                else:
                    colorized_lines.append(line)
            else:
                # Leave other lines unchanged
                colorized_lines.append(line)
        
        # Print the colorized help text
        print('\n'.join(colorized_lines), file=file or sys.stdout)

class BLIHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Custom help formatter to tweak the help output appearance"""
    def __init__(self, prog):
        super().__init__(prog, max_help_position=35, width=100)

def depend_command(args: argparse.Namespace) -> None:
    """Execute the depend command to check and install dependencies."""
    if args.check_only:
        # Only check dependencies without installing
        if dependencies.check_dependencies(quiet=False):
            print(f"{Fore.GREEN}All required dependencies are installed and working correctly.{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}Some dependencies are missing. Run 'bli depend' without --check-only to install them.{Style.RESET_ALL}")
            sys.exit(1)
    else:
        # Check and install dependencies
        if not dependencies.install_dependencies():
            print(f"{Fore.RED}Failed to install all required dependencies.{Style.RESET_ALL}")
            sys.exit(1)
        print(f"{Fore.GREEN}All dependencies are installed and ready to use.{Style.RESET_ALL}")

def main() -> None:
    """Main function for the BLI CLI."""
    # Set up environment
    os.environ["PULUMI_CONFIG_PASSPHRASE"] = ""
    
    # Set up argument parser with custom error handling
    parser = BLIArgumentParser(
        description=f"{Fore.BLUE}Bare Layer Infrastructure CLI - A wrapper for Pulumi to manage GCP infrastructure{Style.RESET_ALL}",
        epilog=f"{Fore.BLUE}For more information, visit https://github.com/yourusername/bli{Style.RESET_ALL}",
        formatter_class=BLIHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Deploy command
    deploy_parser = subparsers.add_parser(
        "deploy", 
        help="Deploy infrastructure",
        description=f"{Fore.BLUE}Deploy your infrastructure using Pulumi. This will create or update resources as defined in your Pulumi project.{Style.RESET_ALL}",
        epilog=f"{Fore.MAGENTA}Example:{Style.RESET_ALL} bli deploy -s my-stack -i my-gcp-project",
        formatter_class=BLIHelpFormatter
    )
    deploy_parser.add_argument("-s", "--stack-name", help="Stack name to deploy")
    deploy_parser.add_argument("-i", "--project-id", required=True, help="GCP Project ID (required)")
    deploy_parser.add_argument("-r", "--proxy-address", default="proxy.telus.com", help="Proxy address (default: proxy.telus.com)")
    deploy_parser.add_argument("-o", "--proxy-port", default="8080", help="Proxy port (default: 8080)")
    deploy_parser.add_argument("-l", "--use-local-auth", action="store_true", help="Use local authentication")
    deploy_parser.add_argument("-n", "--no-proxy", action="store_true", help="Skip proxy setup")
    deploy_parser.add_argument("-w", "--work-dir", type=Path, default=Path("."), help="Working directory (default: current directory)")
    deploy_parser.add_argument("--stg", action="store_true", help="Use staging environment")
    deploy_parser.add_argument("--srv", action="store_true", help="Use service environment")
    deploy_parser.add_argument("-v", "--verbose", action="store_true", help="Show verbose output including template details")
    
    # Preview command
    preview_parser = subparsers.add_parser(
        "preview", 
        help="Preview infrastructure changes",
        description=f"{Fore.BLUE}Preview changes to your infrastructure without deploying. Shows what would be created, updated, or deleted.{Style.RESET_ALL}",
        epilog=f"{Fore.MAGENTA}Example:{Style.RESET_ALL} bli preview -s my-stack -i my-gcp-project",
        formatter_class=BLIHelpFormatter
    )
    preview_parser.add_argument("-s", "--stack-name", help="Stack name to preview")
    preview_parser.add_argument("-i", "--project-id", required=True, help="GCP Project ID (required)")
    preview_parser.add_argument("-r", "--proxy-address", default="proxy.telus.com", help="Proxy address (default: proxy.telus.com)")
    preview_parser.add_argument("-o", "--proxy-port", default="8080", help="Proxy port (default: 8080)")
    preview_parser.add_argument("-l", "--use-local-auth", action="store_true", help="Use local authentication")
    preview_parser.add_argument("-n", "--no-proxy", action="store_true", help="Skip proxy setup")
    preview_parser.add_argument("-w", "--work-dir", type=Path, default=Path("."), help="Working directory (default: current directory)")
    preview_parser.add_argument("--stg", action="store_true", help="Use staging environment")
    preview_parser.add_argument("--srv", action="store_true", help="Use service environment")
    preview_parser.add_argument("-v", "--verbose", action="store_true", help="Show verbose output including template details")
    
    # Init command
    init_parser = subparsers.add_parser(
        "init", 
        help="Initialize a new stack",
        description=f"{Fore.BLUE}Initialize a new Pulumi stack with YAML configuration. This creates the necessary Pulumi project files and configures a local stack.{Style.RESET_ALL}",
        epilog=f"{Fore.MAGENTA}Example:{Style.RESET_ALL} bli init -s dev-stack -w ./my_infrastructure",
        formatter_class=BLIHelpFormatter
    )
    init_parser.add_argument(
        "-s", "--stack-name", 
        required=True, 
        help="Name of the stack to create (required)"
    )
    init_parser.add_argument(
        "-w", "--work-dir", 
        type=Path, 
        default=Path("."), 
        help="Working directory for the stack (defaults to current directory)"
    )
    
    # Destroy command
    destroy_parser = subparsers.add_parser(
        "destroy", 
        help="Destroy infrastructure",
        description=f"{Fore.BLUE}Destroy all resources in the specified stack. This will permanently remove all managed resources.{Style.RESET_ALL}",
        epilog=f"{Fore.MAGENTA}Example:{Style.RESET_ALL} bli destroy -s my-stack -i my-gcp-project",
        formatter_class=BLIHelpFormatter
    )
    destroy_parser.add_argument("-s", "--stack-name", help="Stack name to destroy")
    destroy_parser.add_argument("-i", "--project-id", required=True, help="GCP Project ID (required)")
    destroy_parser.add_argument("-r", "--proxy-address", default="proxy.telus.com", help="Proxy address (default: proxy.telus.com)")
    destroy_parser.add_argument("-o", "--proxy-port", default="8080", help="Proxy port (default: 8080)")
    destroy_parser.add_argument("-l", "--use-local-auth", action="store_true", help="Use local authentication")
    destroy_parser.add_argument("-n", "--no-proxy", action="store_true", help="Skip proxy setup")
    destroy_parser.add_argument("-w", "--work-dir", type=Path, default=Path("."), help="Working directory (default: current directory)")
    destroy_parser.add_argument("--stg", action="store_true", help="Use staging environment")
    destroy_parser.add_argument("--srv", action="store_true", help="Use service environment")
    destroy_parser.add_argument("-v", "--verbose", action="store_true", help="Show verbose output including template details")
    
    # Clear command
    clear_parser = subparsers.add_parser(
        "clear", 
        help="Clear Pulumi lock files",
        description=f"{Fore.BLUE}Clear Pulumi lock files when operations get stuck. Useful for resolving 'stack is already being updated' errors.{Style.RESET_ALL}",
        epilog=f"{Fore.MAGENTA}Example:{Style.RESET_ALL} bli clear -s my-stack -w ./my_infrastructure",
        formatter_class=BLIHelpFormatter
    )
    clear_parser.add_argument("-w", "--work-dir", type=Path, default=Path("."), help="Working directory (default: current directory)")
    clear_parser.add_argument("-s", "--stack-name", help="Stack name for which to clear locks")
    
    # Depend command
    depend_parser = subparsers.add_parser(
        "depend", 
        help="Check and install dependencies",
        description=f"{Fore.BLUE}Check for required dependencies (Pulumi, GCP CLI) and install them if missing.{Style.RESET_ALL}",
        epilog=f"{Fore.MAGENTA}Example:{Style.RESET_ALL} bli depend --check-only",
        formatter_class=BLIHelpFormatter
    )
    depend_parser.add_argument("--check-only", action="store_true", help="Only check dependencies without installing")
    
    # Graph command
    graph_parser = subparsers.add_parser(
        "graph", 
        help="Generate dependency graph for infrastructure",
        description=f"{Fore.BLUE}Generate a visual representation of your infrastructure resources and their dependencies using Pulumi's graph capabilities.{Style.RESET_ALL}",
        epilog=f"{Fore.MAGENTA}Example:{Style.RESET_ALL} bli graph -s my-stack -i my-gcp-project -t -d",
        formatter_class=BLIHelpFormatter
    )
    graph_parser.add_argument("-s", "--stack-name", help="Stack name to graph")
    graph_parser.add_argument("-i", "--project-id", required=True, help="GCP Project ID (required)")
    graph_parser.add_argument("-r", "--proxy-address", default="proxy.telus.com", help="Proxy address (default: proxy.telus.com)")
    graph_parser.add_argument("-p", "--proxy-port", default="8080", help="Proxy port (default: 8080)")  # Changed from -o to -p
    graph_parser.add_argument("-l", "--use-local-auth", action="store_true", help="Use local authentication")
    graph_parser.add_argument("-n", "--no-proxy", action="store_true", help="Skip proxy setup")
    graph_parser.add_argument("-w", "--work-dir", type=Path, default=Path("."), help="Working directory (default: current directory)")
    graph_parser.add_argument("--stg", action="store_true", help="Use staging environment")
    graph_parser.add_argument("--srv", action="store_true", help="Use service environment")
    graph_parser.add_argument("-v", "--verbose", action="store_true", help="Show verbose output including template details")
    graph_parser.add_argument("-f", "--format", default="dot", choices=["dot", "json", "yaml"], help="Graph output format (default: dot)")
    graph_parser.add_argument("--output", help="Save graph to file instead of printing to console")
    graph_parser.add_argument("-t", "--tree", action="store_true", help="Display graph as a console-friendly tree view")
    graph_parser.add_argument("-d", "--details", action="store_true", help="Show detailed resource information in the tree view")
    graph_parser.add_argument("--pretty", action="store_true", help="Format the graph output in a readable text format")

    # Parse arguments
    args = parser.parse_args()
    
    # Print ASCII art (only if we didn't error out in argument parsing)
    print(f"{Fore.MAGENTA}{ASCII_ART}{Style.RESET_ALL}")
    
    # Execute command
    try:
        if args.command == "init":
            # For init command, install all dependencies
            if not dependencies.install_dependencies():
                sys.exit(1)
            init_command(args)
        elif args.command == "depend":
            # Handle dependency management
            depend_command(args)
        elif args.command is None:
            # No command provided, show help
            parser.print_help()
            sys.exit(1)
        else:
            # For all other commands, just check dependencies
            if not dependencies.check_dependencies(quiet=False):
                print(f"{Fore.YELLOW}Some dependencies are missing. Run 'bli depend' to install them.{Style.RESET_ALL}")
                sys.exit(1)
                
            # Execute the appropriate command
            if args.command == "deploy":
                deploy_command(args)
            elif args.command == "preview":
                preview_command(args)
            elif args.command == "destroy":
                destroy_command(args)
            elif args.command == "clear":
                clear_command(args)
            elif args.command == "graph":
                graph_command(args)
            else:
                parser.print_help()
                sys.exit(1)
    except Exception as e:
        print(f"{Fore.RED}Error: {str(e)}{Style.RESET_ALL}")
        sys.exit(1)

if __name__ == "__main__":
    main()