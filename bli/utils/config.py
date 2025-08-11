import os
import subprocess
import sys
from pathlib import Path

import colorama
from colorama import Fore, Style

class Config:
    """Configuration class for BLI CLI."""
    
    def __init__(
        self,
        stack_name: str,
        project_id: str,
        proxy_address: str,
        proxy_port: str,
        use_local_auth: bool,
        no_proxy: bool,
        project_type: str,
    ):
        self.proxy_address = proxy_address
        self.proxy_port = proxy_port
        self.project_id = project_id
        self.stack_name = stack_name
        self.use_local_auth = use_local_auth
        self.no_proxy = no_proxy
        self.project_type = project_type

    @classmethod
    def from_cli(
        cls,
        stack_name: str,
        project_id: str,
        proxy_address: str,
        proxy_port: str,
        use_local_auth: bool,
        no_proxy: bool,
        staging: bool,
        service: bool,
    ) -> 'Config':
        """Create Config instance from CLI arguments."""
        if staging and service:
            raise ValueError("Cannot specify both --stg and --srv flags")
        
        project_type = "bi-stg"
        if staging:
            project_type = "bi-stg"
        elif service:
            project_type = "bi-srv"
        
        return cls(
            stack_name=stack_name,
            project_id=project_id,
            proxy_address=proxy_address,
            proxy_port=proxy_port,
            use_local_auth=use_local_auth,
            no_proxy=no_proxy,
            project_type=project_type,
        )

def get_stack_name(provided_name: str, work_dir: Path) -> str:
    """Get stack name from provided name or default."""
    if provided_name:
        return provided_name
    
    if (work_dir / "Pulumi.yaml").exists():
        return "bli-stack"
    
    print("Stack name is required. Please provide it using the -s flag.")
    sys.exit(1)

def setup_proxy(config: Config) -> None:
    """Set up HTTP proxy configuration."""
    if config.no_proxy:
        print(f"{Fore.YELLOW}Skipping proxy setup{Style.RESET_ALL}")
        return

    print(f"{Fore.GREEN}Setting Proxy using http://{config.proxy_address}:{config.proxy_port}{Style.RESET_ALL}")

    # Set environment variables
    os.environ["HTTP_PROXY"] = f"http://{config.proxy_address}:{config.proxy_port}"
    os.environ["HTTPS_PROXY"] = f"http://{config.proxy_address}:{config.proxy_port}"

    # Configure gcloud
    subprocess.run(["gcloud", "config", "set", "proxy/type", "http"], check=True)
    subprocess.run(["gcloud", "config", "set", "proxy/address", config.proxy_address], check=True)
    subprocess.run(["gcloud", "config", "set", "proxy/port", config.proxy_port], check=True)

def setup_gcloud(config: Config) -> None:
    """Set up Google Cloud authentication."""
    if config.use_local_auth:
        print(f"{Fore.GREEN}Using local authentication{Style.RESET_ALL}")
        return

    print(f"{Fore.GREEN}Setting up Google Cloud authentication{Style.RESET_ALL}")

    home_dir = Path.home()
    credentials_path = home_dir / ".config/gcloud/application_default_credentials.json"
    
    if credentials_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path)
    else:
        print(f"{Fore.RED}Local credentials not found. Run 'gcloud auth application-default login' first.{Style.RESET_ALL}")
        sys.exit(1)

    subprocess.run(["gcloud", "config", "set", "project", config.project_id], check=True)