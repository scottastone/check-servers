#!.venv/bin/python3
import os
import sys
import glob
import shutil
import stat
import subprocess

def main():
    """
    Finds all 'check-*.py' scripts in the 'src' directory,
    builds them using PyInstaller, and copies them to /usr/local/bin.
    """
    project_root = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(project_root, "src")
    dist_dir = os.path.join(project_root, "dist")
    target_bin_dir = "/usr/local/bin"

    # Ensure we are running with root privileges for the copy step
    if os.geteuid() != 0 and any("check" in arg for arg in sys.argv):
        print(f"Please run this script with sudo to copy files to {target_bin_dir}")
        sys.exit(1)

    # Find all check scripts in the src directory
    scripts_to_build = glob.glob(os.path.join(src_dir, "check-*.py"))

    if not scripts_to_build:
        print(f"No 'check-*.py' scripts found in '{src_dir}'. Exiting.")
        return

    print("Building scripts...")
    for script_path in scripts_to_build:
        print(f"  - Building {script_path}")
        try:
            # Using PyInstaller to build the script
            # --clean: Clean PyInstaller cache and remove temporary files before building.
            subprocess.run(
                [
                    ".venv/bin/pyinstaller",
                    "--onefile",
                    "--clean",
                    script_path,
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=project_root # Run pyinstaller from the project root
            )
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to build {os.path.basename(script_path)}.")
            print(e.stdout)
            print(e.stderr)
            sys.exit(1)

    print("\nSetting permissions and copying files...")
    for script_path in scripts_to_build:
        script_filename = os.path.basename(script_path)
        binary_name = os.path.splitext(script_filename)[0]
        source_binary_path = os.path.join(dist_dir, binary_name)
        target_binary_path = os.path.join(target_bin_dir, binary_name)

        if not os.path.exists(source_binary_path):
            print(f"WARNING: Could not find built binary at {source_binary_path}")
            continue

        # Set execute permissions (+x) for owner, group, and others
        current_permissions = os.stat(source_binary_path).st_mode
        os.chmod(source_binary_path, current_permissions | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # Copy the file to the target directory
        print(f"  - Copying {source_binary_path} to {target_binary_path}")
        shutil.copy(source_binary_path, target_binary_path)

    print("\nBuild and deployment complete!")

if __name__ == "__main__":
    main()