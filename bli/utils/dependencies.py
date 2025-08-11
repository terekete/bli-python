import os
import subprocess
import sys
from shutil import which

import colorama
from colorama import Fore, Style

def check_dependencies(quiet: bool = False) -> bool:
    """
    Check if required dependencies are installed.
    
    Args:
        quiet: If True, don't print confirmation messages for installed dependencies
    
    Returns:
        bool: True if all dependencies are installed, False otherwise
    """
    if not quiet:
        print("Checking dependencies...")
    
    # Check for Pulumi first
    pulumi_found = False
    if which("pulumi"):
        try:
            result = subprocess.run(["pulumi", "version"], check=False, capture_output=True, text=True)
            if result.returncode == 0:
                pulumi_found = True
                if not quiet:
                    print(f"{Fore.GREEN}✓{Style.RESET_ALL} Pulumi CLI is installed")
            else:
                # Try another command to verify Pulumi is working
                about_result = subprocess.run(["pulumi", "about"], check=False, capture_output=True, text=True)
                if about_result.returncode == 0:
                    pulumi_found = True
                    if not quiet:
                        print(f"{Fore.GREEN}✓{Style.RESET_ALL} Pulumi CLI is installed")
        except Exception:
            pulumi_found = False
    
    if not pulumi_found:
        if not quiet:
            print(f"{Fore.RED}✗{Style.RESET_ALL} Pulumi CLI is not installed.")
            print(f"Please run 'bli init' to set up your environment.")
        return False
    
    # Check other dependencies
    gcloud_found = False
    if which("gcloud"):
        try:
            result = subprocess.run(["gcloud", "version"], check=False, capture_output=True, text=True)
            if result.returncode == 0:
                gcloud_found = True
                if not quiet:
                    print(f"{Fore.GREEN}✓{Style.RESET_ALL} Google Cloud SDK is installed")
        except Exception:
            gcloud_found = False
    
    if not gcloud_found:
        if not quiet:
            print(f"{Fore.RED}✗{Style.RESET_ALL} Google Cloud SDK is not installed.")
            print(f"Please run 'bli init' to set up your environment.")
        return False
    
    return True

def install_dependencies() -> bool:
    """
    Install all required dependencies for BLI.
    This is intended to be called by the 'init' command.
    
    Returns:
        bool: True if all dependencies were installed successfully, False otherwise
    """
    print("Setting up BLI environment...")
    
    # Install Pulumi
    pulumi_installed = install_pulumi()
    if not pulumi_installed:
        return False
    
    # Check Google Cloud SDK
    gcloud_found = False
    if which("gcloud"):
        try:
            result = subprocess.run(["gcloud", "version"], check=False, capture_output=True, text=True)
            if result.returncode == 0:
                gcloud_found = True
                print(f"{Fore.GREEN}✓{Style.RESET_ALL} Google Cloud SDK is installed")
        except Exception:
            gcloud_found = False
    
    if not gcloud_found:
        print(f"{Fore.RED}✗{Style.RESET_ALL} Google Cloud SDK is not installed.")
        print("Installing Google Cloud SDK...")
        
        try:
            if sys.platform.startswith('linux') or sys.platform == 'darwin':
                # Instructions for Linux/macOS installation
                print(f"{Fore.YELLOW}Please install Google Cloud SDK manually by following the instructions at:{Style.RESET_ALL}")
                print("https://cloud.google.com/sdk/docs/install")
                return False
            elif sys.platform == 'win32':
                # Instructions for Windows installation
                print(f"{Fore.YELLOW}Please install Google Cloud SDK manually by following the instructions at:{Style.RESET_ALL}")
                print("https://cloud.google.com/sdk/docs/install")
                return False
        except Exception as e:
            print(f"{Fore.RED}Failed to install Google Cloud SDK: {str(e)}{Style.RESET_ALL}")
            return False
    
    print(f"{Fore.GREEN}All dependencies are installed successfully!{Style.RESET_ALL}")
    return True

