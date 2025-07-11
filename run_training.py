import sky
import textwrap
from dotenv import dotenv_values
from sky import ClusterStatus

print("Launching on SkyPilot…")

setup_script = textwrap.dedent(
    """
        echo 'Setting up environment...'
        apt install -y nvtop
        curl -LsSf https://astral.sh/uv/install.sh | sh
        source $HOME/.local/bin/env

        uv sync
    """
)

# Create a SkyPilot Task
task = sky.Task(
    name="lecture-rl-assistant",
    setup=setup_script,
    run="uv run train.py",
    workdir=".",  # Sync the project directory
    envs=dict(dotenv_values()),  # type: ignore
)
task.set_resources(sky.Resources(accelerators="H100-SXM:1"))

# Generate cluster name
cluster_name = "lecture-rl-assistant"
print(f"Launching task on cluster: {cluster_name}")

print("Checking for existing cluster and jobs…")
cluster_status = sky.get(sky.status(cluster_names=[cluster_name]))
if len(cluster_status) > 0 and cluster_status[0]["status"] == ClusterStatus.UP:
    print(f"Cluster {cluster_name} is UP. Canceling any active jobs…")
    sky.stream_and_get(sky.cancel(cluster_name, all=True))

# Launch the task; stream_and_get blocks until the task starts running, but
# running this in its own thread means all models run in parallel.
job_id, _ = sky.stream_and_get(
    sky.launch(
        task,
        cluster_name=cluster_name,
        retry_until_up=True,
        idle_minutes_to_autostop=200,
        down=True,
        fast=True,
    )
)

print(f"Job submitted for {cluster_name} (ID: {job_id}). Streaming logs…")
exit_code = sky.tail_logs(cluster_name=cluster_name, job_id=job_id, follow=True)
print(f"Job {job_id} for {cluster_name} finished with exit code {exit_code}.")