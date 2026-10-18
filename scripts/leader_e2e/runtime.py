"""Create isolated MySQL and owned child processes; retain data and logs on exit."""
import json
import os
import secrets
import shutil
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

from devtools.environment import SERVICES, service_python


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_http(url: str, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(.5)
    raise RuntimeError(f"Readiness timeout: {url}")


class Runtime:
    def __init__(self, root: Path, directory: Path, nacos: str):
        self.root, self.directory, self.nacos = root, directory, nacos
        self.name = "aihub-pro-leader-qa-" + directory.name.lower()
        self.password, self.jwt = secrets.token_hex(24), secrets.token_hex(32)
        self.processes: list[tuple[str, subprocess.Popen, object]] = []
        self.group = "LEADER_QA_" + secrets.token_hex(6)
        self.ports: dict[str, int] = {}
        self.created = False

    def create_database(self):
        wait_http(f"http://{self.nacos}/nacos/v1/console/health/readiness", 120)
        env = {**os.environ, "MYSQL_ROOT_PASSWORD": self.password}
        result = subprocess.run([
            "docker", "run", "-d", "--name", self.name,
            "--label", "com.aihub.pro.purpose=leader-e2e",
            "--mount", f"type=volume,source={self.name}-data,target=/var/lib/mysql",
            "-p", "127.0.0.1::3306", "-e", "MYSQL_ROOT_PASSWORD", "-e", "TZ=UTC",
            "mysql:8.4", "--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci",
        ], env=env, capture_output=True, text=True)
        if result.returncode: raise RuntimeError("Could not create isolated MySQL: " + result.stderr)
        self.created = True
        self.db_port = int(subprocess.check_output(["docker", "port", self.name, "3306/tcp"], text=True).strip().rsplit(":", 1)[1])
        for attempt in range(90):
            result = self.sql("SELECT 1", check=False)
            if result.returncode == 0: break
            if attempt % 10 == 0: print("Waiting for isolated MySQL", flush=True)
            time.sleep(1)
        else: raise RuntimeError("Isolated MySQL did not become ready")
        offset = datetime.now().astimezone().strftime("%z")
        self.database_timezone = offset[:3] + ":" + offset[3:]
        # DB defaults and application date.today() must use the same date.
        self.sql(f"SET GLOBAL time_zone='{self.database_timezone}'")
        for path in sorted((self.root / "deploy/mysql/init").glob("*.sql")):
            self.sql(path.read_text(encoding="utf-8"))
        self.sql("""USE capability_db;
INSERT INTO t_capability (id,category_id,name,code,service_name,path,param_schema,price_per_call,status,description)
VALUES (4,1,'Unsupported online QA capability','qa-unsupported','ai-chat-service','/untrusted',
JSON_OBJECT('type','object'),8,'online','Test-only unsupported adapter');""")
        print("Created independent QA MySQL", self.name, flush=True)

    def sql(self, statement: str, check: bool = True):
        return subprocess.run([
            "docker", "exec", "-i", "-e", "MYSQL_PWD", self.name,
            "mysql", "--protocol=tcp", "-uroot", "--default-character-set=utf8mb4", "--batch",
        ], input=statement, env={**os.environ, "MYSQL_PWD": self.password},
            text=True, encoding="utf-8", capture_output=True, check=check)

    def start(self, name: str, command: list[str], directory: Path, environment: dict):
        log = (self.directory / f"{name}.log").open("x", encoding="utf-8")
        process = subprocess.Popen(command, cwd=directory, env=environment, stdout=log, stderr=subprocess.STDOUT)
        self.processes.append((name, process, log))
        print("Started", name, "pid", process.pid, flush=True)

    def start_services(self, model_url: str, catalog_mode: str):
        environment = {**os.environ, "NACOS_ADDR": self.nacos, "NACOS_GROUP": self.group,
            "NACOS_NAMESPACE": "public", "JWT_SECRET": self.jwt, "JWT_ISSUER": "ai-capability-hub",
            "USE_MOCK": "false", "MODEL_BASE_URL": model_url, "MODEL_API_KEY": "qa-only-placeholder",
            "MODEL_TIMEOUT": "0.8", "NACOS_MODEL_CONFIG_ENABLED": "false",
            "CAPABILITY_CATALOG_MODE": catalog_mode, "ENABLE_INTERNAL_CHAIN": "true",
            "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "SERVICE_HOST": "127.0.0.1"}
        self.environment = environment
        for name, (database, _) in SERVICES.items():
            port = free_port()
            self.ports[name] = port
            root = self.root / "services" / name
            env = {**environment, "SERVICE_NAME": name, "SERVICE_PORT": str(port),
                   "DB_URL": f"mysql+pymysql://root:{self.password}@127.0.0.1:{self.db_port}/{database}?charset=utf8mb4"}
            executable = service_python(root)
            if not executable.exists(): raise RuntimeError(f"Install dependencies for {name} first")
            self.start(name, [str(executable), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], root, env)
        for port in self.ports.values(): wait_http(f"http://127.0.0.1:{port}/health", 45)
        gateway_port = free_port()
        self.ports["gateway"] = gateway_port
        jar = self.root / "gateway/target/api-gateway-0.1.0-SNAPSHOT.jar"
        if not jar.exists(): raise RuntimeError("Package Gateway with mvn package before E2E")
        self.start("gateway", [shutil.which("java") or "java", "-jar", str(jar)], self.root / "gateway",
                   {**environment, "GATEWAY_PORT": str(gateway_port), "SENTINEL_DASHBOARD": "127.0.0.1:8859"})
        self.gateway = f"http://127.0.0.1:{gateway_port}"
        wait_http(self.gateway + "/api/capability/market", 120)
        # Discovery may become ready after the HTTP server itself.
        for name in SERVICES: wait_http(self.gateway + f"/{name}/health", 45)
        print("Gateway and all four real service routes are ready", flush=True)

    def start_strict_probe(self):
        port = free_port()
        root = self.root / "services/ai-chat-service"
        env = {**self.environment, "CAPABILITY_CATALOG_MODE": "internal",
               "SERVICE_NAME": "ai-chat-strict-probe", "SERVICE_PORT": str(port),
               "DB_URL": f"mysql+pymysql://root:{self.password}@127.0.0.1:{self.db_port}/ai_chat_db?charset=utf8mb4"}
        self.start("strict-probe", [str(service_python(root)), "-m", "uvicorn", "app.main:app",
                                   "--host", "127.0.0.1", "--port", str(port)], root, env)
        wait_http(f"http://127.0.0.1:{port}/health", 30)
        return f"http://127.0.0.1:{port}"

    def check_browser(self, username: str, password: str):
        port = free_port()
        self.ports["web"] = port
        root = self.root / "web"
        env = {**os.environ, "VITE_DEV_GATEWAY_URL": self.gateway, "VITE_USE_MOCK_LOGIN": "false",
               "VITE_API_BASE_URL": "/api", "VITE_PORT": str(port)}
        node = shutil.which("node") or "node"
        self.start("web", [node, str(root / "node_modules/vite/bin/vite.js"), "--strictPort",
                           "--host", "127.0.0.1", "--port", str(port)], root, env)
        base = f"http://127.0.0.1:{port}"
        wait_http(base, 30)
        result = subprocess.run([node, "--experimental-strip-types", "tests/chat-browser.ts"], cwd=root,
            env={**env, "PRO_E2E_WEB_URL": base, "PRO_E2E_USERNAME": username,
                 "PRO_E2E_PASSWORD": password, "PRO_E2E_EVIDENCE": str(self.directory / "browser")},
            capture_output=True, text=True, encoding="utf-8")
        with (self.directory / "browser-driver.log").open("x", encoding="utf-8") as log:
            log.write(result.stdout + result.stderr)
        if result.returncode: raise RuntimeError("Browser verification failed; inspect browser-driver.log")
        print(result.stdout, flush=True)

    def close(self):
        for name, process, log in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log.close()
        if self.created:
            subprocess.run(["docker", "stop", "--time", "10", self.name], capture_output=True)
        with (self.directory / "resources.json").open("x", encoding="utf-8") as out:
            json.dump({"qa_container": self.name, "qa_volume": self.name + "-data",
                       "ports": self.ports, "nacos_group": self.group,
                       "database_timezone": getattr(self, "database_timezone", None),
                       "owned_processes_stopped": True, "qa_data_retained": True}, out, indent=2)
