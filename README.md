# `submit`

A lightweight job submission tool that supports both local execution and SLURM cluster submissions. It uses Jinja2 templates and YAML configuration to manage job parameters and execution.

## Requirements
- Python 3.6+
- Jinja2
- PyYAML

> This tool is designed to run on the ML Cloud without the need for a python environment or package installations.

## Configuration

The tool uses a YAML configuration file (`run.yaml`) to define:
- Execution modes (local/SLURM)
- Python kernel settings
- Template paths
- Script configurations
- Default arguments



Example configuration structure:
```yaml
mode:
  local:
    pykernel: "python3"
    template: "templates/local.sh"
  slurm:
    pykernel: "python3"
    template: "templates/slurm.sh"

scripts:
  my_script:
    path: "path/to/script.py"
    default_args:
      param1: [1.0, 2.0]
      param2: ["value1", "value2"]
```

Default is to create such a `run.yaml` file in the main `submit` directory.

## Usage

Basic usage:
```bash
python submit.py --mode [local|slurm] --script <script_name> [--slurm_args <slurm_args>] [--script_args <script_args>]
```

### Command Line Arguments

Required arguments:
- `--script`: Name of the script configuration from run.yaml
- `--config_file`: Path to YAML config file (default: ./submit/run.yaml)

Optional arguments:
- `--mode`: Execution mode (local or slurm, default: local)

SLURM-specific arguments:
- `--partition`: SLURM partition
- `--nodes`: Number of nodes
- `--cpus-per-task`: CPUs per task
- `--mem-per-cpu`: Memory per CPU (e.g. 4G)
- `--gres`: Generic resources (e.g. gpu:1)
- `--time`: Time limit (e.g. 3-00:00:00)

Additional arguments:
- Any `--key value1 value2 ...` pairs will be passed to the script. If multiple values are provided, the script will be run with all combinations of the script values.

### Examples

Run a local job with default parameters:
```bash
python submit.py --mode local --script my_script
```

Run a SLURM job with custom parameters:
```bash
python submit.py --mode slurm --script my_script --partition gpu --cpus-per-task 4 --mem-per-cpu 4G
```

### Cloud setup

My current workflow is as follows:
1. Start by cloning `submit` in your working repository. 
2. I prefer running jobs on the ML Cloud using a singularity container (cf. https://portal.mlcloud.uni-tuebingen.de/user-guide/tutorials/singularity/). To do so, copy and modify the `examples/Singularity.def` file in your working repository. Then build the singularity container with the following command:
```bash
# Set cache and tmp directories for the Singularity build - (not optimal)
export SINGULARITY_CACHEDIR="/scratch_local/$USER-$SLURM_JOBID"
export SINGULARITY_TMPDIR="/scratch_local/$USER-$SLURM_JOBID"

# Build the singularity container
singularity build --fakeroot --force --bind /mnt:/mnt --nv python.sif Singularity
```
3. Then, copy and modify the `examples/run.yaml` file in the main `submit` directory.
4. From the working repository, run jobs with the following command structure:
```bash
python submit/submit.py --mode [local|slurm] --script <script_name> [--slurm_args <slurm_args>] [--script_args <script_args>]
```

> All examples/* files are excluded when placed in the main `submit` directory to not mess with this repository. 

### Contributing

If you think features are missing or issues occur, please reach out.