def install_pulumi() -> bool:
    """Install Pulumi CLI if not already installed."""
    # First check if Pulumi is available in PATH
    if which("pulumi"):
        # Check if it works properly
        try:
            result = subprocess.run(["pulumi", "version"], check=False, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"{Fore.GREEN}✓{Style.RESET_ALL} Pulumi CLI is already installed")
                return True
            else:
                # Try another command to verify Pulumi is working
                about_result = subprocess.run(["pulumi", "about"], check=False, capture_output=True, text=True)
                if about_result.returncode == 0:
                    print(f"{Fore.GREEN}✓{Style.RESET_ALL} Pulumi CLI is already installed")
                    return True
                print(f"{Fore.YELLOW}Pulumi found but version check failed: {result.stderr.strip() if result.stderr else 'Unknown error'}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}Pulumi found but encountered an error: {str(e)}{Style.RESET_ALL}")
    else:
        print("Pulumi CLI not found in PATH.")
        
    # If we get here, we need to install Pulumi
    print("Installing Pulumi CLI...")
    
    try:
        if sys.platform.startswith('linux'):
            subprocess.run(["curl", "-fsSL", "https://get.pulumi.com", "|", "sh"], check=True, shell=True)
            # Add to PATH for the current session
            pulumi_bin_path = os.path.expanduser("~/.pulumi/bin")
            if os.path.exists(pulumi_bin_path):
                os.environ["PATH"] = f"{pulumi_bin_path}:{os.environ.get('PATH', '')}"
                
        elif sys.platform == 'darwin':
            # Check if Homebrew is available
            if which("brew"):
                subprocess.run(["brew", "install", "pulumi"], check=True)
            else:
                subprocess.run(["curl", "-fsSL", "https://get.pulumi.com", "|", "sh"], check=True, shell=True)
                # Add to PATH for the current session
                pulumi_bin_path = os.path.expanduser("~/.pulumi/bin")
                if os.path.exists(pulumi_bin_path):
                    os.environ["PATH"] = f"{pulumi_bin_path}:{os.environ.get('PATH', '')}"
                    
        elif sys.platform == 'win32':
            if which("choco"):
                subprocess.run(["choco", "install", "pulumi", "-y"], check=True, shell=True)
            else:
                # PowerShell installer as fallback
                ps_cmd = "(New-Object System.Net.WebClient).DownloadString('https://get.pulumi.com/install.ps1') | powershell -Command -"
                subprocess.run(["powershell", "-Command", ps_cmd], check=True)
                # Add to PATH for current session
                pulumi_bin_path = os.path.join(os.environ.get('USERPROFILE', ''), '.pulumi', 'bin')
                if os.path.exists(pulumi_bin_path):
                    os.environ["PATH"] = f"{pulumi_bin_path};{os.environ.get('PATH', '')}"
        else:
            print(f"{Fore.RED}Unsupported platform: {sys.platform}{Style.RESET_ALL}")
            return False
        
        # Verify installation with a simple command
        if which("pulumi"):
            verify_result = subprocess.run(["pulumi", "about"], check=False, capture_output=True, text=True)
            if verify_result.returncode == 0:
                print(f"{Fore.GREEN}✓{Style.RESET_ALL} Pulumi CLI installed successfully")
                return True
            else:
                print(f"{Fore.RED}Pulumi installation verification failed.{Style.RESET_ALL}")
                if verify_result.stderr:
                    print(f"Error: {verify_result.stderr.strip()}")
                return False
        else:
            print(f"{Fore.RED}Pulumi installation completed but CLI not found in PATH.{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}You may need to restart your terminal or add Pulumi to your PATH manually.{Style.RESET_ALL}")
            return False
            
    except subprocess.SubprocessError as e:
        print(f"{Fore.RED}Failed to install Pulumi CLI: {str(e)}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Please install Pulumi manually from https://www.pulumi.com/docs/get-started/install/{Style.RESET_ALL}")
        return False