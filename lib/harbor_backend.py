"""Pinned Harbor adapter for Compose tasks; Harbor owns trials, grading and teardown.

The original task stays untouched. Compose config is resolved by Harbor against the
original environment directory, then staged with our overlay and per-run networks.
Private DockerEnvironment calls are confined to resolve_compose, tested against the
pinned version. There is no vendored Harbor lifecycle implementation here.
"""
import argparse
import asyncio
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HARBOR_VERSION = "0.23.0"
COMPOSE_NAMES = ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")
PROVIDER_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MSWEA_API_KEY", "LLM_API_KEY")


def check_version():
    try:
        version = importlib.metadata.version("harbor")
    except importlib.metadata.PackageNotFoundError:
        raise RuntimeError("Compose tasks need Harbor. Install requirements-harbor.txt in .venv-harbor, or set HR_HARBOR_PYTHON.") from None
    if version != HARBOR_VERSION:
        raise RuntimeError(f"Harbor {HARBOR_VERSION} is required; found {version}. Use a dedicated .venv-harbor.")


def project_name(value):
    return "hr-hb-" + hashlib.sha256(value.encode()).hexdigest()[:20]


def docker(*args, check=True):
    result = subprocess.run(["docker", *map(str, args)], text=True, capture_output=True, timeout=60)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def provider_env(proxy):
    return {**{key: "proxy" for key in PROVIDER_VARS},
            "OPENAI_BASE_URL": proxy + "/v1", "OPENAI_API_BASE": proxy + "/v1",
            "ANTHROPIC_BASE_URL": proxy, "LLM_BASE_URL": proxy + "/v1"}


def clean_host_env(proxy):
    # Compose interpolation must not inject the worker's real provider/cloud keys.
    for key in list(os.environ):
        if key.startswith("AWS_") or key in {"HR_GIT_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", *PROVIDER_VARS}:
            os.environ.pop(key, None)
    os.environ.update(provider_env(proxy))
    os.environ.setdefault("TEST_DIR", "/tests")


async def resolve_compose(task_dir, work, project, platform):
    from harbor.environments.docker.docker import DockerEnvironment
    from harbor.models.task.task import Task
    from harbor.models.trial.paths import TrialPaths
    from harbor.models.task.config import NetworkPolicy, NetworkMode
    task = Task(task_dir)
    if task.has_steps or task.config.environment.os.value != "linux":
        raise ValueError("This backend currently supports single-step Linux Compose tasks")
    paths = TrialPaths(work / "resolve")
    paths.mkdir()
    mounts = [{"type": "bind", "source": str(work / leaf), "target": f"/logs/{leaf}"}
              for leaf in ("agent", "verifier", "artifacts")]
    for leaf in ("agent", "verifier", "artifacts"):
        (work / leaf).mkdir(parents=True, exist_ok=True)
    aliases = [task.paths.environment_dir / n for n in COMPOSE_NAMES if (task.paths.environment_dir / n).is_file()]
    extra = aliases[:1] if aliases and aliases[0].name != "docker-compose.yaml" else []
    env = DockerEnvironment(environment_dir=task.paths.environment_dir, environment_name=project,
        session_id=project, trial_paths=paths, task_env_config=task.config.environment,
        mounts=mounts, extra_docker_compose=extra,
        network_policy=NetworkPolicy(network_mode=NetworkMode.PUBLIC))
    env._use_prebuilt = bool(task.config.environment.docker_image)
    env._mounts_compose_path = env._write_mounts_compose_file()
    env._resources_compose_path = env._write_resources_compose_file()
    try:
        result = await env._run_docker_compose_command(["config", "--format", "json"], timeout_sec=60)
        config = json.loads(result.stdout[result.stdout.index("{"):])
    finally:
        env._cleanup_mounts_compose_file()
        env._cleanup_resources_compose_file()
    config.pop("name", None)
    for service in config["services"].values():
        service["platform"] = platform
    return task, config


def compose_file(path, config):
    path.write_text(json.dumps(config, indent=2))
    return path


