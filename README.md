# submit
Lightweight code wrapper for submitting scripts across platforms.
 
## Requirements
- Python 3.6+
- Jinja2

Install dependencies:
```
pip install jinja2
```

## Environment Configuration

Copy the example env file and update paths:

```
cp .env.example .env
```

Edit the `.env` file to set:

```bash
SIMG_PATH=/path/to/your/singularity/image.sif
REPO_PATH=/path/to/your/repo
DATASETS_ROOT_PATH=/path/to/your/datasets
LOG_PATH=/path/to/your/logs
PYTHON_KERNEL=/path/to/your/python3.6
```

## Usage

```
python submit.py [options]
```

For Slurm mode:
```
python submit.py --mode slurm --job_name experiment --python_script run.py --python_arguments "--param=1.0"
```

For local mode:
```
python submit.py --mode local --job_name experiment --python_script run.py --python_arguments "--param=1.0"
```
