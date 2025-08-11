import os
import re
from pathlib import Path

import jinja2
from colorama import Fore, Style

from bli.utils.config import Config

def render_template(template_path: Path, output_path: Path, config: Config, verbose: bool = False) -> None:
    """Render a Jinja2 template with configuration and process Pulumi variable references.
    
    Args:
        template_path: Path to the template file
        output_path: Path where the rendered file should be saved
        config: Configuration object with values for substitution
        verbose: If True, print detailed debug information
    """
    template_content = template_path.read_text()
    
    # Create Jinja2 environment with trim_blocks and lstrip_blocks
    env = jinja2.Environment(
        trim_blocks=True,    # Remove first newline after a block
        lstrip_blocks=True,  # Strip tabs and spaces from the beginning of a line to the start of a block
        keep_trailing_newline=True  # Keep the trailing newline when rendering templates
    )
    template = env.from_string(template_content)
    
    # Prepare context
    context = {
        "VAR": dict(os.environ),
        "environment": "dev",
        "env": "dev",
        "project_type": config.project_type,
        "project": config.project_id,  # Add the project ID from config
        "location": "northamerica-northeast1",   # Add location from config
    }
    
    # Render template with Jinja2
    rendered = template.render(**context)
    
    # Process Pulumi variable references like ${project}
    # This replaces ${variable} with the actual value if it exists in our context
    def replace_var(match):
        var_name = match.group(1)
        if var_name in context:
            return str(context[var_name])
        return match.group(0)  # Keep as is if not found
    
    # Replace ${var} references with actual values
    rendered = re.sub(r'\$\{(\w+)\}', replace_var, rendered)
    
    # Remove consecutive empty lines to clean up the output
    rendered = re.sub(r'\n\s*\n\s*\n+', '\n\n', rendered)
    
    # Print debug information only in verbose mode
    if verbose:
        print("\n" + "="*80)
        print(f"{Fore.GREEN}▶ STARTING TEMPLATE RENDERING PROCESS{Style.RESET_ALL}")
        print("="*80 + "\n")

        print(f"{Fore.BLUE}📄 TEMPLATE SOURCE:{Style.RESET_ALL}")
        print("─"*50)
        print(template_content)
        print("─"*50 + "\n")

        print(f"{Fore.BLUE}🔧 ENVIRONMENT VARIABLES:{Style.RESET_ALL}")
        print("─"*50)
        print(f"  Project Type: {config.project_type}")
        print(f"  Project ID:   {config.project_id}")
        print(f"  Location:     northamerica-northeast1")
        print(f"  Environment:  dev")
        print("─"*50 + "\n")

        print(f"{Fore.BLUE}🔄 RENDERED OUTPUT:{Style.RESET_ALL}")
        print("─"*50)
        print(rendered)
        print("─"*50 + "\n")

        print("="*80)
        print(f"{Fore.GREEN}✓ TEMPLATE RENDERING COMPLETE{Style.RESET_ALL}")
        print("="*80 + "\n")
    else:
        # Just print a simple message in non-verbose mode
        print(f"{Fore.GREEN}Rendered template: {template_path.name} → {output_path.name}{Style.RESET_ALL}")

    # Write output
    output_path.write_text(rendered)