async def compose_command(path, project, *args, timeout=1800):
    proc = await asyncio.create_subprocess_exec("docker", "compose", "-p", project, "-f", str(path), *args,
                                               stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        proc.terminate()
        await proc.wait()
        raise
    if proc.returncode:
        raise RuntimeError(output.decode(errors="replace")[-12000:])
    return output.decode(errors="replace")


async def build_main(args):
    work = args.work.resolve(); work.mkdir(parents=True, exist_ok=True)
    project = project_name(str(work))
    task, config = await resolve_compose(args.task, work, project, args.platform)
    main = config["services"]["main"]
    if main.get("build"):
        main["image"] = args.image
        file = compose_file(work / "build-compose.json", config)
        await compose_command(file, project, "build", "main", timeout=task.config.environment.build_timeout_sec)
    else:
        source = main.get("image")
        if not source:
            raise ValueError("Compose main needs a build definition or image")
        if docker("image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", source, check=False) != args.platform:
            await compose_command(compose_file(work / "build-compose.json", config), project, "pull", "main")
        docker("tag", source, args.image)
    print(args.image)


def runtime_compose(config, *, image, project, evaluation, network, proxy, egress, out):
    config = copy.deepcopy(config)
    services = config["services"]
    aliases = set(services)
    for service in services.values():
        if service.get("container_name"):
            aliases.add(service["container_name"])
        for value in (service.get("networks") or {}).values():
            aliases.update((value or {}).get("aliases") or [])
    no_proxy = ",".join(sorted(aliases | {"localhost", "127.0.0.1", proxy.split("//")[-1].split(":")[0]}))
    labels = {"hr.harbor": project}
    if evaluation:
        labels["hr.evaluation"] = evaluation
    for kind in ("networks", "volumes"):
        for value in config.get(kind, {}).values():
            if value.get("external"):
                raise ValueError(f"External {kind} need an explicit integration; task resources must be isolated per run")
            value.pop("name", None)
            value["labels"] = {**value.get("labels", {}), **labels}
            if kind == "networks" and egress != "open":
                value["internal"] = True
    config.setdefault("networks", {})["hr_gateway"] = {"external": True, "name": network}
    for name, service in services.items():
        if service.get("network_mode"):
            raise ValueError(f"Service {name} uses network_mode; shared/host network namespaces need a separate integration")
        container_alias = service.pop("container_name", None)
        service["labels"] = {**service.get("labels", {}), **labels}
        service.setdefault("networks", {})["hr_gateway"] = {"aliases": [container_alias]} if container_alias else None
        values = service.setdefault("environment", {})
        # A declared key without a base URL otherwise sends a dummy key to the real provider.
        if proxy:
            endpoints = {"OPENAI_API_KEY": ("OPENAI_BASE_URL", "OPENAI_API_BASE"),
                         "ANTHROPIC_API_KEY": ("ANTHROPIC_BASE_URL",), "LLM_API_KEY": ("LLM_BASE_URL",)}
            declared = set(values)
            for key, urls in endpoints.items():
                if key in declared:
                    declared.update(urls)
            for key, value in provider_env(proxy).items():
                if key in declared:
                    values[key] = value
        if egress != "open":
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                values[key] = proxy.replace(":4000", ":3128")
            values.update(NO_PROXY=no_proxy, no_proxy=no_proxy, NODE_USE_ENV_PROXY="1")
            if egress == "inspect":
                for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO"):
                    values[key] = "/hr-ca.pem"
                service.setdefault("volumes", []).append({"type": "bind", "source": str(out / "hr-ca.pem"), "target": "/hr-ca.pem", "read_only": True})
        if name == "main":
            service.pop("build", None)
            service["image"] = image
            service["pull_policy"] = "never"
            # Inject agent-only variables at exec time, so verification does not inherit proxies.
            for key in list(values):
                if key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "NODE_USE_ENV_PROXY"):
                    values.pop(key)
            service.setdefault("volumes", []).append({"type": "bind", "source": str(out), "target": "/out"})
        elif service.get("build"):
            service["image"] = f"hr-sidecar/{project}:{name}"
    return config, no_proxy


