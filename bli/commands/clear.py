import shutil
from argparse import Namespace
from pathlib import Path
from typing import Optional

from colorama import Fore, Style

def clear_lock_file(work_dir: Path, stack_name: Optional[str] = None) -> None:
    """Clear Pulumi lock files."""
    build_path = work_dir / "build"
    base_locks_path = build_path / ".pulumi" / "locks"
    
    if stack_name:
        # Path for specific stack's lock
        stack_lock_path = base_locks_path / "organization" / "test-stack" / stack_name
        
        if stack_lock_path.exists():
            shutil.rmtree(stack_lock_path)
            print(f"{Fore.GREEN}Successfully removed stack lock directory{Style.RESET_ALL}")
            print(f"Lock directory location: {stack_lock_path}")
        else:
            print(f"{Fore.YELLOW}No lock directory found for stack{Style.RESET_ALL}")
            print(f"Checked location: {stack_lock_path}")
    else:
        # If no stack specified, remove the entire locks directory
        if base_locks_path.exists():
            shutil.rmtree(base_locks_path)
            print(f"{Fore.GREEN}Successfully removed all locks directory{Style.RESET_ALL}")
            print(f"Locks directory location: {base_locks_path}")
        else:
            print(f"{Fore.YELLOW}No locks directory found{Style.RESET_ALL}")
            print(f"Checked location: {base_locks_path}")

def clear_command(args: Namespace) -> None:
    """Execute the clear command."""
    clear_lock_file(args.work_dir, args.stack_name)