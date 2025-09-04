"""
Initialization module for submit tool setup.

This module automates the setup process for using the submit tool in a Python repository
on cloud environments. It handles:
- Singularity container creation from pyproject.toml/setup.py
- Copying and configuring run.yaml
- Automatic discovery and configuration of Python scripts
- Interactive and non-interactive setup modes

Usage:
    python -m submit.init [options]
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import yaml


class SubmitInitializer:
    """Handles the initialization and setup of the submit tool."""

    def __init__(
        self,
        repo_root: Path,
        interactive: bool = True,
        force: bool = False,
        verbose: bool = False,
    ):
        """Initialize the setup handler.

        Args:
            repo_root: Root directory of the Python repository
            interactive: Whether to prompt for user input
            force: Whether to overwrite existing files
            verbose: Whether to enable verbose logging
        """
        self.repo_root = repo_root
        self.interactive = interactive
        self.force = force
        self.verbose = verbose
        self.submit_dir = repo_root / "submit"

        # Validate that we're in a submit directory
        if not (self.submit_dir / "submit.py").exists():
            # We might be running from the submit directory itself
            if (Path.cwd() / "submit.py").exists():
                self.submit_dir = Path.cwd()
                self.repo_root = Path.cwd().parent
            else:
                msg = (
                    "Cannot find submit.py. Please run from a repository containing a submit/ directory "
                    "or from within the submit directory itself."
                )
                raise FileNotFoundError(msg)

    def _is_relative_to(self, path: Path, parent: Path) -> bool:
        """Python 3.6+ compatible version of Path.is_relative_to()."""
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def log(self, message: str, level: str = "INFO"):
        """Log a message with appropriate formatting."""
        prefix = f"[{level}]" if level != "INFO" else ""
        print(f"{prefix} {message}")

    def verbose_log(self, message: str):
        """Log a verbose message only if verbose mode is enabled."""
        if self.verbose:
            self.log(message, "DEBUG")

    def prompt_yes_no(self, question: str, default: bool = True) -> bool:
        """Prompt user for yes/no input."""
        if not self.interactive:
            return default

        suffix = " [Y/n]" if default else " [y/N]"
        while True:
            response = input(f"{question}{suffix}: ").lower().strip()
            if not response:
                return default
            if response in ["y", "yes"]:
                return True
            elif response in ["n", "no"]:
                return False
            else:
                print("Please enter 'y' or 'n'")

    def prompt_input(self, question: str, default: str = "") -> str:
        """Prompt user for text input."""
        if not self.interactive and default:
            return default

        suffix = f" [{default}]" if default else ""
        response = input(f"{question}{suffix}: ").strip()
        return response if response else default

    def find_python_config(self) -> Optional[Path]:
        """Find Python package configuration file."""
        config_files = ["pyproject.toml", "setup.py", "setup.cfg"]

        for config_file in config_files:
            config_path = self.repo_root / config_file
            if config_path.exists():
                self.log(f"Found Python configuration: {config_path}")
                return config_path

        self.log(
            "No Python configuration file found (pyproject.toml, setup.py, setup.cfg)",
            "WARNING",
        )
        return None

    def create_singularity_def(self) -> Path:
        """Create or update Singularity.def file."""
        singularity_def = self.repo_root / "Singularity.def"

        if singularity_def.exists() and not self.force:
            if not self.prompt_yes_no(
                "Singularity.def already exists. Overwrite?", False
            ):
                self.log("Using existing Singularity.def")
                return singularity_def

        # Determine Python version
        python_version = self.prompt_input("Python version for container", "3.12")

        # Determine installation method
        config_file = self.find_python_config()
        if config_file:
            install_cmd = "python -m pip install --root-user-action=ignore -e ."
        else:
            requirements_file = self.repo_root / "requirements.txt"
            if requirements_file.exists():
                install_cmd = "python -m pip install --root-user-action=ignore -r requirements.txt"
            else:
                install_cmd = "echo 'No package configuration found. Add your install commands here.'"

        singularity_content = f"""Bootstrap: docker
From: python:{python_version}

%post
    cd {self.repo_root.absolute()}
    {install_cmd}
    
    # Install additional dependencies if needed
    # python -m pip install --root-user-action=ignore <additional-packages>

