"""The fixed, secret-free on-disk configuration schema."""

import json
import math
import tomllib
from dataclasses import asdict, dataclass, field


@dataclass
class SourceCfg:
    type: str = "opcua"
    endpoint: str = "opc.tcp://192.168.0.10:4840"
    security_policy: str = "None"
    security_mode: str = "SignAndEncrypt"
    cert_dir: str = "pki"
    server_cert: str = ""
    username: str = ""
    sampling_ms: int = 1000
    host: str = "localhost"
    port: int = 1883
    tls_ca: str = ""
    tls_cert: str = ""
    tls_key: str = ""
    client_id: str = ""
    seed: int = 7
    fault_start: int = 40


@dataclass
class TagCfg:
    name: str
    asset: str = "P101"
    node: str = ""
    topic: str = ""
    json_key: str = "value"
    unit: str = ""
    warn: float | None = None
    alarm: float | None = None
    low_warn: float | None = None
    low_alarm: float | None = None

    def limits(self) -> dict:
        return {key: getattr(self, key) for key in ("warn", "alarm", "low_warn", "low_alarm")
                if getattr(self, key) is not None}


@dataclass
class GithubCfg:
    enabled: bool = False
    repo: str = "owner/name"
    branch: str = "gh-pages"
    every_minutes: float = 15
    history_days: int = 7
    token_env: str = "IIOT_AGENT_GITHUB_TOKEN"
    api_url: str = "https://api.github.com"
    label: str = "My machine"


@dataclass
class StoreCfg:
    path: str = "iiot-agent.db"
    keep_days: int = 30


@dataclass
class ManualCfg:
    path: str = ""


@dataclass
class WebCfg:
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass
class ErpCfg:
    url: str = ""


@dataclass
class Config:
    source: SourceCfg = field(default_factory=SourceCfg)
    tags: list[TagCfg] = field(default_factory=list)
    store: StoreCfg = field(default_factory=StoreCfg)
    manual: ManualCfg = field(default_factory=ManualCfg)
    web: WebCfg = field(default_factory=WebCfg)
    github: GithubCfg = field(default_factory=GithubCfg)
    erp: ErpCfg = field(default_factory=ErpCfg)


def sim_tags() -> list[TagCfg]:
    return [TagCfg("vibration", unit="mm/s", warn=4.5, alarm=7.1),
            TagCfg("temperature", unit="°C", warn=70.0, alarm=85.0),
            TagCfg("pressure", unit="bar", low_alarm=4.0)]


def validate(cfg: Config) -> Config:
    if cfg.source.type not in ("opcua", "mqtt", "sim"):
        raise ValueError("Unknown source type: use opcua, mqtt or sim")
    if cfg.source.security_policy not in ("None", "Basic256Sha256", "Aes128_Sha256_RsaOaep",
                                           "Aes256_Sha256_RsaPss"):
        raise ValueError("Unknown security_policy")
    if cfg.source.security_mode not in ("Sign", "SignAndEncrypt"):
        raise ValueError("Unknown security_mode")
    if cfg.source.type == "sim" and not cfg.tags:
        cfg.tags = sim_tags()
    names = set()
    for tag in cfg.tags:
        if not tag.name or not tag.asset or tag.name in names:
            raise ValueError("Tags need an asset and unique, non-empty names")
        names.add(tag.name)
        if cfg.source.type == "opcua" and not tag.node:
            raise ValueError(f"Tag {tag.name}: missing node")
        if cfg.source.type == "mqtt" and not tag.topic:
            raise ValueError(f"Tag {tag.name}: missing topic")
        if cfg.source.type == "sim" and tag.name not in {t.name for t in sim_tags()}:
            raise ValueError("Sim supports vibration, temperature and pressure only")
        for value in tag.limits().values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Tag {tag.name}: limits must be finite numbers")
        if tag.warn is not None and tag.alarm is not None and tag.warn >= tag.alarm:
            raise ValueError(f"Tag {tag.name}: warn must be less than alarm")
        if tag.low_warn is not None and tag.low_alarm is not None and tag.low_alarm >= tag.low_warn:
            raise ValueError(f"Tag {tag.name}: low_alarm must be less than low_warn")
    for name, value in (("sampling_ms", cfg.source.sampling_ms), ("keep_days", cfg.store.keep_days),
                        ("every_minutes", cfg.github.every_minutes), ("history_days", cfg.github.history_days)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive")
    for name, value in (("web.port", cfg.web.port), ("source.port", cfg.source.port)):
        if type(value) is not int or not 0 <= value <= 65535:
            raise ValueError(f"{name} must be a port number")
    if bool(cfg.source.tls_cert) != bool(cfg.source.tls_key):
        raise ValueError("Supply both TLS certificate and private key")
    if not cfg.source.endpoint or not cfg.source.host:
        raise ValueError("Source endpoint and host must not be empty")
    for name, value in (("seed", cfg.source.seed), ("fault_start", cfg.source.fault_start)):
        if type(value) is not int:
            raise ValueError(f"{name} must be an integer")
    return cfg


def from_dict(data: dict) -> Config:
    if not isinstance(data, dict):
        raise ValueError("Configuration must be an object")
    classes = {"source": SourceCfg, "store": StoreCfg, "manual": ManualCfg,
               "web": WebCfg, "github": GithubCfg, "erp": ErpCfg}
    try:
        unknown = set(data) - set(classes) - {"tags"}
        if unknown:
            raise ValueError("Unknown configuration section")
        cfg = Config(**{name: cls(**data.get(name, {})) for name, cls in classes.items()},
                     tags=[TagCfg(**tag) for tag in data.get("tags", [])])
        # Reject mismatched JSON/TOML types before values reach network/file APIs.
        for name in classes:
            obj, defaults = getattr(cfg, name), classes[name]()
            for key, value in asdict(obj).items():
                default = getattr(defaults, key)
                if isinstance(default, str) and not isinstance(value, str):
                    raise ValueError(f"{name}.{key} must be text")
                if isinstance(default, bool) and type(value) is not bool:
                    raise ValueError(f"{name}.{key} must be a boolean")
        for tag in cfg.tags:
            for key in ("name", "asset", "node", "topic", "json_key", "unit"):
                if not isinstance(getattr(tag, key), str):
                    raise ValueError(f"Tag {key} must be text")
        return validate(cfg)
    except (TypeError, AttributeError) as error:
        raise ValueError("Invalid configuration fields or types") from error


def load(path) -> Config:
    with open(path, "rb") as stream:
        return from_dict(tomllib.load(stream))


def dump(config: Config) -> str:
    validate(config)
    lines = ["# Password: environment variable OPCUA_PASSWORD only.",
             "# GitHub token: environment variable named by github.token_env."]
    for section, values in asdict(config).items():
        entries = values if section == "tags" else [values]
        for entry in entries:
            lines.extend(["", "[[tags]]" if section == "tags" else f"[{section}]"])
            for key, value in entry.items():
                if value is not None:
                    lines.append(f"{key} = {json.dumps(value, ensure_ascii=False, allow_nan=False)}")
    return "\n".join(lines) + "\n"


def example() -> str:
    return ("# Edit the endpoint and NodeIds, or choose tags in http://127.0.0.1:8080/setup.\n"
            "# source.type: opcua | mqtt | sim; MQTT uses host/port and tag topic/json_key.\n"
            "# Limits warn/alarm/low_warn/low_alarm are optional and machine-specific.\n"
            + dump(Config(tags=[TagCfg("vibration", node="ns=2;s=Pump/Vibration",
                                       unit="mm/s", warn=4.5, alarm=7.1)])))
