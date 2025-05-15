import argparse
from enum import Enum
from pathlib import Path
import datetime 
import sys
import subprocess
from typing import Union
from jinja2 import Template 
import yaml
from itertools import product

class ExecutionMode(Enum):
    SLURM = "slurm"
    LOCAL = "local"


class LocalJob:
    def __init__(
        self,
        cmd_template: Union[str, Path],
        job_name: str,
        template_vars: Union[dict, None] = None,
        log_path: Path = Path("logs")
    ) -> None:
        self._cmd_template = cmd_template
        self._template_vars = template_vars or {}
        self._job_name = job_name
        self._log_path = log_path

    def _render_cmd(self):
        if isinstance(self._cmd_template, Path):
            template_str = self._cmd_template.read_text()
        else:
            template_str = self._cmd_template

        template = Template(template_str)
        return template.render(**self._template_vars)

    def submit(self) -> None:
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
                text=True,
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
    def __init__(
        self,
        cmd_template: Union[str, Path],
        job_name: str,
        template_vars: dict,
        log_path: Path = Path("logs"),
    ) -> None:
        self._template = cmd_template
        self._vars = template_vars
        self._job_name = job_name
        self._log_path = log_path

    def _render(self) -> str:
        tpl = Path(self._template).read_text() if isinstance(self._template, Path) else self._tempalte
        return Template(tpl).render(job_name=self._job_name, **self._vars)

    def submit(self) -> None:
        # ensure log dir exists (for SBATCH --output=...)
        self._log_path.mkdir(parents=True, exist_ok=True)

        script_fp = Path(f"{self._job_name}.slurm.sh")
        script_fp.write_text(self._render())
        script_fp.chmod(0o700)

        # submit and clean up
        subprocess.run(["sbatch", str(script_fp)], check=True)
        script_fp.unlink()


JOB_OPTIONS = {
    "local": LocalJob,
    "slurm": SlurmJob,
}

        
def main() -> None:
    parser = argparse.ArgumentParser(description="Submit jobs.")
    parser.add_argument(
        "--mode",
        type=str,
        choices=[m.value for m in ExecutionMode],
        default=ExecutionMode.LOCAL.value,
        help="Execution mode (e.g. slurm or local)"
    )

    parser.add_argument(
        "--script",
        type=str,
        required=True,
        help="Which entry under `scripts:` in the YAML to run."
    )

    parser.add_argument(
        "--config_file",
        type=Path,
        default=Path("./submit/run.yaml"),
        help="YAML config file, containing all run variables."
    )

    # Split off any --key value1 value2 ... into `unknown`
    args, unknown = parser.parse_known_args()

    # Load YAML config
    with args.config_file.open("r") as f:
        config = yaml.safe_load(f)

    # Grab the right mode-block
    mode_cfg = config["mode"][args.mode]
    pykernel = mode_cfg["pykernel"]
    template_fp = Path(mode_cfg["template"])

    # Grab the selected script-block
    script_cfg = config["scripts"][args.script]
    script_path = script_cfg["path"]

    # Combine variables to pass to jinja
    extra_args: dict[str, list[str]] = {}
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
     
    for combo in product(*all_values):
        # combo is a tuple like ("value1_for_key1", "value_for_key2", ...)
        combo_dict = dict(zip(keys, combo))
        
        # Prepare the vars that go into Jinja
        template_vars = {
            "pykernel": pykernel,
            "script_path": str(script_path),
            "script_args": combo_dict,            
        }

        # instantiate and submit
        suffix = "_".join(f"{k}={v}" for k,v in combo_dict.items())
        name = args.script if not suffix else f"{args.script}_{suffix}"
        
        job = JOB_OPTIONS[args.mode](
            cmd_template=template_fp,
            job_name=name,            
            template_vars=template_vars
        )
        job.submit()

if __name__ == "__main__":
    main()