def stage_task(task_dir, destination, image, config):
    import toml
    import shutil
    destination.mkdir(parents=True, exist_ok=True)
    for path in task_dir.iterdir():
        if path.name not in ("task.toml", "environment"):
            if path.is_dir(): shutil.copytree(path, destination / path.name)
            else: shutil.copy2(path, destination / path.name)
    raw = toml.load(task_dir / "task.toml")
    raw.setdefault("environment", {})["docker_image"] = image
    (destination / "task.toml").write_text(toml.dumps(raw))
    env_dir = destination / "environment"; env_dir.mkdir()
    # Paths in resolved Compose are absolute; keep remaining assets for task hooks and provenance.
    for path in (task_dir / "environment").iterdir():
        if path.name not in COMPOSE_NAMES:
            (env_dir / path.name).symlink_to(path.resolve(), target_is_directory=path.is_dir())
    compose_file(env_dir / "docker-compose.yaml", config)


def scalar_reward(rewards):
    # Keep every metric in harbor-result.json; never invent an aggregate for multi-metric graders.
    return rewards.get("reward") if rewards else None


async def run_trial(args):
    project = project_name(str(args.out.resolve()))
    gateway = project + "-gateway"
    labels = ["--label", f"hr.harbor={project}"]
    if os.environ.get("HR_LOCAL_EVAL_ID"):
        labels += ["--label", "hr.evaluation=" + os.environ["HR_LOCAL_EVAL_ID"]]
    docker("network", "create", *labels, *(["--internal"] if args.egress != "open" else []), gateway)
    try:
        if args.proxy_container:
            docker("network", "connect", gateway, args.proxy_container)
        return await execute_trial(args, project, gateway)
    finally:
        # A SIGKILL is handled by the worker's label-based reaper. Normal exit/cancel
        # gets Harbor teardown first and this fallback for a partially created trial.
        if args.proxy_container:
            docker("network", "disconnect", gateway, args.proxy_container, check=False)
        for kind in ("container", "network", "volume"):
            ids = docker(kind, "ls", "-q", "--filter", f"label=hr.harbor={project}",
                         *(["-a"] if kind == "container" else []), check=False).split()
            if ids: docker(kind, "rm", *(["-f", "-v"] if kind == "container" else []), *ids)