%environment
    export PYTHONPATH="{self.repo_root.absolute()}:$PYTHONPATH"

%runscript
    exec "$@"
"""

        singularity_def.write_text(singularity_content)
        self.log(f"Created {singularity_def}")

        if self.interactive:
            self.log(
                f"Singularity.def configured with repository path: {self.repo_root.absolute()}",
                "INFO",
            )

        return singularity_def

    def discover_python_scripts(self) -> List[Tuple[str, Path]]:
        """Discover Python scripts in scripts/ directories and allow user to add others."""
        discovered_scripts = []

        # Look for all scripts directories anywhere in the repo
        scripts_pattern = "**/scripts/*.py"
        self.verbose_log(f"Searching for scripts with pattern: {scripts_pattern}")
        self.verbose_log(f"Repository root: {self.repo_root}")
        self.verbose_log(f"Submit directory: {self.submit_dir}")

        for script_file in self.repo_root.glob(scripts_pattern):
            self.verbose_log(f"Found potential script: {script_file}")
            self.verbose_log(f"  - Is __init__.py? {script_file.name == '__init__.py'}")
            self.verbose_log(
                f"  - Is in submit dir? {self._is_relative_to(script_file, self.submit_dir)}"
            )
            if script_file.name != "__init__.py" and not self._is_relative_to(
                script_file, self.submit_dir
            ):
                script_name = script_file.stem
                relative_path = script_file.relative_to(self.repo_root)
                self.verbose_log(f"  - Added script: {script_name} -> {relative_path}")
                discovered_scripts.append((script_name, relative_path))
            else:
                self.verbose_log(f"  - Skipped: {script_file.name}")

        # In interactive mode, ask user to add additional scripts
        if self.interactive:
            self.log(
                "\nWould you like to add additional scripts not in scripts/ directories?"
            )
            while self.prompt_yes_no("Add another script?", False):
                script_path_str = self.prompt_input(
                    "Enter script path relative to repository root (e.g., src/train.py)"
                )

                if not script_path_str:
                    continue

                script_path = Path(script_path_str)
                full_script_path = self.repo_root / script_path

                # Validate the script exists and is a Python file
                if not full_script_path.exists():
                    self.log(f"File not found: {full_script_path}", "WARNING")
                    continue

                if not script_path.suffix == ".py":
                    self.log(f"Not a Python file: {script_path}", "WARNING")
                    continue

                if self._is_relative_to(full_script_path, self.submit_dir):
                    self.log(
                        f"Skipping file in submit directory: {script_path}", "WARNING"
                    )
                    continue

                # Check for duplicate names
                script_name = script_path.stem
                existing_names = {name for name, _ in discovered_scripts}
                if script_name in existing_names:
                    if not self.prompt_yes_no(
                        f"Script name '{script_name}' already exists. Add anyway?",
                        False,
                    ):
                        continue

                # Allow user to customize the script name
                custom_name = self.prompt_input(
                    f"Script name for {script_path}", script_name
                )
                if not custom_name:
                    custom_name = script_name

                discovered_scripts.append((custom_name, script_path))
                self.log(f"Added script: {custom_name} -> {script_path}")

        self.verbose_log(f"Total discovered scripts: {len(discovered_scripts)}")
        return discovered_scripts

    def create_run_yaml(self) -> Path:
        """Create run.yaml configuration file in submit directory."""
        run_yaml_path = self.submit_dir / "run.yaml"

        if run_yaml_path.exists() and not self.force:
            if not self.prompt_yes_no("run.yaml already exists. Overwrite?", False):
                self.log("Using existing run.yaml")
                return run_yaml_path

        # Discover scripts
        discovered_scripts = self.discover_python_scripts()

        self.log(f"Discovered {len(discovered_scripts)} Python scripts")
        for name, path in discovered_scripts:
            self.log(f"  - {name}: {path}")

        # Build configuration
        config = {
            "mode": {
                "slurm": {
                    "pykernel": "singularity exec --bind /mnt:/mnt --nv python.sif bash -c",
                    "template": "./submit/templates/slurm_job.sh.j2",
                },
                "cloud_local": {
                    "pykernel": "singularity exec --bind /mnt:/mnt --nv python.sif bash -c",
                    "template": "./submit/templates/cloud_local_job_cmd.j2",
                },
                "local": {
                    "pykernel": "python",
                    "template": "./submit/templates/local_job_cmd.j2",
                },
            },
            "scripts": {},
        }

        # Add discovered scripts
        for script_name, script_path in discovered_scripts:
            if self.interactive:
                include = self.prompt_yes_no(f"Include script '{script_name}'?", True)
                if not include:
                    continue

            # Add script with empty default_args placeholder
            config["scripts"][script_name] = {
                "path": f"./{script_path}",
                "default_args": {},
            }

        # Handle empty scripts case
        if not config["scripts"]:
            self.log("No scripts were configured. Created empty template.", "INFO")
        else:
            self.log(
                "Empty default_args placeholders added for all scripts. You can customize these later in run.yaml.",
                "INFO",
            )

        # Write configuration
        with run_yaml_path.open("w") as f:
            yaml.dump(config, f, default_flow_style=False)

        self.log(f"Created {run_yaml_path}")
        return run_yaml_path

    def setup_logging_directory(self) -> Path:
        """Create logs directory."""
        logs_dir = self.repo_root / "logs"
        logs_dir.mkdir(exist_ok=True)
        self.log(f"Created logs directory: {logs_dir}")
        return logs_dir

    def create_build_script(self) -> Path:
        """Create a script to build the Singularity container."""
        build_script = self.repo_root / "build_container.sh"

        build_content = """#!/bin/bash
