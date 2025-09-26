import asyncio, csv, json, os
from datetime import datetime, timezone
import websockets
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
import socket
import ipaddress
import contextlib


# ---- Per-file async writers -------------------------------------------------

_writers: dict[str, asyncio.Queue] = {}   # path -> queue
_headers: dict[str, list[str]] = {}       # path -> header (for first-time write)

async def _csv_writer_worker(path: str, header: list[str], q: asyncio.Queue):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    file_exists = os.path.isfile(path)
    with open(path, mode="a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(header)
        while True:
            row = await q.get()
            w.writerow(row)
            f.flush()
            q.task_done()

def _ensure_writer(path: str, header: list[str]) -> asyncio.Queue:
    if path not in _writers:
        q = asyncio.Queue()
        _writers[path] = q
        _headers[path] = header
        asyncio.create_task(_csv_writer_worker(path, header, q))
    return _writers[path]

async def _enqueue_row(path: str, header: list[str], row: list):
    q = _ensure_writer(path, header)
    await q.put(row)

# ---- Connection/session handling --------------------------------------------

CLIENTS = set()
# simple per-connection context
class Ctx:
    def __init__(self):
        self.base_dir = None     # set after session_start

def _safe(s: str) -> str:
    bad = '<>:"/\\|?*'
    s = ''.join('_' if c in bad else c for c in (s or ''))
    return s.strip() or "Unknown"

async def handle(ws):
    CLIENTS.add(ws)
    ctx = Ctx()

    await ws.send(json.dumps({"type": "server_welcome", "message": "Connected."}))
    peer = getattr(ws, "remote_address", ("unknown", 0))
    peer = f"{peer[0]}:{peer[1]}"
    print(f"[CONNECT] {peer} connected")

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send(json.dumps({"type":"error","error":"invalid_json"}))
                continue

            t = msg.get("type")

            if t == "client_hello":
                print(
                    "[HELLO] from {} -> product='{}' unity='{}' platform='{}' url='{}' session='{}'".format(
                        peer, msg.get("product",""), msg.get("unity",""),
                        msg.get("platform",""), msg.get("url",""), msg.get("session","")
                    )
                )
                await ws.send(json.dumps({"type": "hello_ack"}))

            elif t == "session_start":
                # Build and remember the per-session folder
                user = _safe(msg.get("user"))
                scene = _safe(msg.get("scene"))
                mode = _safe(msg.get("mode"))
                started_at = msg.get("started_at") or datetime.now(timezone.utc).isoformat()
                # Prefer the folder Unity already computed, else compute here
                session_dir = msg.get("session_dir") or f"{user}_{scene}_{mode}_{datetime.now():%Y%m%d-%H%M%S}"

                base = os.path.join("logs", session_dir)   # top-level folder on the server
                os.makedirs(base, exist_ok=True)
                ctx.base_dir = base

                print(f"[SESSION] {peer} -> {base}")
                await ws.send(json.dumps({"type":"session_ack","dir":session_dir}))
                # (no writers yet; they are created lazily per file)

            elif t == "ping":
                await ws.send(json.dumps({"type": "pong"}))

            elif t == "echo":
                await ws.send(json.dumps({"type": "echo_response", "payload": msg.get("payload")}))

            elif t == "training_log":
                # default base dir if client forgot to send session_start
                base = ctx.base_dir or os.path.join("logs", "unassigned")
                path = os.path.join(base, "TrainingLog.csv")

                unity_time = float(msg.get("unity_time", 0.0))
                frame = int(msg.get("frame", -1))
                session = str(msg.get("session", ""))
                step = str(msg.get("step", ""))
                action = str(msg.get("action", ""))
                success = msg.get("success", False)
                if isinstance(success, str):
                    success = success.lower() in ("1","true","t","yes","y")
                score = int(msg.get("score", 0))
                ts_iso = datetime.now(timezone.utc).isoformat()

                await _enqueue_row(
                    path,
                    header=["ts_iso","client","unity_time","frame","session","step","action","success","score"],
                    row=[ts_iso, peer, f"{unity_time:.6f}", frame, session, step, action, int(bool(success)), score],
                )
                await ws.send(json.dumps({"type":"training_ack","frame":frame,"step":step}))

            elif t == "gaze_event":
                base = ctx.base_dir or os.path.join("logs", "unassigned")
                path = os.path.join(base, "EyeGazeLog.csv")

                def fnum(v, d=0.0):
                    try: return float(v)
                    except: return float(d)

                ts_iso = datetime.now(timezone.utc).isoformat()
                start = fnum(msg.get("unity_time_start", 0.0))
                end   = fnum(msg.get("unity_time_end", start))
                dur   = fnum(msg.get("duration", max(0.0, end - start)))
                label = str(msg.get("object",""))
                scene = str(msg.get("scene",""))
                step  = str(msg.get("step",""))

                hit = msg.get("hit_pos", {}) or {}
                origin = msg.get("origin", {}) or {}
                d = msg.get("dir", {}) or {}
                head = msg.get("headset", {}) or {}

                await _enqueue_row(
                    path,
                    header=[
                        "StartTime","EndTime","Duration","Object","Scene","Step",
                        "HitPos.x","HitPos.y","HitPos.z",
                        "Origin.x","Origin.y","Origin.z",
                        "Dir.x","Dir.y","Dir.z",
                        "LeftConfidence","RightConfidence","IsTrackingReliable",
                        "Headset.x","Headset.y","Headset.z",
                        "server_ts_iso","client"
                    ],
                    row=[
                        f"{start:.6f}", f"{end:.6f}", f"{dur:.6f}", label, scene, step,
                        fnum(hit.get("x")), fnum(hit.get("y")), fnum(hit.get("z")),
                        fnum(origin.get("x")), fnum(origin.get("y")), fnum(origin.get("z")),
                        fnum(d.get("x")), fnum(d.get("y")), fnum(d.get("z")),
                        fnum(msg.get("left_conf",0.0)), fnum(msg.get("right_conf",0.0)),
                        int(bool(msg.get("is_reliable", True))),
                        fnum(head.get("x")), fnum(head.get("y")), fnum(head.get("z")),
                        ts_iso, peer
                    ],
                )
                await ws.send(json.dumps({"type":"gaze_ack","label":label,"duration":dur}))

            elif t == "broadcast":
                payload = json.dumps({"type":"broadcast_message","from":"server","payload":msg.get("payload")})
                await asyncio.gather(*[c.send(payload) for c in CLIENTS if c.open])

            else:
                await ws.send(json.dumps({"type":"ack","received_type":t,"payload":msg.get("payload")}))
    except (ConnectionClosedOK, ConnectionClosedError):
        pass
    finally:
        CLIENTS.discard(ws)

def get_primary_ipv4() -> str:
    """Best-effort: IPv4 of the default route (no packets sent)."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"

def list_local_ipv4s() -> list[str]:
    """Private/link-local non-loopback IPv4s; primary first."""
    ips = set()
    hostname = socket.gethostname()

    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ips.add(info[4][0])
    except socket.gaierror:
        pass

    primary = get_primary_ipv4()
    ips.add(primary)

    good = []
    for ip in ips:
        try:
            addr = ipaddress.ip_address(ip)
            if addr.is_loopback:
                continue
            if addr.is_private or addr.is_link_local:
                good.append(ip)
        except ValueError:
            pass

    return sorted(set(good), key=lambda x: (x != primary, x))

async def main():
    host, port = "0.0.0.0", 8765

    async with websockets.serve(lambda ws: handle(ws), host=host, port=port):
        print(f"WebSocket server listening on ws://{host}:{port}")

        # Helpful connection hints
        print(f"• Same machine (Unity Editor):   ws://127.0.0.1:{port}  (or ws://localhost:{port})")

        lan_ips = list_local_ipv4s()
        if lan_ips:
            print("• Another device on the same network (e.g., headset):")
            for ip in lan_ips:
                print(f"    ws://{ip}:{port}")
        else:
            print("• No LAN IP detected. Are you offline? (try ipconfig/ifconfig)")

        hostname = socket.gethostname()
        fqdn = socket.getfqdn()
        print(f"Host: {hostname}   FQDN: {fqdn}")
        print("NOTE: Ensure your firewall allows inbound TCP on this port.")

        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
