## Install build tools
pip install build

## Build the package
python -m build
pip install -e .

## Dataset Example

### Initialize Stack
bli init -s mock-dataset -w ./mock-dataset

### Preview Resource
bli preview -s mock-dataset2 -w ./mock-dataset2 -n -l -i mock-wb-lab-43744c -v

### Deploy Resource
bli deploy -s mock-dataset2 -w ./mock-dataset2 -n -l -i mock-wb-lab-43744c -v

### Destroy Resources
bli destroy -s mock-dataset2 -w ./mock-dataset2 -n -l -i mock-wb-lab-43744c -v

### Clear Locks
bli clear -s mock-dataset2 -w ./mock-dataset

### Graph
bli graph -s mock-dataset2 -w ./mock-dataset2 -n -l -i mock-wb-lab-43744c -v