async def execute_trial(args, project, gateway):
    from harbor.trial.trial import Trial
    from harbor.trial.hooks import TrialEvent
    from harbor.models.trial.config import TrialConfig
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    work = args.work.resolve(); work.mkdir(parents=True, exist_ok=True)
    _, original = await resolve_compose(args.task, work, project, args.platform)
    config, no_proxy = runtime_compose(original, image=args.image, project=project,
        evaluation=os.environ.get("HR_LOCAL_EVAL_ID", ""), network=gateway,
        proxy=args.proxy, egress=args.egress, out=out)
    staged = work / "task"
    stage_task(args.task.resolve(), staged, args.image, config)
    runtime_path = staged / "environment/docker-compose.yaml"
    # Build sidecars before Trial selects its prebuilt main image.
    await compose_command(runtime_path, project, "build")
    recipe = json.loads(args.recipe.read_text()) if args.recipe else None
    bridge_env = {}
    if recipe:
        bridge_env = {v["name"]: v["value"].replace("$PROXY_URL", args.proxy) for v in recipe["env"]}
        bridge_env.update(PROXY_URL=args.proxy, TEST_DIR="/tests", HR_PATH=args.image_path)
        if args.egress != "open":
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                bridge_env[key] = args.proxy.replace(":4000", ":3128")
            bridge_env.update(NO_PROXY=no_proxy, no_proxy=no_proxy, NODE_USE_ENV_PROXY="1")
            if args.egress == "inspect":
                for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO"):
                    bridge_env[key] = "/hr-ca.pem"
    bridge = work / "bridge.json"
    bridge.write_text(json.dumps({"wrapper": str(args.wrapper.resolve()) if args.wrapper else None,
        "out": str(out), "workdir": args.workdir, "env": bridge_env}))
    agent = {"name": "oracle"} if args.oracle else {"import_path": "harbor_agent:RecipeAgent", "kwargs": {"bridge_file": str(bridge)}}
    trial = await Trial.create(TrialConfig.model_validate({"task": {"path": str(staged)},
        "trial_name": project, "trials_dir": str(work / "trials"), "agent": agent,
        "environment": {"type": "docker", "delete": True}}))
    started = time.monotonic()
    async def log(entry):
        name = "stderr.log" if entry.stream == "stderr" else "stdout.log"
        folder = out / "verifier" if entry.phase == "verification" else out
        folder.mkdir(exist_ok=True)
        with (folder / name).open("a") as f:
            f.write(entry.text)
        if entry.phase == "agent":
            print(entry.text, end="", flush=True)
    async def verify(event):
        print("Harbor: verifying task", flush=True)
        if args.proxy_container:
            script = "import os,urllib.request; urllib.request.urlopen(urllib.request.Request('http://localhost:4000/_hr/phase',data=b'{\"phase\":\"verify\"}',headers={'X-HR-Token':os.environ['T']}))"
            docker("exec", "-e", f"T={args.control_token}", args.proxy_container, "python3", "-c", script)
        # Match the existing runner: main verifier has open egress, without the agent's proxy env.
        ids = docker("ps", "-q", "--filter", f"label=hr.harbor={project}", "--filter", "label=com.docker.compose.service=main").split()
        for cid in ids:
            docker("network", "connect", args.verify_network, cid, check=False)
    trial.add_log_callback(log)
    trial.add_hook(TrialEvent.VERIFICATION_START, verify)
    result = None
    try:
        result = await trial.run()
    finally:
        # Trial handles graceful cancellation; this also catches partially-started stacks.
        await compose_command(runtime_path, project + "__env", "down", "--volumes", "--remove-orphans", timeout=60)
    rewards = result.verifier_result.rewards if result.verifier_result else None
    error = result.exception_info.model_dump(mode="json") if result.exception_info else None
    exit_file = out / "agent-exit.json"
    rc = json.loads(exit_file.read_text())["rc"] if exit_file.exists() else (0 if not error else 1)
    if error and error["exception_type"] == "AgentTimeoutError": rc = 124
    record = {"backend": "harbor", "version": HARBOR_VERSION, "rc": rc,
        "seconds": int(time.monotonic() - started), "reward": scalar_reward(rewards), "rewards": rewards,
        "verifier_rc": None, "error": error, "trial": result.model_dump(mode="json")}
    (out / "harbor-result.json").write_text(json.dumps(record, indent=2))
    # Preserve Harbor's complete trial artifacts under the run folder, without duplicating staged task data.
    import shutil
    for name in ("verifier", "agent", "artifacts"):
        source = trial.paths.trial_dir / name
        if source.exists(): shutil.copytree(source, out / name, dirs_exist_ok=True)
    if error:
        print(f"Harbor: {error['exception_type']}: {error['exception_message']}", file=sys.stderr)
    return 0 if not error or error["exception_type"] in ("AgentTimeoutError", "NonZeroAgentExitCodeError") else 1


async def main(args):
    check_version()
    if args.command == "check": return 0
    clean_host_env(getattr(args, "proxy", None) or "http://hr-proxy:4000")
    os.environ["DOCKER_DEFAULT_PLATFORM"] = args.platform
    if args.command == "image":
        await build_main(args); return 0
    current = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT): loop.add_signal_handler(sig, current.cancel)
    return await run_trial(args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "image", "run"))
    for key in ("task", "work", "out", "recipe", "wrapper"):
        parser.add_argument("--" + key, type=Path)
    for key in ("image", "network", "verify-network", "proxy", "proxy-container", "workdir", "image-path"):
        parser.add_argument("--" + key, default="")
    parser.add_argument("--control-token", default=os.environ.get("HR_CONTROL_TOKEN", ""))
    parser.add_argument("--platform", default="linux/amd64")
    parser.add_argument("--egress", default="record")
    parser.add_argument("--oracle", action="store_true")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(main(args)))
    except asyncio.CancelledError:
        sys.exit(143)
    except Exception as error:
        if args.command == "run" and args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            if not (args.out / "harbor-result.json").exists():
                (args.out / "harbor-result.json").write_text(json.dumps({"backend": "harbor", "version": HARBOR_VERSION,
                    "rc": 1, "seconds": 0, "reward": None, "rewards": None, "verifier_rc": None,
                    "error": {"exception_type": type(error).__name__, "exception_message": str(error)}}))
        print(f"Harbor backend: {error}", file=sys.stderr)
        sys.exit(1)