# Script to build Singularity container for submit tool

# Set cache and tmp directories for Singularity build
export SINGULARITY_CACHEDIR="/scratch_local/$USER-$SLURM_JOBID"
export SINGULARITY_TMPDIR="/scratch_local/$USER-$SLURM_JOBID"

# Create directories if they don't exist
mkdir -p "$SINGULARITY_CACHEDIR"
mkdir -p "$SINGULARITY_TMPDIR"

echo "Building Singularity container..."
echo "Cache dir: $SINGULARITY_CACHEDIR"
echo "Temp dir: $SINGULARITY_TMPDIR"

# Build the container
singularity build --fakeroot --force --bind /mnt:/mnt --nv python.sif Singularity.def

echo "Container build complete!"
echo "You can now run jobs with: python submit/submit.py --mode cloud_local --script <script_name>"
"""

        build_script.write_text(build_content)
        build_script.chmod(0o755)
        self.log(f"Created build script: {build_script}")
        return build_script

    def build_container_with_script(self) -> bool:
        """Build the Singularity container using the build script."""
        build_script = self.repo_root / "build_container.sh"

        if not build_script.exists():
            self.log("Build script not found. Cannot build container.", "WARNING")
            return False

        try:
            self.log("Building Singularity container using build script...")
            self.log("This may take several minutes...")

            # Run the build script
            result = subprocess.run(
                ["bash", str(build_script)],
                cwd=self.repo_root,
            )

            if result.returncode == 0:
                self.log("Container build completed successfully!", "INFO")
                return True
            else:
                self.log(
                    f"Container build failed with return code {result.returncode}",
                    "WARNING",
                )
                return False

        except FileNotFoundError:
            self.log("Bash shell not found. Cannot run build script.", "WARNING")
            return False
        except Exception as e:
            self.log(f"Error running build script: {e}", "WARNING")
            return False

    def run_setup(self):
        """Run the complete setup process."""
        self.log(
            "⚠️  WARNING: This initialization feature is experimental and "
            "may change in future versions. Please report any bug."
        )
        self.log("Starting submit tool initialization...")
        self.log(f"Repository root: {self.repo_root}")
        self.log(f"Submit directory: {self.submit_dir}")

        # Create Singularity definition
        self.log("\n1. Setting up Singularity container configuration...")
        singularity_def = self.create_singularity_def()

        # Create run.yaml
        self.log("\n2. Creating run.yaml configuration...")
        run_yaml = self.create_run_yaml()

        # Setup logging
        self.log("\n3. Setting up logging directory...")
        logs_dir = self.setup_logging_directory()

        # Create build script
        self.log("\n4. Creating container build script...")
        build_script = self.create_build_script()

        # Summary
        self.log("\n" + "=" * 60)
        self.log("Setup complete! Summary of created files:")
        self.log(f"  - {singularity_def}")
        self.log(f"  - {run_yaml}")
        self.log(f"  - {logs_dir}/")
        self.log(f"  - {build_script}")

        # Container building
        self.log("\n5. Building Singularity container...")
        build_container = False

        if self.interactive:
            build_container = self.prompt_yes_no(
                "Would you like to build the Singularity container now? (Requires Singularity and may take time)",
                False,
            )
        else:
            # In non-interactive mode, try to build if Singularity is available
            try:
                subprocess.run(
                    ["singularity", "--version"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                self.log("Singularity detected. Building container automatically...")
                build_container = True
            except (FileNotFoundError, subprocess.CalledProcessError):
                self.log(
                    "Singularity not available. Skipping container build.", "WARNING"
                )
                build_container = False

        if build_container:
            success = self.build_container_with_script()
            if success:
                self.log("\n" + "=" * 60)
                self.log("Full setup complete! Container is ready to use.")
                self.log("\nYou can now run jobs with:")
                self.log(
                    "  - Local: python submit/submit.py --mode local --script <script_name>"
                )
                self.log(
                    "  - Cloud: python submit/submit.py --mode cloud_local --script <script_name>"
                )
                self.log(
                    "  - SLURM: python submit/submit.py --mode slurm --script <script_name>"
                )
            else:
                self.log("\nContainer build failed. You can build it later with:")
                self.log("  ./build_container.sh")
        else:
            self.log("\nNext steps:")
            self.log("1. Review and edit Singularity.def if needed")
            self.log("2. Run ./build_container.sh to build the container")
            self.log(
                "3. Test with: python submit/submit.py --mode local --script <script_name>"
            )
            self.log(
                "4. Use SLURM: python submit/submit.py --mode slurm --script <script_name>"
            )

    def rebuild_yaml_only(self):
        """Rebuild only the run.yaml file by rediscovering scripts."""
        self.log(
            "⚠️  WARNING: This initialization feature is experimental and may change in future versions."
        )
        self.log("Rebuilding run.yaml configuration...")
        self.log(f"Repository root: {self.repo_root}")
        self.log(f"Submit directory: {self.submit_dir}")

        # Create run.yaml
        run_yaml = self.create_run_yaml()

        # Summary
        self.log("=" * 60)
        self.log("run.yaml rebuild complete!")
        self.log(f"Updated: {run_yaml}")
        self.log("You can now run jobs with your rediscovered scripts.")

    def rebuild_singularity_only(self):
        """Rebuild only the Singularity.def file and build script."""
        self.log(
            "⚠️  WARNING: This initialization feature is experimental and may change in future versions."
        )
        self.log("Rebuilding Singularity container configuration...")
        self.log(f"Repository root: {self.repo_root}")
        self.log(f"Submit directory: {self.submit_dir}")

        # Create Singularity definition
        singularity_def = self.create_singularity_def()

        # Create build script
        build_script = self.create_build_script()

        # Summary
        self.log("=" * 60)
        self.log("Singularity configuration rebuild complete!")
        self.log(f"Updated: {singularity_def}")
        self.log(f"Updated: {build_script}")
        self.log("You can now build the container with: ./build_container.sh")


def main():
    """Main entry point for submit initialization."""
    parser = argparse.ArgumentParser(
        description="Initialize submit tool setup in a Python repository"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Root directory of the Python repository (default: current directory)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run setup without prompting for input (uses defaults)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configuration files",
    )
    parser.add_argument(
        "--run-yaml-only",
        action="store_true",
        help="Only rebuild run.yaml file by rediscovering scripts",
    )
    parser.add_argument(
        "--singularity-only",
        action="store_true",
        help="Only rebuild Singularity.def container definition and build script",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging for debugging",
    )

    args = parser.parse_args()

    try:
        initializer = SubmitInitializer(
            repo_root=args.repo_root,
            interactive=not args.non_interactive,
            force=args.force,
            verbose=args.verbose,
        )

        if args.run_yaml_only:
            initializer.rebuild_yaml_only()
        elif args.singularity_only:
            initializer.rebuild_singularity_only()
        else:
            initializer.run_setup()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nSetup cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"Error during setup: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
