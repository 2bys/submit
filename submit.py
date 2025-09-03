"""Submit jobs with various arguments to SLURM or to run locally."""

import argparse
import datetime
import subprocess
import sys
from enum import Enum
from itertools import product
from pathlib import Path
from typing import Union

import yaml
from jinja2 import Template


class ExecutionMode(Enum):
    """Enumeration of supported job execution modes."""

    SLURM = "slurm"
    LOCAL = "local"
    CLOUD_LOCAL = "cloud_local"

    @classmethod
    def from_str(cls, value: str) -> "ExecutionMode":
        """Convert a string to an ExecutionMode enum value.

        Args:
            value: String representation of the execution mode

        Returns:
            Corresponding ExecutionMode enum value

        Raises:
            ValueError: If the string doesn't match any enum value
        """
        try:
            return cls(value)
        except ValueError as err:
            msg = (
                f"Invalid execution mode: {value}. "
                f"Must be one of {[m.value for m in cls]}"
            )
            raise ValueError(msg) from err


class LocalJob:
    """Class for managing and executing jobs locally."""

    def __init__(
        self,
        cmd_template: Union[str, Path],
        job_name: str,
        template_vars: Union[dict, None] = None,
        log_path: Path = Path("logs"),
    ) -> None:
        """Initialize a local job.

        Args:
            cmd_template: Command template string or path to template file
            job_name: Name of the job
            template_vars: Variables to substitute in the template
            log_path: Directory to store log files
        """
        self._cmd_template = cmd_template
        self._template_vars = template_vars or {}
        self._job_name = job_name
        self._log_path = log_path

    def _render_cmd(self):
        """Render the command template with the provided variables."""
        if isinstance(self._cmd_template, Path):
            template_str = self._cmd_template.read_text()
        else:
            template_str = self._cmd_template

        template = Template(template_str)
        return template.render(**self._template_vars)

    def submit(self) -> None:
        """Execute the job locally and log its output."""
        # Render the final command
        cmd_str = self._render_cmd()

        # Setup log file
        self._log_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self._log_path / f"{timestamp}_{self._job_name}.out"

        print(f"Running job '{self._job_name}' locally")
        print(f"Command: {cmd_str}")
        print(f"Logging to: {log_file}")

        with log_file.open("w") as f:
            f.write(f"Job Name: {self._job_name}\n")
            f.write(f"Command: {cmd_str}\n")
            f.write("-" * 80 + "\n\n")
            process = subprocess.Popen(
                cmd_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )
            while True:
                line = process.stdout.readline()
                # in text mode, readline() returns "" on EOF
                if line == "" and process.poll() is not None:
                    break
                if line:
                    line = line.rstrip()
                    print(line)
                    f.write(line + "\n")
                    f.flush()
            return_code = process.poll()
            if return_code != 0:
                print(f"Job failed with return code {return_code}", file=sys.stderr)
                sys.exit(return_code)


class SlurmJob:
    """Class for managing and submitting jobs to SLURM scheduler."""

    def __init__(
        self,
        cmd_template: Union[str, Path],
        job_name: str,
        template_vars: dict,
        log_path: Path = Path("logs"),
    ) -> None:
        """Initialize a SLURM job.

        Args:
            cmd_template: Command template string or path to template file
            job_name: Name of the job
            template_vars: Variables to substitute in the template
            log_path: Directory to store log files
        """
        self._template = cmd_template
        self._vars = template_vars
        self._job_name = job_name
        self._log_path = log_path

    def _render(self) -> str:
        """Render the SLURM script template with the provided variables."""
        tpl = (
            Path(self._template).read_text()
            if isinstance(self._template, Path)
            else self._template
        )
        return Template(tpl).render(job_name=self._job_name, **self._vars)

    def submit(self) -> None:
        """Submit the job to the SLURM scheduler."""
        # ensure log dir exists (for SBATCH --output=...)
        self._log_path.mkdir(parents=True, exist_ok=True)

        script_fp = Path(f"{self._job_name}.slurm.sh")
        script_fp.write_text(self._render())
        script_fp.chmod(0o700)

        # submit and clean up
        subprocess.run(["sbatch", str(script_fp)], check=True)
        script_fp.unlink()


JOB_OPTIONS = {
    ExecutionMode.LOCAL: LocalJob,
    ExecutionMode.SLURM: SlurmJob,
    ExecutionMode.CLOUD_LOCAL: LocalJob,
}


def arg_to_string(val):
    """Turn argument to string without backslash"""
    return str(val).replace("/", "-")


