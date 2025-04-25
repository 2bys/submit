"""
Lightweight wrapper for Slurm job. 
"""
from pathlib import Path
import re
import subprocess
import sys
from enum import Enum
from shutil import which
from jinja2 import Environment, FileSystemLoader
from typing import Union

class SlurmJob:
    """Submits jobs to the Slurm cluster.
    
    The class creates a bash script with the relevant commands, executes it and 
    deletes it afterwards.

    Example:
    ``
    slurm_job = SlurmJob(
        cmd_str="python ./run.py --param=1.0",
        job_name="experiment",
        partition="2080-galvani",
        time="0-00:01:00",
        mem="8G"
    )
    slurm_job.submit()
    ``    
    """

    def __init__(
        self,
        cmd_str: str,
        job_name: Union[str, None],
        partition: str,
        cpus_per_task: int,
        mem_per_cpu: Union[str, None],
        mem: Union[str, None],
        gres: str,
        time: str,
        log_path: Path,
        constraint: Union[str, None],
        exclude: Union[str, None],
        mail_type: Union[str, None],
        mail_user: Union[str, None],
    ) -> None:
        """SlurmJob constructor that stores (and check some of the) parameters.

        Args:
            cmd_str: The command line string for executing the actual program code
                (and potential setup code), e.g., `"python train.py <ARGS>"`.
            job_name: Name of the Slurm job. If None, it becomes the sweep ID.
            partition: This setting specifies the partition. For a complete
                list of available partitions, execute the Slurm command
                `sinfo -s`. Examples:
                cpu-galvani: 30h time limit
                2080-galvani: 3d time limit
                a100-galvani: 3d time limit
            cpus_per_task: The number of CPUs (as only a single task is used).
            mem_per_cpu: Available RAM per each CPU specified in megabytes (suffix `M`)
                or gigabytes (suffix `G`).
            mem: Total available RAM in the same format as mem_per_cpu.
            gres: GPU resources to allocate. Default is `gpu:1` which allocates a single
                GPU whose type depends on the partition.
            time: Maximum runtime specified in the format D-HH:MM:SS,
                e.g., `"0-08:00:00"` for 8 hours. This needs to be compatible
                with `partition`.
            log_path: The output file will be stored in this folder.
                Default is `None`, i.e. the output and
                error file are stored in the working directory.
            constraint: With this parameter, you can target specific nodes that fulfill
                a certain constraint.
            exclude: This parameter allows to exclude certain nodes.
            mail_type: This parameter selects the type of event(s) for which an email
                notification is sent. If set, `mail_user` must also be set.
            mail_user: This parameter sets the email account for email notifications.

        Raises:
            ValueError: Either both mem_per_cpu and mem are specified or neither.
        """
        # Input checks
        self._check_job_name(job_name)

        if mem_per_cpu is not None and mem is not None:
            msg = "Both `mem_per_cpu` and `mem` are specified"
            raise ValueError(msg)

        if mem_per_cpu is None and mem is None:
            msg = "Neither `mem_per_cpu` nor `mem` is specified"
            raise ValueError(msg)

        if mem_per_cpu is not None:
            self._check_memory_format(mem_per_cpu)

        if mem is not None:
            self._check_memory_format(mem)

        if mail_type is not None and mail_user is None:
            msg = "`mail_user` must be specified when `mail_type` is set"
            raise ValueError(msg)

        self._check_time_format(time)

        # Attribute assignments
        self._cmd_str = cmd_str
        self._job_name = job_name
        self._partition = partition
        self._cpus_per_task = cpus_per_task
        self._mem_per_cpu = mem_per_cpu
        self._mem = mem
        self._gres = gres
        self._time = time
        self._log_path = log_path
        self._constraint = constraint
        self._exclude = exclude
        self._mail_type = mail_type
        self._mail_user = mail_user

        self._output_file_path = self._create_file_paths()

    def submit(self) -> None:
        """Submits the job to Slurm.

        Creates a temporary bash script, executes it, and finally deletes it. Note that
        the `sbatch` command returns immediately.

        Raises:
            RuntimeError: If `sbatch` command is not available.
        """
        if not self._sbatch_exists():
            msg = "No 'sbatch' command found on the system"
            raise RuntimeError(msg)

        self._log_path.mkdir(parents=True, exist_ok=True)

        bash_file_path = Path(f"{self._job_name}.sh")
        with bash_file_path.open("w") as f:
            f.write(self._create_bash_str())
        bash_file_path.chmod(0o700)
    
        try:
            subprocess.run(  # noqa: S603
                ["/usr/bin/sbatch", str(bash_file_path)], check=True
            )
        finally:
            bash_file_path.unlink()

    @staticmethod
    def _check_job_name(job_name: str) -> None:
        """Validates the job name.

        The job name must only contain letters, numbers, underscores, and hyphens.
        """
        job_name_format = r"^[a-zA-Z0-9_-]+$"

        if not re.match(job_name_format, job_name):
            msg = f"Job name '{job_name}' has incorrect format"
            raise ValueError(msg)

    @staticmethod
    def _check_memory_format(mem: str) -> None:
        """Validates the format of `mem` or `mem_per_cpu`.

        For example, `"13.4M"` (for 13.4 megabytes) or `"8G"` (for 8 gigabytes) are
        valid values.
        """
        mem_format = r"^(\d+)\.(\d+)[G,M]$|^(\d+)[G,M]$"

        if not re.match(mem_format, mem):
            msg = f"Memory '{mem}' has incorrect format"
            raise ValueError(msg)

    @staticmethod
    def _check_time_format(time: str) -> None:
        """Ensures that `time` has the right format D-HH:MM:SS."""
        time_format = r"^(\d{1})-(\d{2}):(\d{2}):(\d{2})$"

        if not re.match(time_format, time):
            msg = "Time not in format D-HH:MM:SS"
            raise ValueError(msg)

    def _create_file_paths(self) -> Path:
        """Creates absolute output and error file paths based on `self.job_name`.

        Returns:
            The resolved path for the output file.
        """
        # `%j` is a placeholder for the job-id and will be filled in by Slurm
        output_path = self._log_path / f"%j_{self._job_name}.out"

        return output_path.resolve()

    def _create_sbatch_str(self) -> str:
        """Creates the configuration string that contains the `SBATCH` commands.

        Returns:
            A string containing all the SBATCH commands for job configuration.
        """
        mem_option = (
            f"--mem={self._mem}"
            if self._mem is not None
            else f"--mem-per-cpu={self._mem_per_cpu}"
        )

        sbatch_str = (
            f"#SBATCH --job-name={self._job_name}\n"
            f"#SBATCH --partition={self._partition}\n"
            "#SBATCH --nodes=1\n"
            "#SBATCH --ntasks=1\n"
            f"#SBATCH --cpus-per-task={self._cpus_per_task}\n"
            f"#SBATCH {mem_option}\n"
            f"#SBATCH --gres={self._gres}\n"
            f"#SBATCH --time={self._time}\n"
            f"#SBATCH --output={self._output_file_path}"
        )

        if self._constraint is not None:
            sbatch_str += f"\n#SBATCH --constraint={self._constraint}"

        if self._exclude is not None:
            sbatch_str += f"\n#SBATCH --exclude={self._exclude}"

        if self._mail_type is not None:
            sbatch_str += f"\n#SBATCH --mail-type={self._mail_type}"
            sbatch_str += f"\n#SBATCH --mail-user={self._mail_user}"

        return sbatch_str

    def _create_sbatch_file(self):    
        template_dir = Path(__file__).parent / "templates"
        env_j2 = Environment(
            loader=FileSystemLoader(str(template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env_j2.get_template("slurm_job.sh.j2")
        script_content = template.render(
            job_name=self.job_name,
            partition=args.partition,
            cpus_per_task=args.cpus_per_task,
            mem_option=args.mem_option,
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

    @staticmethod
    def _create_scontrol_str() -> str:
        """Creates the `scontrol` string.

        The returned command prints important information to the output file.

        Returns:
            The scontrol command string.
        """
        return "scontrol show job $SLURM_JOB_ID"

    def _create_cmd_str(self) -> str:
        """Create the command line string for executing the actual program.

        Returns:
            The command line string to execute the program.
        """
        return self._cmd_str

    def _create_bash_str(self) -> str:
        """Creates one string that represents the content of the bash file.

        The function joins the components defined in the above methods.

        Returns:
            A string containing the full content of the bash script.
        """
        bash_str = (
            f"#!/bin/bash\n\n{self._create_sbatch_str()}\n\n"
            f"{self._create_scontrol_str()}\n\n{self._create_cmd_str()}"
        )
        return bash_str

    @staticmethod
    def _sbatch_exists() -> bool:
        """Check whether the `sbatch` command is available.

        Returns:
            bool: True if the `sbatch` command is available, False otherwise.
        """
        return which("sbatch") is not None

    


    
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
    script_content = template.render(
        job_name=args.job_name,
        partition=args.partition,
        cpus_per_task=args.cpus_per_task,
        mem_option=args.mem_option,
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
