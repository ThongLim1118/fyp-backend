import subprocess, json, os, shlex
import time

FREQTRADE_IMAGE = os.environ.get("FREQTRADE_IMAGE", "freqtradeorg/freqtrade:stable")
PROJECT_DIR = os.environ.get("PROJECT_DIR", "/app")
UD = os.path.join(PROJECT_DIR, "user_data")


# 可选：宿主机用户/用户组，解决导出文件权限
HOST_UID = os.environ.get("HOST_UID")
HOST_GID = os.environ.get("HOST_GID")

def _docker_base_args(detach: bool = False, name: str | None = None) -> list[str]:
    args = ["docker", "run"]
    if detach:
        args.append("-d")
    args += ["--rm"]
    if name:
        args += ["--name", name]
    # if HOST_UID and HOST_GID:
    #     args += ["-u", f"{HOST_UID}:{HOST_GID}"]
    args += ["-v", f"{PROJECT_DIR}:/freqtrade"]
    return args

def run_detached(args: list[str], name_prefix: str) -> str:
    """
    启动一个后台容器，返回容器ID
    """
    cmd = _docker_base_args(detach=True, name=name_prefix) + [FREQTRADE_IMAGE] + args
    out = subprocess.check_output(cmd).decode().strip()
    return out  # container id

def run_foreground(args: list[str]) -> tuple[int, str, str]:
    cmd = _docker_base_args(detach=False) + [FREQTRADE_IMAGE] + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr

def docker_logs(container_id: str, lines: int = 200) -> str:
    cmd = ["docker", "logs", "--tail", str(lines), container_id]
    return subprocess.check_output(cmd, text=True).strip()

def docker_ps_name(name: str) -> list[str]:
    cmd = ["docker", "ps", "-aqf", f"name={name}"]
    out = subprocess.check_output(cmd, text=True).strip()
    return out.splitlines() if out else []

def docker_rm(container_id: str):
    subprocess.run(["docker", "rm", "-f", container_id], check=False)

def docker_ps_running(ref: str) -> bool:
    # 只查运行中的容器
    out = subprocess.check_output(
        ["docker", "ps", "-qf", f"name={ref}", "-f", "status=running"],
        text=True
    ).strip()
    return bool(out)

def docker_ps_any(ref: str) -> bool:
    # 所有状态（含已退出）
    out = subprocess.check_output(
        ["docker", "ps", "-aqf", f"name={ref}"],
        text=True
    ).strip()
    return bool(out)

def docker_inspect_state(ref: str) -> tuple[str, int] | None:
    """
    返回 (state, exit_code)：
      state 可能为 running/exited/restarting/created/paused/dead
      exit_code 仅在非 running 时有意义
    """
    try:
        fmt = "{{json .State}}"
        out = subprocess.check_output(["docker", "inspect", "-f", fmt, ref], text=True).strip()
        st = json.loads(out)
        return st.get("Status"), int(st.get("ExitCode", 0))
    except subprocess.CalledProcessError:
        return None