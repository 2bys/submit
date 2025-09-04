# `submit`

A lightweight job submission tool that supports both local execution and SLURM cluster submissions. It uses Jinja2 templates and YAML configuration to manage job parameters and execution.

## Quick Setup (Recommended)

For automated setup in your Python repository (on the MLCloud):

1. **Clone submit into your project:**
```bash
git clone <submit-repo-url> submit/
```

2. **Run automated setup:**
Start an interactive session with

```bash
srun --partition=2080-galvani --gres=gpu:1 --pty bash
```

and then run

```bash
python3 -m submit.init
```

Consider the following additional arguments:
- `--non-interactive`: setup in yolo mode.
- `--force`: overwrite existing configuration files.
- `--run-yaml-only`: only rebuild `run.yaml` file.
- `--verbose`: enable verbose logging for debugging script discovery issue 

3. **Build container (if prompted or manually):**
```bash
./build_container.sh  # Run in SLURM interactive session for cloud usage
```

### Expected Folder Structure

**Before setup:**
```
your-project/
├── submit/                 # Cloned submit repository
│   ├── submit.py
│   ├── init.py
│   ├── templates/
│   └── examples/          # Example configuration files
│       ├── run.yaml
│       └── Singularity.def
├── scripts/                # Your Python scripts (optional)
│   ├── train.py
│   └── evaluate.py
├── pyproject.toml         # Or setup.py, requirements.txt
└── src/                   # Your source code
```

**After setup:**
```
your-project/
├── submit/
│   ├── submit.py
│   ├── init.py
│   ├── run.yaml           # Generated configuration
│   ├── templates/
│   └── examples/          # Example files (unchanged)
├── scripts/               # Your scripts (discovered automatically)
├── Singularity.def        # Generated container definition
├── build_container.sh     # Generated build script
├── python.sif            # Built container (after running build script)
├── logs/                  # Generated logs directory
└── pyproject.toml
```

The automated setup will:
- Discover Python scripts in `**/scripts/*.py` directories
- Generate container definition based on your `pyproject.toml`/`setup.py`
- Create run configuration with found scripts
- Optionally build the Singularity container

## Manual Cloud Setup Tutorial

My current workflow is as follows:
1. Start by cloning `submit` in your working repository (e.g. `$WORK/repos/my-repo/submit`) 
2. Next copy `submit/examples/*` to `submit/*`, e.g. via
```bash
cp -rf ./submit/examples/* ./submit/examples/
```
3. I prefer running jobs on the ML Cloud using a singularity container (cf. https://portal.mlcloud.uni-tuebingen.de/user-guide/tutorials/singularity/). To do so, copy and modify the `submit/Singularity.def` file in your working repository. Then, start an interactive session (using e.g. `srun ...`) and build the singularity container with the following command:
```bash
# Set cache and tmp directories for the Singularity build - (not optimal)
export SINGULARITY_CACHEDIR="/scratch_local/$USER-$SLURM_JOBID"
export SINGULARITY_TMPDIR="/scratch_local/$USER-$SLURM_JOBID"

# Build the singularity containers
singularity build --fakeroot --force --bind /mnt:/mnt --nv python.sif submit/Singularity.def
```
4. Next, open and modify the `submit/run.yaml` file in the main `submit` directory. It is important to change the entries below scripts, `regression...` to the scripts you want to run and have in the repo. (Note: `default_args` is optional, so in most cases this section can be removed).
5. From the working repository, run jobs with the following command structure:
```bash
python3 submit/submit.py --mode [local|cloud_local|slurm] --script <script_name> [--slurm_args <slurm_args>] [--script_args <script_args>]
```

You can find some more details below.

Remarks:
- If you want to use jax, keep in mind to install it with cuda dependencies (e.g. `pip install -U "jax[cuda12]"`)
- All examples/* files are excluded when placed in the main `submit` directory to not mess with this repository. 

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

## More details on usage

Basic usage:
```bash
python submit.py --mode [local|cloud_local|slurm] --script <script_name> [--slurm_args <slurm_args>] [--script_args <script_args>]
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

### Contributing

If you think features are missing or issues occur, please reach out.
