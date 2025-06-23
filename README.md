# `submit`

A lightweight job submission tool that supports both local execution and SLURM cluster submissions. It uses Jinja2 templates and YAML configuration to manage job parameters and execution.

## Cloud setup tutorial

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
