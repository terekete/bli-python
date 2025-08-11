## Project structure
```

bli/
├── __init__.py
├── __main__.py
├── cli.py
├── commands/
│   ├── __init__.py
│   ├── deploy.py
│   ├── preview.py
│   ├── init.py
│   ├── destroy.py
│   └── clear.py
├── utils/
│   ├── __init__.py
│   ├── config.py
│   ├── dependencies.py
│   └── templating.py
├── setup.py
├── pyproject.toml
└── README.md

```

# BLI CLI

Bare Layer Infrastructure Command Line Interface

## Overview

BLI CLI is a command line tool for managing infrastructure using Pulumi. It provides a simplified interface for deploying, previewing, and destroying infrastructure stacks.

## Installation

You can install the BLI CLI directly from PyPI:

```bash
pip install bli
```

Or, install it from source:

```bash
git clone https://github.com/yourusername/bli.git
cd bli-cli
pip install -e .
```

## Requirements

- Python 3.7+
- Google Cloud SDK
- Pulumi CLI (will be installed automatically if missing)

## Usage

### Initialize a new stack

```bash
bli init -s my-stack -w /path/to/work/dir
```

### Deploy infrastructure

```bash
bli deploy -s my-stack -i my-project-id -w /path/to/work/dir
```

### Preview changes

```bash
bli preview -s my-stack -i my-project-id -w /path/to/work/dir
```

### Destroy infrastructure

```bash
bli destroy -s my-stack -i my-project-id -w /path/to/work/dir
```

### Clear Pulumi locks

```bash
bli clear -s my-stack -w /path/to/work/dir
```

## Command Line Options

All commands support the following options:

- `-w`, `--work-dir`: Working directory (default: current directory)
- `-s`, `--stack-name`: Stack name

Deploy, preview, and destroy commands also support:

- `-i`, `--project-id`: Google Cloud project ID (required)
- `-r`, `--proxy-address`: Proxy address (default: proxy.telus.com)
- `-o`, `--proxy-port`: Proxy port (default: 8080)
- `-l`, `--use-local-auth`: Use local authentication
- `-n`, `--no-proxy`: Skip proxy setup
- `--stg`: Use staging environment
- `--srv`: Use service environment

## Development

### Setup development environment

```bash
# Clone the repository
git clone https://github.com/yourusername/bli.git
cd bli

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev]"
```

### Run tests

```bash
pytest
```

## License

MIT

## Other commands
find . -type f -name "*.py" \
  -not -path "*/\.*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/venv/*" \
  -not -path "*/env/*" \
  -not -path "*/tmp/*" \
  -print0 | xargs -0 -I{} sh -c 'echo "// {}" && cat "{}"' > merged.txt