def main() -> None:
    """Main entry point for job submission.

    Parses command line arguments and submits jobs according to the specified mode
    (local or SLURM) and configuration.
    """
    parser = argparse.ArgumentParser(description="Submit jobs.")
    parser.add_argument(
        "--mode",
        type=str,
        choices=[m.value for m in ExecutionMode],
        default=ExecutionMode.LOCAL.value,
        help="Execution mode (e.g. slurm or local)",
    )

    parser.add_argument(
        "--script",
        type=str,
        required=True,
        help="Which entry under `scripts:` in the YAML to run.",
    )

    parser.add_argument(
        "--config_file",
        type=Path,
        default=Path("./submit/run.yaml"),
        help="YAML config file, containing all run variables.",
    )

    # Special slurm arguments
    parser.add_argument("--partition", type=str, help="SLURM partition")
    parser.add_argument("--nodes", type=int, help="Number of nodes")
    parser.add_argument("--cpus-per-task", type=int, help="CPUs per task")
    parser.add_argument("--mem-per-cpu", type=str, help="Memory per CPU (e.g. 4G)")
    parser.add_argument("--gres", type=str, help="Generic resources (e.g. gpu:1)")
    parser.add_argument("--time", type=str, help="Time limit (e.g. 3-00:00:00)")
    parser.add_argument(
        "--slurm_log_dir",
        type=str,
        default="./logs",
        help="Log directory for slurm job.",
    )

    # Split off any --key value1 value2 ... into `unknown`
    args, unknown = parser.parse_known_args()

    # Convert mode string to enum
    args.mode = ExecutionMode.from_str(args.mode)

    # If SlurmJob then get slurm args
    if args.mode == ExecutionMode.SLURM:
        mode_specific_overrides = {
            "partition": args.partition,
            "nodes": args.nodes,
            "cpus_per_task": args.cpus_per_task,
            "mem_per_cpu": args.mem_per_cpu,
            "gres": args.gres,
            "time_limit": args.time,
            "slurm_log_dir": args.slurm_log_dir,
        }
    else:
        mode_specific_overrides = {}

    # Load YAML config
    with args.config_file.open("r") as f:
        config = yaml.safe_load(f)

    # Grab the right mode-block
    mode_cfg = config["mode"][args.mode.value]
    pykernel = mode_cfg["pykernel"]
    template_fp = Path(mode_cfg["template"])

    # Grab the selected script-block
    script_cfg = config["scripts"][args.script]
    script_path = script_cfg["path"]
    default_args = script_cfg.get("default_args", {})

    # Combine variables to create job arrays
    extra_args = {k: v if isinstance(v, list) else [v] for k, v in default_args.items()}
    i = 0
    while i < len(unknown):
        tok = unknown[i]
        if not tok.startswith("--"):
            parser.error(f"Unexpected token {tok!r}")
        key = tok.lstrip("--")
        i += 1
        vals = []
        # consume until next --foo or end
        while i < len(unknown) and not unknown[i].startswith("--"):
            vals.append(unknown[i])
            i += 1
        if not vals:
            parser.error(f"No values provided for argument --{key}")
        extra_args[key] = vals

    # Build cartesian product of all key-values
    keys = list(extra_args.keys())
    all_values = [extra_args[k] for k in keys]

    # Show job creation details
    total_jobs = len(list(product(*all_values)))
    print(f"Creating {total_jobs} job(s) with the following parameters:")
    if keys:
        for key, values in extra_args.items():
            values_str = ", ".join(str(v) for v in values)
            print(f"  {key}: [{values_str}]")
        print()
    else:
        print("  (no parameters specified)")
        print()

    for combo in product(*all_values):
        # combo is a tuple like ("value1_for_key1", "value_for_key2", ...)
        combo_dict = dict(zip(keys, combo))

        # Prepare the vars that go into Jinja
        template_vars = {
            "pykernel": pykernel,
            "script_path": str(script_path),
            "script_args": combo_dict,
        }

        # Add mode specific arguments
        template_vars.update(
            {k: v for k, v in mode_specific_overrides.items() if v is not None}
        )

        # instantiate and submit
        suffix = "_".join(
            f"{arg_to_string(k)}={arg_to_string(v)}" for k, v in combo_dict.items()
        )
        name = args.script if not suffix else f"{args.script}_{suffix}"

        job = JOB_OPTIONS[args.mode](
            cmd_template=template_fp, job_name=name, template_vars=template_vars
        )
        job.submit()

    print(f"Submitted {total_jobs} job(s)")


if __name__ == "__main__":
    main()
