import io
import json
import os
import subprocess
import zipfile

from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = "ZQuestClassic/discord-scripts"
WORKFLOW = "cron.yml"
LOG_DIR = Path("gha-logs")
LOG_RETENTION_DAYS = 90

def main():
    if not LOG_DIR.exists():
        LOG_DIR.mkdir(parents=True)

    now = datetime.now(timezone.utc)
    cutoff_date = now - timedelta(days=LOG_RETENTION_DAYS)
    print(f"Cutoff date for logs: {cutoff_date}")

    print(f"Fetching runs for {WORKFLOW}...")
    # Get all runs for the workflow
    result = subprocess.run(
        [
            "gh", "run", "list",
            "--workflow", WORKFLOW,
            "--repo", REPO,
            "--limit", "5000",
            "--json", "databaseId,createdAt,status,conclusion"
        ],
        capture_output=True,
        text=True,
        check=True
    )

    runs = json.loads(result.stdout)
    print(f"Found {len(runs)} runs.")

    for run in runs:
        run_id = run["databaseId"]
        created_at_str = run["createdAt"]
        # Parse ISO 8601 format: 2026-04-27T12:22:45Z
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))

        if created_at < cutoff_date:
            # Since runs are usually ordered newest first, we could break here, 
            # but we'll just continue to be safe in case of weird ordering.
            continue

        created_at_filename = created_at_str.replace(":", "-")
        log_file = LOG_DIR / f"run-{run_id}-{created_at_filename}.log"

        if log_file.exists() and log_file.stat().st_size > 0:
            # print(f"Skipping run {run_id}, log already exists and is not empty.")
            continue

        print(f"Downloading logs for run {run_id} ({created_at_str})...")
        try:
            # Download the logs zip
            api_result = subprocess.run(
                ["gh", "api", f"repos/{REPO}/actions/runs/{run_id}/logs"],
                capture_output=True,
                check=True
            )
            
            with zipfile.ZipFile(io.BytesIO(api_result.stdout)) as z:
                # Find the log file for the update-top-issues job
                # It usually looks like "1_update-top-issues.txt"
                log_filenames = [f for f in z.namelist() if "update-top-issues" in f and f.endswith(".txt") and "system.txt" not in f]
                
                if not log_filenames:
                    print(f"No update-top-issues log found in zip for run {run_id}.")
                    continue
                
                # Take the first one found
                target_log = log_filenames[0]
                with z.open(target_log) as f:
                    log_file.write_bytes(f.read())
                print(f"Saved log to {log_file}")

        except subprocess.CalledProcessError as e:
            print(f"Failed to download logs for run {run_id}: {e}")
            if e.stderr:
                print(f"Error output: {e.stderr.decode().strip()}")
        except zipfile.BadZipFile:
            print(f"Failed to open zip for run {run_id}: Not a valid zip file (might be still running or logs expired).")

if __name__ == "__main__":
    main()
