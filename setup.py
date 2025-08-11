from setuptools import setup, find_packages

# Read the long description from README.md
try:
    with open("README.md", "r", encoding="utf-8") as fh:
        long_description = fh.read()
except FileNotFoundError:
    long_description = "BLI CLI - A Pulumi-based Infrastructure Management Tool"

setup(
    name="bli",
    version="0.1.0",
    
    # Metadata
    author="terekete",
    author_email="gates.mark@gmail.com",
    description="BLI CLI - A Pulumi-based Infrastructure Management Tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/bli",
    
    # Packaging
    packages=find_packages(),
    
    # Python version and platform support
    python_requires='>=3.7,<4.0',
    
    # Dependencies
    install_requires=[
        "pulumi>=3.0.0,<4.0.0",
        "jinja2>=3.0.0,<4.0.0",
        "colorama>=0.4.4,<1.0.0",
    ],
    
    # Optional dependencies (extras)
    extras_require={
        'dev': [
            'pytest>=6.2.0',
            'tox>=3.24.0',
            'mypy>=0.910',
            'black>=21.5b2',
        ],
        'docs': [
            'sphinx>=4.0.0',
            'sphinx-rtd-theme>=0.5.2',
        ],
    },
    
    # Entry points for CLI
    entry_points={
        "console_scripts": [
            "bli=bli.cli:main",
        ],
    },
    
    # Metadata for PyPI
    classifiers=[
        # Development Status
        "Development Status :: 3 - Alpha",
        
        # Intended Audience
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        
        # License
        "License :: OSI Approved :: MIT License",
        
        # Operating System
        "Operating System :: OS Independent",
        
        # Python Versions
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        
        # Categories
        "Topic :: Software Development :: Build Tools",
        "Topic :: System :: Systems Administration",
        "Topic :: Utilities",
    ],
    
    # Package data (include non-Python files)
    package_data={
        "bli": ["*.yaml", "*.yml"],
    },
    
    # Keyword tags for discoverability
    keywords="infrastructure pulumi cli devops deployment automation gcp",
)