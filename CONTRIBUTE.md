# BUILD.md - BLI CLI Development Setup

This guide explains how to set up a Python development environment to test and develop the BLI CLI tool.

## Prerequisites

Before setting up the development environment, ensure you have the following installed:

- **Python 3.7 or higher** (recommended: Python 3.9+)
- **Git** for version control
- **pip** (usually comes with Python)

## Quick Setup

```bash
# Clone the repository (if applicable)
git clone <repository-url>
cd bli

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package in development mode
pip install -e .

# Verify installation
bli --help
```

## Detailed Setup Instructions

### 1. Create Project Directory

```bash
# Create a new directory for the project
mkdir bli-cli
cd bli-cli
```

### 2. Set Up Python Virtual Environment

#### Using venv (Recommended)

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Linux/macOS:
source venv/bin/activate

# On Windows Command Prompt:
venv\Scripts\activate.bat

# On Windows PowerShell:
venv\Scripts\Activate.ps1
```

#### Using conda (Alternative)

```bash
# Create conda environment
conda create -n bli-dev python=3.9
conda activate bli-dev
```

### 3. Create Project Structure

Based on the provided code, create the following directory structure:

```
bli-cli/
├── bli/
│   ├── __init__.py
│   ├── cli.py
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── clear.py
│   │   ├── deploy.py
│   │   ├── destroy.py
│   │   ├── graph.py
│   │   ├── init.py
│   │   └── preview.py
│   └── utils/
│       ├── __init__.py
│       ├── config.py
│       ├── dependencies.py
│       ├── pulumi_utils.py
│       └── templating.py
├── setup.py
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

### 4. Create Requirements Files

#### requirements.txt (Production Dependencies)

```txt
pulumi>=3.0.0,<4.0.0
jinja2>=3.0.0,<4.0.0
colorama>=0.4.4,<1.0.0
```

#### requirements-dev.txt (Development Dependencies)

```txt
-r requirements.txt
pytest>=6.2.0
tox>=3.24.0
mypy>=0.910
black>=21.5b2
flake8>=3.9.0
pre-commit>=2.15.0
```

### 5. Install Dependencies

```bash
# Install production dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -r requirements-dev.txt

# Or install the package in development mode (recommended)
pip install -e .
```

### 6. Install External Dependencies

The BLI CLI requires external tools to function properly:

#### Install Pulumi CLI

```bash
# On Linux/macOS
curl -fsSL https://get.pulumi.com | sh
export PATH=$PATH:$HOME/.pulumi/bin

# On Windows (PowerShell)
iwr https://get.pulumi.com/install.ps1 -UseBasicParsing | iex

# Or using package managers:
# macOS with Homebrew
brew install pulumi

# Windows with Chocolatey
choco install pulumi

# Linux with Snap
sudo snap install pulumi --classic
```

#### Install Google Cloud SDK (Optional but recommended for GCP testing)

```bash
# Follow instructions at: https://cloud.google.com/sdk/docs/install

# Quick install on Linux/macOS:
curl https://sdk.cloud.google.com | bash
exec -l $SHELL

# Initialize gcloud
gcloud init
```

### 7. Verify Installation

```bash
# Check Python environment
python --version
pip list

# Check external dependencies
pulumi version
gcloud version  # If installed

# Test BLI CLI
bli --help
bli depend --check-only
```

## Development Workflow

### 1. Making Code Changes

The project is installed in "editable" mode (`pip install -e .`), so changes to the source code will be immediately available when running the `bli` command.

### 2. Testing Changes

```bash
# Run the CLI to test changes
bli --help

# Test specific commands
bli depend --check-only
bli init -s test-stack -w ./test-project

# Test with verbose output
bli deploy -s test-stack -i my-project-id -v
```

### 3. Code Quality Tools

```bash
# Format code with Black
black bli/

# Check code style with flake8
flake8 bli/

# Type checking with mypy
mypy bli/

# Run all checks
python -m pytest  # If you add tests
```

## Project Structure Explanation

- **`bli/`** - Main package directory
  - **`cli.py`** - Main CLI entry point and argument parsing
  - **`commands/`** - Individual command implementations
    - `deploy.py` - Infrastructure deployment
    - `preview.py` - Preview changes
    - `destroy.py` - Destroy infrastructure
    - `init.py` - Initialize new stacks
    - `clear.py` - Clear lock files
    - `graph.py` - Generate dependency graphs
  - **`utils/`** - Utility modules
    - `config.py` - Configuration management
    - `dependencies.py` - Dependency checking and installation
    - `pulumi_utils.py` - Pulumi command utilities
    - `templating.py` - Jinja2 template rendering

## Testing the CLI

### 1. Initialize Dependencies

```bash
# Check and install required dependencies
bli depend
```

### 2. Create a Test Project

```bash
# Create a test directory
mkdir test-infrastructure
cd test-infrastructure

# Initialize a new stack
bli init -s development-stack
```

### 3. Test Basic Operations

```bash
# Preview (safe - doesn't make changes)
bli preview -s development-stack -i your-gcp-project-id

# Deploy (creates actual resources - be careful!)
bli deploy -s development-stack -i your-gcp-project-id

# Generate dependency graph
bli graph -s development-stack -i your-gcp-project-id --tree

# Clean up (destroys resources)
bli destroy -s development-stack -i your-gcp-project-id
```

## Troubleshooting

### Common Issues

1. **Virtual environment not activated**
   ```bash
   # Make sure you see (venv) in your prompt
   source venv/bin/activate  # Linux/macOS
   venv\Scripts\activate     # Windows
   ```

2. **Import errors**
   ```bash
   # Reinstall in development mode
   pip install -e .
   ```

3. **Pulumi not found**
   ```bash
   # Check PATH or reinstall Pulumi
   which pulumi
   bli depend
   ```

4. **Permission errors**
   ```bash
   # On Linux/macOS, you might need to make scripts executable
   chmod +x venv/bin/bli
   ```

### Environment Variables

The CLI uses several environment variables:

```bash
# Pulumi configuration
export PULUMI_CONFIG_PASSPHRASE=""
export PULUMI_SKIP_UPDATE_CHECK="true"

# Optional: Proxy settings (if needed)
export HTTP_PROXY="http://proxy.example.com:8080"
export HTTPS_PROXY="http://proxy.example.com:8080"
```

## Development Tips

1. **Use verbose mode** (`-v`) when testing to see detailed output
2. **Start with preview commands** before deploy to avoid creating unwanted resources
3. **Use separate GCP projects** for testing to avoid conflicts
4. **Keep backups** of important Pulumi state files
5. **Test in isolated directories** to avoid conflicts with existing projects

## Next Steps

Once your environment is set up:

1. Read through the source code to understand the architecture
2. Try the example commands with your own GCP project
3. Extend the functionality by adding new commands or features
4. Consider adding unit tests for better reliability

## Support

If you encounter issues:

1. Check the verbose output with `-v` flag
2. Verify all dependencies are installed with `bli depend --check-only`
3. Ensure your virtual environment is activated
4. Check the Pulumi and GCP CLI documentation for external tool issues