# iiot-maintenance-agent

[![ci](https://github.com/sulemanali5760/iiot-maintenance-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/sulemanali5760/iiot-maintenance-agent/actions/workflows/ci.yml)

Condition monitoring with zero infrastructure: Python on the machine PC, optional GitHub Pages dashboard.

Connect to an OPC UA server or MQTT broker, choose tags in a local web interface, and watch values,
limits, trends and maintenance notifications with cited manual passages. Readings stay in SQLite.
For a machine PC, a workshop or a student lab. It is not a replacement for Grafana or ThingsBoard
where monitoring servers already exist.

## Quick start

Python 3.11 or newer:

```powershell
pip install git+https://github.com/sulemanali5760/iiot-maintenance-agent
iiot-agent browse opc.tcp://HOST:4840
iiot-agent init
# Edit iiot-agent.toml: endpoint, NodeIds and machine-specific limits.
iiot-agent run -c iiot-agent.toml
```

Open http://127.0.0.1:8080 for the dashboard or http://127.0.0.1:8080/setup to browse and select tags.
Save writes the TOML and restarts collection in the process. Changing the web binding requires
restarting the command. Ctrl+C stops collection and the web server. `--no-web` runs collection alone.
`init -o another.toml` writes another example; existing files are never overwritten by `init`.

`browse` prints path, NodeId and datatype. Use `--root NODEID` for a subtree. Secure connections accept
`--security-policy Basic256Sha256`, `--security-mode SignAndEncrypt`, `--cert-dir pki` and `--user USER`.
Set `OPCUA_PASSWORD` in the process environment; passwords never go in TOML. The server must trust the
client certificate. Configure `source.server_cert` to pin the server certificate. Browse passwords
entered in setup are used only for that browse request; collection still reads the environment.

Without hardware, set `[source] type = "sim"` and remove the example `[[tags]]` block to use the three
bundled sensor tags. `iiot-agent sim` separately serves the simulated IO-Link master at
`opc.tcp://127.0.0.1:4841/iolink/` for testing an OPC UA client.

For MQTT, set source type to `mqtt`, `host` and `port`, and give each tag a `topic` instead of a node.
Payloads can be numbers or JSON objects; `json_key = "value"` selects the numeric field. `tls_ca`,
`tls_cert`, `tls_key` and `client_id` are supported. Use port 8883 when the broker requires TLS.
Collection reconnects with exponential backoff from 1 second up to 60 seconds after connection loss.
The old `bridge`, `store` and `watch` commands are replaced by `run`.

## GitHub dashboard

[Live example](https://sulemanali5760.github.io/iiot-maintenance-agent/): a scheduled GitHub Action connects every hour
to the public umati OPC UA server (`opc.tcp://opcua.umati.app:4843`), reads three values of its sample
robot for 60 seconds and pushes the snapshot (`.github/workflows/live.yml`, `examples/public-demo.toml`).
The robot is a sample device whose values the server simulates; the connection and the pipeline are real.

Create a fine-grained GitHub token with **Contents: read and write on one repository**. Set it in
the environment variable `IIOT_AGENT_GITHUB_TOKEN`, then edit:

```toml
[github]
enabled = true
repo = "owner/name"
branch = "gh-pages"
every_minutes = 15
history_days = 7
token_env = "IIOT_AGENT_GITHUB_TOKEN"
label = "My machine"
```

`run` pushes `snapshot.json` and the standalone dashboard as `index.html`. It creates an orphan
branch if needed and preserves merged history for `history_days`, capped at 2000 points per tag.
Enable GitHub Pages in the repository settings: deploy from the `gh-pages` branch, root folder.
Snapshots contain the display label, tag measurements and notifications; connection settings,
usernames and tokens are excluded. Put no connection secrets in labels, tag names or your manual.

For a scheduled collection job:

```powershell
iiot-agent snapshot -c iiot-agent.toml --duration 60 --push
```

This collects for 60 seconds, merges the previous snapshot, pushes once and exits. No received
reading exits with status 1. Without `--push`, it only collects to the configured SQLite store.

## Data privacy

GitHub Pages sites are public. Real plant data belongs in a private repository (Pages on private
repositories needs a paid plan) or local only with `[github] enabled = false`. A public snapshot
includes tag/asset names, measurements, alarms and notification text with manual passages. Review
that content before enabling a push. Credentials belong in environment variables and local key files.

## Detection and notifications

Each tag can set `warn`, `alarm`, `low_warn` and `low_alarm`. Only the latest value determines its
state; omitted limits are disabled. Configure these limits for the actual machine. The last 20
readings give a least-squares linear trend toward the high alarm while rising or low alarm while
falling. A flat trend has no estimate. This is a linear estimate, not a validated lifetime model.

Notifications fire once at WARN and once at ALARM, then re-arm when the value returns to OK.
SQLite stores readings and notifications; `store.keep_days` controls retention. The UI displays
SQL-downsampled history. A BM25 retriever selects passages from your Markdown manual
(`[manual] path = "manual.md"`); an empty path uses the fictional bundled pump example. Notifications
include the measured value, SQL statistics, trend estimate and cited source headings.

The optional LLM extra is unchanged: `pip install "iiot-maintenance-agent[llm] @ git+https://github.com/sulemanali5760/iiot-maintenance-agent"`, set
`ANTHROPIC_API_KEY`, then `iiot-agent demo --llm`. It receives only measurements and retrieved
passages and is instructed to cite headings. Review its output; a prompt restriction cannot
guarantee accuracy. `IIOT_AGENT_MODEL` selects the model. Normal monitoring uses deterministic text.

`[erp] url = "http://127.0.0.1:8000/notifications"` sends notification JSON to an endpoint you provide
via POST. Fields follow an SAP PM-style notification object; no SAP system, authentication mapping
or delivery queue is included. Failed deliveries are logged; notifications remain in SQLite.

## Offline demo

```powershell
iiot-agent demo
```

The deterministic offline demo uses no server, broker, sleep or API key. Its existing output includes:

```text
Alarm: vibration WARN 4.517 mm/s; time to alarm limit: 51.0 s
Alarm: vibration ALARM 7.103 mm/s; time to alarm limit: 0.0 s
Readings stored: 480
```

Use `--db demo.db` to retain demo readings.

## Limits

The local UI is the live view; GitHub updates are minutes apart and Pages refreshes once a minute.
This is a single-machine tool. The UI has no authentication and binds to localhost by default.
There is no hysteresis, signal filtering, calibration or machine-specific validation. MQTT QoS 1
can deliver duplicates. Use actual machine documentation rather than the fictional example manual.

## Checks

```powershell
python -m pip install -r requirements-dev.txt -e .
python -m pytest -v
python -m pip_audit -r requirements-dev.txt
```

Tests use local in-process servers and fake APIs, never public internet. MQTT integration tests skip
without `MQTT_HOST`; set it (and optionally `MQTT_PORT`) to a local broker to run them. CI runs them on
Windows and Linux with Python 3.11 and 3.12, with a Mosquitto broker on Linux. No hardware validation
is claimed.

## Licence

MIT
