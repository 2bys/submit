#!/usr/bin/env python3
"""
Lightweight wrapper for submitting jobs on Slurm cloud.
"""
import os
import sys
import re
import datetime
import argparse
import subprocess
from enum import Enum
from pathlib import Path
from shutil import which
from jinja2 import Environment, FileSystemLoader

def load_env(env_file: Path) -> dict:
    env = {}
    if env_file.exists():
        with env_file.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                key, _, value = line.partition('=')
                env[key.strip()] = value.strip()
    return env

class ExecutionMode(Enum):
    SLURM = "slurm"
    LOCAL = "local"

class LocalJob:
    """Executes jobs locally, capturing output to a log file."""
    def __init__(
        self,
        cmd_str: str,
        job_name: str,
        log_path: Path = Path("logs"),
    ) -> None:
        self._cmd_str = cmd_str
        self._job_name = job_name
        self._log_path = log_path

    def submit(self) -> None:
        self._log_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self._log_path / f"{timestamp}_{self._job_name}.out"
        print(f"Running job '{self._job_name}' locally")
        print(f"Command: {self._cmd_str}")
        print(f"Logging to: {log_file}")
        with log_file.open("w") as f:
            f.write(f"Job Name: {self._job_name}\n")
            f.write(f"Command: {self._cmd_str}\n")
            f.write("-" * 80 + "\n\n")
            process = subprocess.Popen(
                self._cmd_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            while True:
                output = process.stdout.readline()
                if output == b"" and process.poll() is not None:
                    break
                if output:
                    decoded = output.decode("utf-8", errors="replace").rstrip()
                    print(decoded)
                    f.write(decoded + "\n")
                    f.flush()
            return_code = process.poll()
            if return_code != 0:
                print(f"Job failed with return code {return_code}", file=sys.stderr)
                sys.exit(return_code)

def get_venv_cmd_str(args: argparse.Namespace) -> str:
    python_kernel = args.python_kernel
    setup_str = ""
    if isinstance(python_kernel, str) and python_kernel.startswith("singularity"):
        setup_str = (
            "mkdir -p $WORK/tmp\n"
            "export TMPDIR=$WORK/tmp\n"
            "mkdir -p $WORK/cache\n"
            "export CACHEDIR=$WORK/cache\n\n"
        )
    run_str = f"{python_kernel} {args.python_script} {args.python_arguments}"
    return setup_str + run_str

def submit_slurm_job(args: argparse.Namespace) -> None:
    env_vars = load_env(Path(".env"))
    args.simg_path = args.simg_path or Path(env_vars.get("SIMG_PATH", ""))
    args.datasets_root_path = args.datasets_root_path or Path(env_vars.get("DATASETS_ROOT_PATH", ""))
    args.log_path = args.log_path or Path(env_vars.get("LOG_PATH", ""))
    if not args.simg_path:
        print("Singularity image path not specified", file=sys.stderr)
        sys.exit(1)
    if not args.datasets_root_path:
        print("Datasets root path not specified", file=sys.stderr)
        sys.exit(1)
    if not args.log_path:
        print("Log path not specified", file=sys.stderr)
        sys.exit(1)
    if which("sbatch") is None:
        print("sbatch command not found", file=sys.stderr)
        sys.exit(1)
    setup_commands = []
    if args.partition == "2080-galvani":
        dataset = args.dataset
        setup_commands.append("mkdir -p /scratch_local/$SLURM_JOB_USER-$SLURM_JOB_ID/datasets")
        if dataset:
            setup_commands.append(
                f"cp -rf {args.datasets_root_path}/{dataset} "
                f"/scratch_local/$SLURM_JOB_USER-$SLURM_JOB_ID/datasets/{dataset}"
            )
            setup_commands.append("")
            setup_commands.extend([
                "mkdir -p $WORK/tmp",
                "export TMPDIR=$WORK/tmp",
                "mkdir -p $WORK/cache",
                "export CACHEDIR=$WORK/cache",
            ])
            setup_commands.append(f"echo $(ls /scratch_local/$SLURM_JOB_USER-$SLURM_JOB_ID/datasets/{dataset})")
        else:
            print("No dataset specified, skipping dataset copy", file=sys.stderr)
    run_command = (
        f"singularity exec --bind /scratch_local/$SLURM_JOB_USER-$SLURM_JOB_ID:/host "
        f"--bind /mnt:/mnt --nv {args.simg_path} "
        f"bash -c 'python {args.python_script} {args.python_arguments}'"
    )
    template_dir = Path(__file__).parent / "templates"
    env_j2 = Environment(
        loader=FileSystemLoader(str(template_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env_j2.get_template("slurm_job.sh.j2")
    mem_option = f"--mem-per-cpu={args.mem_per_cpu}"
    script_content = template.render(
        job_name=args.job_name,
        partition=args.partition,
        cpus_per_task=args.cpus_per_task,
        mem_option=mem_option,
        gres=args.gres,
        time=args.time,
        log_path=str(args.log_path),
        constraint=args.constraint,
        exclude=args.exclude,
        mail_type=args.mail_type,
        mail_user=args.mail_user,
        setup_commands=setup_commands,
        run_command=run_command,
    )
    script_file = Path(f"{args.job_name}.sh")
    script_file.write_text(script_content)
    script_file.chmod(0o700)
    try:
        subprocess.run(["sbatch", str(script_file)], check=True)
    finally:
        script_file.unlink()

def main() -> None:
    parser = argparse.ArgumentParser(description="Submit jobs to compute instance.")
    parser.add_argument(
        "--mode",
        type=str,
        choices=[m.value for m in ExecutionMode],
        default=ExecutionMode.SLURM.value,
        help="Execution mode (slurm or local)",
    )
    parser.add_argument(
        "--python_kernel",
        type=str,
        default=None,
        help="Path to Python kernel",
    )
    parser.add_argument(
        "--job_name",
        type=str,
        default="test",
        help="Job name",
    )
    parser.add_argument(
        "--simg-path",
        type=lambda p: Path(p),
        default=None,
        help="Path to Singularity image",
    )
    parser.add_argument(
        "--repo-path",
        type=lambda p: Path(p),
        default=None,
        help="Path to repository (unused)",
    )
    parser.add_argument(
        "--datasets-root-path",
        type=lambda p: Path(p),
        default=None,
        help="Root path of datasets",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="diff_kdv_1",
        help="Dataset to copy",
    )
    parser.add_argument(
        "--partition",
        type=str,
        default="2080-galvani",
        choices=["2080-galvani", "a100-galvani"],
        help="Slurm partition",
    )
    parser.add_argument(
        "--cpus-per-task",
        type=int,
        default=12,
        help="Number of CPUs",
    )
    parser.add_argument(
        "--mem-per-cpu",
        type=str,
        default="4G",
        help="Memory per CPU",
    )
    parser.add_argument(
        "--gres",
        type=str,
        default="gpu:1",
        help="GPU resources",
    )
    parser.add_argument(
        "--time",
        type=str,
        default="3-00:00:00",
        help="Maximum runtime D-HH:MM:SS",
    )
    parser.add_argument(
        "--log-path",
        type=lambda p: Path(p),
        default=None,
        help="Directory to store logs",
    )
    parser.add_argument(
        "--constraint",
        type=str,
        default=None,
        help="Node constraint",
    )
    parser.add_argument(
        "--exclude",
        type=str,
        default=None,
        help="Nodes to exclude",
    )
    parser.add_argument(
        "--mail-type",
        type=str,
        default=None,
        help="Email notification event types",
    )
    parser.add_argument(
        "--mail-user",
        type=str,
        default=None,
        help="Email for notifications",
    )
    parser.add_argument(
        "--python_script",
        type=str,
        required=True,
        help="Python script to execute",
    )
    parser.add_argument(
        "--python_arguments",
        type=str,
        default="--wandb",
        help="Arguments for Python script",
    )
    args = parser.parse_args()
    env_vars = load_env(Path(".env"))
    if args.mode == ExecutionMode.LOCAL.value:
        args.python_kernel = args.python_kernel or env_vars.get("PYTHON_KERNEL")
        args.log_path = args.log_path or Path(env_vars.get("LOG_PATH", "logs"))
        cmd_str = get_venv_cmd_str(args)
        job = LocalJob(cmd_str, args.job_name, args.log_path)
        job.submit()
    else:
        submit_slurm_job(args)

if __name__ == "__main__":
    main()
