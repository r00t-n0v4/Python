#!/usr/bin/env python3
"""
Bluetooth Scanner & Commander — Linux Edition
Dual-mode: Classic Bluetooth (phones!) + BLE
Multi-device: Broadcast to all  OR  Independent per-device sessions
"""

import asyncio
import sys
import re
import subprocess
import shutil
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

# ── Dependency bootstrap ──────────────────────────────────────────────────────

def install_missing():
    needed = []
    for mod, pkg in [("bleak", "bleak"), ("rich", "rich")]:
        try:
            __import__(mod)
        except ImportError:
            needed.append(pkg)
    if needed:
        print(f"[*] Installing: {', '.join(needed)} …")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *needed, "-q"])
        print("[✓] Done.\n")

install_missing()

# ── Imports ───────────────────────────────────────────────────────────────────

from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.text import Text
from rich.rule import Rule
from rich.align import Align
from rich.columns import Columns
from rich import box

# ── Theme ─────────────────────────────────────────────────────────────────────

console = Console()
CYAN   = "bright_cyan"
BLUE   = "steel_blue1"
GREEN  = "green3"
YELLOW = "yellow1"
RED    = "red1"
GREY   = "grey62"
WHITE  = "bright_white"
DIM    = "dim"

# Device colour palette — one per selected device
DEVICE_COLORS = ["bright_cyan", "bright_magenta", "bright_yellow", "bright_green",
                 "bright_red", "bright_blue", "orange1", "medium_purple1"]

# ── Device model ─────────────────────────────────────────────────────────────

@dataclass
class BTDevice:
    address: str
    name: str
    mode: str          # "classic", "ble", "dual"
    rssi: Optional[int] = None
    device_class: str = ""
    service_uuids: list = field(default_factory=list)
    _raw_ble: object = field(default=None, repr=False)
    _raw_adv: object = field(default=None, repr=False)

    def label(self) -> str:
        return self.name if self.name else self.address

# ── Known UUIDs ───────────────────────────────────────────────────────────────

KNOWN_SERVICES = {
    "0000180a-0000-1000-8000-00805f9b34fb": "Device Information",
    "0000180f-0000-1000-8000-00805f9b34fb": "Battery Service",
    "00001800-0000-1000-8000-00805f9b34fb": "Generic Access",
    "00001801-0000-1000-8000-00805f9b34fb": "Generic Attribute",
    "0000180d-0000-1000-8000-00805f9b34fb": "Heart Rate",
    "00001812-0000-1000-8000-00805f9b34fb": "HID",
    "0000110b-0000-1000-8000-00805f9b34fb": "Audio Sink",
    "0000111e-0000-1000-8000-00805f9b34fb": "Handsfree",
    "0000fe9f-0000-1000-8000-00805f9b34fb": "Google Fast Pair",
    "0000112f-0000-1000-8000-00805f9b34fb": "Phonebook Access",
    "00001105-0000-1000-8000-00805f9b34fb": "OPP File Transfer",
    "00001132-0000-1000-8000-00805f9b34fb": "Message Access",
}
KNOWN_CHARS = {
    "00002a19-0000-1000-8000-00805f9b34fb": "Battery Level",
    "00002a00-0000-1000-8000-00805f9b34fb": "Device Name",
    "00002a24-0000-1000-8000-00805f9b34fb": "Model Number",
    "00002a25-0000-1000-8000-00805f9b34fb": "Serial Number",
    "00002a26-0000-1000-8000-00805f9b34fb": "Firmware Revision",
    "00002a27-0000-1000-8000-00805f9b34fb": "Hardware Revision",
    "00002a28-0000-1000-8000-00805f9b34fb": "Software Revision",
    "00002a29-0000-1000-8000-00805f9b34fb": "Manufacturer Name",
}

MAJOR_CLASS = {
    0: "Miscellaneous", 1: "Computer", 2: "Phone",
    3: "LAN/Network", 4: "Audio/Video", 5: "Peripheral",
    6: "Imaging", 7: "Wearable", 8: "Toy", 9: "Health",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def decode_class(cod_hex: str) -> str:
    try:
        cod = int(cod_hex, 16)
        major = (cod >> 8) & 0x1F
        return MAJOR_CLASS.get(major, f"Class {cod_hex}")
    except Exception:
        return cod_hex

def rssi_bar(rssi: Optional[int]) -> Text:
    if rssi is None:
        return Text("N/A", style=GREY)
    strength = max(0, min(5, int((rssi + 100) / 14)))
    bar = "█" * strength + "░" * (5 - strength)
    color = GREEN if strength >= 4 else (YELLOW if strength >= 2 else RED)
    return Text(f"{bar} {rssi} dBm", style=color)

def mode_badge(mode: str) -> Text:
    if mode == "classic": return Text("CLASSIC", style=f"bold {BLUE}")
    if mode == "ble":     return Text("  BLE  ", style=f"bold {CYAN}")
    return                       Text(" DUAL  ", style=f"bold {GREEN}")

def service_name(uuid: str) -> str:
    return KNOWN_SERVICES.get(uuid.lower(), uuid[:8] + "…")

def char_name(uuid: str) -> str:
    return KNOWN_CHARS.get(uuid.lower(), uuid[:8] + "…")

def format_value(data: bytearray, uuid: str) -> str:
    uuid = uuid.lower()
    try:
        if uuid == "00002a19-0000-1000-8000-00805f9b34fb":
            return f"{data[0]}%"
        if uuid in (
            "00002a00-0000-1000-8000-00805f9b34fb",
            "00002a24-0000-1000-8000-00805f9b34fb",
            "00002a25-0000-1000-8000-00805f9b34fb",
            "00002a26-0000-1000-8000-00805f9b34fb",
            "00002a27-0000-1000-8000-00805f9b34fb",
            "00002a28-0000-1000-8000-00805f9b34fb",
            "00002a29-0000-1000-8000-00805f9b34fb",
        ):
            return data.decode("utf-8", errors="replace").strip("\x00")
    except Exception:
        pass
    return data.hex(" ").upper()

def check_tool(name: str) -> bool:
    return shutil.which(name) is not None

def device_color(idx: int) -> str:
    return DEVICE_COLORS[idx % len(DEVICE_COLORS)]

# ── Banner ────────────────────────────────────────────────────────────────────

def print_banner():
    console.clear()
    t = Text()
    t.append("  ╔════════════════════════════════════════════╗\n", style=f"bold {BLUE}")
    t.append("  ║  ", style=f"bold {BLUE}")
    t.append("BLUETOOTH SCANNER & COMMANDER", style=f"bold {CYAN}")
    t.append("   ║\n", style=f"bold {BLUE}")
    t.append("  ║  ", style=f"bold {BLUE}")
    t.append("Classic + BLE · Multi-Device · Linux     ", style=DIM)
    t.append("║\n", style=f"bold {BLUE}")
    t.append("  ╚════════════════════════════════════════════╝\n", style=f"bold {BLUE}")
    console.print(Align.center(t))
    console.print()

# ── Scanning ──────────────────────────────────────────────────────────────────

async def scan_classic(duration: float) -> list[BTDevice]:
    if not check_tool("bluetoothctl"):
        return []
    devices: dict[str, BTDevice] = {}
    proc = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    proc.stdin.write(b"scan on\n")
    await proc.stdin.drain()

    addr_re  = re.compile(r"\[NEW\] Device ([0-9A-F:]{17}) (.+)", re.IGNORECASE)
    rssi_re  = re.compile(r"Device ([0-9A-F:]{17}).*RSSI[:\s]+(-?\d+)", re.IGNORECASE)
    class_re = re.compile(r"Device ([0-9A-F:]{17}).*Class[:\s]+(0x[0-9A-Fa-f]+)", re.IGNORECASE)

    async def read_loop():
        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            text = line.decode(errors="replace")
            m = addr_re.search(text)
            if m:
                addr = m.group(1).upper()
                if addr not in devices:
                    devices[addr] = BTDevice(address=addr, name=m.group(2).strip(), mode="classic")
            m = rssi_re.search(text)
            if m:
                addr = m.group(1).upper()
                if addr in devices:
                    devices[addr].rssi = int(m.group(2))
            m = class_re.search(text)
            if m:
                addr = m.group(1).upper()
                if addr in devices:
                    devices[addr].device_class = decode_class(m.group(2))

    try:
        await asyncio.wait_for(read_loop(), timeout=duration)
    except asyncio.TimeoutError:
        pass
    try:
        proc.stdin.write(b"scan off\nquit\n")
        await proc.stdin.drain()
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    return list(devices.values())


async def scan_hcitool(duration: float) -> list[BTDevice]:
    if not check_tool("hcitool"):
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            "hcitool", "scan", "--flush",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=duration + 2)
        except asyncio.TimeoutError:
            proc.kill()
            stdout = b""
        result = []
        for line in stdout.decode(errors="replace").splitlines():
            m = re.match(r"\s+([0-9A-F:]{17})\s+(.+)", line, re.IGNORECASE)
            if m:
                result.append(BTDevice(address=m.group(1).upper(), name=m.group(2).strip(), mode="classic"))
        return result
    except Exception:
        return []


async def scan_ble(duration: float) -> list[BTDevice]:
    devices_map: dict[str, tuple] = {}
    def callback(device, adv_data):
        devices_map[device.address.upper()] = (device, adv_data)
    scanner = BleakScanner(detection_callback=callback)
    await scanner.start()
    await asyncio.sleep(duration)
    await scanner.stop()
    return [
        BTDevice(
            address=dev.address.upper(),
            name=dev.name or "",
            mode="ble",
            rssi=adv.rssi,
            service_uuids=list(adv.service_uuids or []),
            _raw_ble=dev, _raw_adv=adv,
        )
        for dev, adv in devices_map.values()
    ]


async def scan_all(duration: float) -> list[BTDevice]:
    with Progress(
        SpinnerColumn(spinner_name="dots2", style=CYAN),
        TextColumn(f"[{CYAN}]Scanning Classic + BLE simultaneously…"),
        BarColumn(bar_width=26, style=BLUE, complete_style=CYAN),
        TimeElapsedColumn(),
        console=console, transient=True,
    ) as progress:
        task = progress.add_task("scan", total=duration)

        async def tick():
            elapsed = 0.0
            while elapsed < duration:
                await asyncio.sleep(0.25)
                elapsed += 0.25
                progress.update(task, advance=0.25)

        classic_task = asyncio.create_task(scan_classic(duration))
        hci_task     = asyncio.create_task(scan_hcitool(duration))
        ble_task     = asyncio.create_task(scan_ble(duration))
        tick_task    = asyncio.create_task(tick())

        classic_devs, hci_devs, ble_devs = await asyncio.gather(classic_task, hci_task, ble_task)
        tick_task.cancel()

    merged: dict[str, BTDevice] = {}
    for d in classic_devs + hci_devs:
        addr = d.address
        if addr not in merged:
            merged[addr] = d
        else:
            if not merged[addr].name and d.name:
                merged[addr].name = d.name
            if merged[addr].rssi is None and d.rssi is not None:
                merged[addr].rssi = d.rssi
    for d in ble_devs:
        addr = d.address
        if addr in merged:
            merged[addr].mode = "dual"
            if not merged[addr].name and d.name:
                merged[addr].name = d.name
            if merged[addr].rssi is None:
                merged[addr].rssi = d.rssi
            merged[addr].service_uuids = d.service_uuids
            merged[addr]._raw_ble = d._raw_ble
            merged[addr]._raw_adv = d._raw_adv
        else:
            merged[addr] = d
    return list(merged.values())

# ── Device table ──────────────────────────────────────────────────────────────

def show_device_table(devices: list[BTDevice], selected: set[int] = None) -> None:
    selected = selected or set()
    table = Table(
        box=box.SIMPLE_HEAD,
        header_style=f"bold {BLUE}",
        border_style=BLUE,
        row_styles=["", "dim"],
        min_width=90,
    )
    table.add_column("✓",       width=3,  justify="center")
    table.add_column("#",       style=f"bold {CYAN}", width=4,  justify="right")
    table.add_column("Type",    width=9,  justify="center")
    table.add_column("Name",    style=WHITE, min_width=22)
    table.add_column("Address", style=GREY,  width=19)
    table.add_column("Signal",  width=18)
    table.add_column("Info",    style=GREY,  min_width=14)

    for i, d in enumerate(devices, 1):
        check = Text("●", style=f"bold {device_color(list(selected).index(i) if i in selected else 0)}") if i in selected else Text("·", style=GREY)
        name  = d.name if d.name else Text("(unknown)", style=GREY)
        info  = d.device_class or "—" if d.mode == "classic" else (
            ", ".join(service_name(s) for s in d.service_uuids[:2])
            + (" …" if len(d.service_uuids) > 2 else "")
            if d.service_uuids else "—"
        )
        table.add_row(check, str(i), mode_badge(d.mode), str(name), d.address, rssi_bar(d.rssi), info)

    console.print(Panel(table, title=f"[bold {CYAN}]Discovered Devices[/]", border_style=BLUE))


def parse_selection(raw: str, max_idx: int) -> list[int]:
    """
    Parse '1,3,5' or '1-4' or '2' or 'all' into a sorted list of 1-based indices.
    """
    raw = raw.strip().lower()
    if raw == "all":
        return list(range(1, max_idx + 1))
    indices = set()
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                for x in range(int(a), int(b) + 1):
                    if 1 <= x <= max_idx:
                        indices.add(x)
            except ValueError:
                pass
        else:
            try:
                x = int(part)
                if 1 <= x <= max_idx:
                    indices.add(x)
            except ValueError:
                pass
    return sorted(indices)

# ══════════════════════════════════════════════════════════════════════════════
# SINGLE-DEVICE ACTIONS (shared by single + independent multi-mode)
# ══════════════════════════════════════════════════════════════════════════════

# ── Classic ──────────────────────────────────────────────────────────────────

async def classic_ping(device: BTDevice, count: int = 4) -> list[str]:
    """Returns list of result lines."""
    if not check_tool("l2ping"):
        return [f"[{YELLOW}]l2ping not found[/]"]
    lines = []
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "l2ping", "-c", str(count), device.address,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        for line in stdout.decode(errors="replace").strip().splitlines():
            lo = line.lower()
            if "bytes from" in lo:
                lines.append(f"[{GREEN}]{line}[/]")
            elif "error" in lo or "unreachable" in lo:
                lines.append(f"[{RED}]{line}[/]")
            else:
                lines.append(f"[{GREY}]{line}[/]")
    except Exception as e:
        lines.append(f"[{RED}]Error: {e}[/]")
    return lines


async def classic_info_dict(device: BTDevice) -> dict[str, str]:
    """Returns {key: value} from bluetoothctl info."""
    if not check_tool("bluetoothctl"):
        return {"Error": "bluetoothctl not found"}
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl", "info", device.address,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
        result = {}
        for line in stdout.decode(errors="replace").splitlines():
            stripped = line.strip()
            if ":" in stripped and not stripped.startswith("Device"):
                key, _, val = stripped.partition(":")
                result[key.strip()] = val.strip()
        return result
    except Exception as e:
        return {"Error": str(e)}


async def classic_sdp_list(device: BTDevice) -> list[str]:
    """Returns list of SDP service names."""
    if not check_tool("sdptool"):
        return ["sdptool not found"]
    try:
        proc = await asyncio.create_subprocess_exec(
            "sdptool", "browse", device.address,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        output = stdout.decode(errors="replace")
        svc_names = re.findall(r"Service Name:\s*(.+)", output)
        profiles  = re.findall(r'"([^"]+)"\s*\(0x[0-9a-fA-F]+\)', output)
        combined  = list(dict.fromkeys(s.strip() for s in svc_names + profiles if s.strip()))
        return combined or ["No SDP services found"]
    except asyncio.TimeoutError:
        return ["Timed out"]
    except Exception as e:
        return [str(e)]

# ── BLE ───────────────────────────────────────────────────────────────────────

async def ble_read_char(client, service_list, svc_idx: int, char_idx: int):
    """Returns (formatted_value, raw_hex) or raises."""
    svc  = service_list[svc_idx]
    readable = [c for c in svc.characteristics if "read" in c.properties]
    char = readable[char_idx]
    data = bytearray(await client.read_gatt_char(char.uuid))
    return format_value(data, str(char.uuid)), data.hex(" ").upper()


async def ble_write_char(client, service_list, svc_idx: int, char_idx: int, data: bytes):
    svc     = service_list[svc_idx]
    writable = [c for c in svc.characteristics if "write" in c.properties or "write-without-response" in c.properties]
    char    = writable[char_idx]
    await client.write_gatt_char(char.uuid, data, response="write" in char.properties)


async def ble_read_all_dict(client, service_list) -> dict[str, str]:
    """Returns {char_label: value} for all readable characteristics."""
    result = {}
    for svc in service_list:
        for char in svc.characteristics:
            if "read" in char.properties:
                label = f"{service_name(str(svc.uuid))} / {char_name(str(char.uuid))}"
                try:
                    data = bytearray(await client.read_gatt_char(char.uuid))
                    result[label] = format_value(data, str(char.uuid))
                except Exception as e:
                    result[label] = f"[err] {str(e)[:30]}"
    return result

# ══════════════════════════════════════════════════════════════════════════════
# SINGLE-DEVICE INTERACTIVE SESSIONS
# ══════════════════════════════════════════════════════════════════════════════

def pick_char(service_list, filter_prop=None):
    console.print()
    idx = IntPrompt.ask(f"  [{CYAN}]Select service #[/]", default=1) - 1
    if not (0 <= idx < len(service_list)):
        console.print(f"  [{RED}]Invalid.[/]"); return None, None
    svc = service_list[idx]
    chars = [c for c in svc.characteristics if not filter_prop or filter_prop in c.properties]
    if not chars:
        console.print(f"  [{YELLOW}]No matching characteristics.[/]"); return None, None
    t = Table(box=box.MINIMAL, show_edge=False, header_style=f"bold {BLUE}")
    t.add_column("#", width=4, style=f"bold {CYAN}", justify="right")
    t.add_column("Characteristic", style=WHITE, min_width=22)
    t.add_column("UUID", style=GREY, width=38)
    t.add_column("Properties", style=YELLOW)
    for i, c in enumerate(chars, 1):
        t.add_row(str(i), char_name(str(c.uuid)), str(c.uuid), ", ".join(c.properties))
    console.print(Panel(t, title=f"[{CYAN}]Characteristics[/]", border_style=BLUE))
    ci = IntPrompt.ask(f"  [{CYAN}]Select characteristic #[/]", default=1) - 1
    if not (0 <= ci < len(chars)):
        console.print(f"  [{RED}]Invalid.[/]"); return None, None
    return svc, chars[ci]


async def session_classic(device: BTDevice):
    console.print()
    console.print(Rule(f"[bold {CYAN}]{device.label()}[/]  [{GREY}]Classic[/]", style=BLUE))
    while True:
        console.print(f"\n  [{WHITE}]1.[/] Ping")
        console.print(f"  [{WHITE}]2.[/] Device info")
        console.print(f"  [{WHITE}]3.[/] SDP services")
        console.print(f"  [{WHITE}]0.[/] Back\n")
        choice = Prompt.ask(f"  [{CYAN}]>[/]", choices=["0","1","2","3"], default="0")
        if choice == "0":
            break
        elif choice == "1":
            count = IntPrompt.ask(f"\n  [{CYAN}]Ping count[/]", default=4)
            console.print()
            for line in await classic_ping(device, count):
                console.print(f"  {line}")
        elif choice == "2":
            info = await classic_info_dict(device)
            t = Table(box=box.MINIMAL, show_edge=False, show_header=False)
            t.add_column("Key",   style=f"bold {BLUE}", width=22)
            t.add_column("Value", style=WHITE)
            for k, v in info.items():
                t.add_row(k, v)
            console.print(Panel(t, title=f"[{CYAN}]Device Info[/]", border_style=BLUE))
        elif choice == "3":
            services = await classic_sdp_list(device)
            t = Table(box=box.SIMPLE_HEAD, header_style=f"bold {BLUE}", min_width=46)
            t.add_column("#", style=f"bold {CYAN}", width=4, justify="right")
            t.add_column("Service", style=WHITE)
            for i, s in enumerate(services, 1):
                t.add_row(str(i), s)
            console.print(Panel(t, title=f"[{CYAN}]SDP Services[/]", border_style=BLUE))


async def session_ble(device: BTDevice):
    console.print()
    console.print(Rule(f"[bold {CYAN}]{device.label()}[/]  [{GREY}]BLE[/]", style=BLUE))
    console.print(f"  [{GREY}]Connecting…[/]")
    try:
        async with BleakClient(device.address, timeout=15.0) as client:
            console.print(f"  [{GREEN}]✓ Connected[/]  MTU {client.mtu_size}\n")
            service_list = list(client.services)
            if not service_list:
                console.print(f"  [{YELLOW}]No GATT services.[/]"); return

            t = Table(box=box.MINIMAL, header_style=f"bold {BLUE}", show_edge=False, min_width=70)
            t.add_column("#", width=4, style=f"bold {CYAN}", justify="right")
            t.add_column("Service", style=WHITE, min_width=22)
            t.add_column("UUID", style=GREY, width=38)
            t.add_column("Chars", justify="right", width=6)
            for i, svc in enumerate(service_list, 1):
                t.add_row(str(i), service_name(str(svc.uuid)), str(svc.uuid), str(len(svc.characteristics)))
            console.print(Panel(t, title=f"[bold {CYAN}]GATT Services[/]", border_style=BLUE))

            while True:
                console.print(f"\n  [{WHITE}]1.[/] Read characteristic")
                console.print(f"  [{WHITE}]2.[/] Write to characteristic")
                console.print(f"  [{WHITE}]3.[/] Subscribe to notifications")
                console.print(f"  [{WHITE}]4.[/] Read ALL readable characteristics")
                console.print(f"  [{WHITE}]0.[/] Disconnect\n")
                choice = Prompt.ask(f"  [{CYAN}]>[/]", choices=["0","1","2","3","4"], default="0")

                if choice == "0":
                    break
                elif choice == "1":
                    _, char = pick_char(service_list, "read")
                    if char:
                        try:
                            data = bytearray(await client.read_gatt_char(char.uuid))
                            console.print(f"\n  [{GREEN}]✓[/] {format_value(data, str(char.uuid))}")
                            console.print(f"  [{GREY}]  Raw: {data.hex(' ').upper()}[/]")
                        except Exception as e:
                            console.print(f"\n  [{RED}]✗ {e}[/]")
                elif choice == "2":
                    _, char = pick_char(service_list, "write")
                    if char:
                        raw = Prompt.ask(f"\n  [{CYAN}]Data (hex 'FF 01' or plain text)[/]")
                        try:
                            data = bytes.fromhex(raw.replace(" ", ""))
                        except ValueError:
                            data = raw.encode()
                        try:
                            await client.write_gatt_char(char.uuid, data, response="write" in char.properties)
                            console.print(f"\n  [{GREEN}]✓ Written {len(data)} byte(s)[/]")
                        except Exception as e:
                            console.print(f"\n  [{RED}]✗ {e}[/]")
                elif choice == "3":
                    _, char = pick_char(service_list, "notify")
                    if char:
                        count = IntPrompt.ask(f"  [{CYAN}]Capture how many notifications[/]", default=5)
                        received = []
                        def handler(_, data): received.append((datetime.now().strftime("%H:%M:%S.%f")[:-3], bytearray(data)))
                        console.print(f"\n  [{CYAN}]Listening… Ctrl+C to stop.[/]\n")
                        try:
                            await client.start_notify(char.uuid, handler)
                            while len(received) < count:
                                await asyncio.sleep(0.1)
                            await client.stop_notify(char.uuid)
                        except (KeyboardInterrupt, asyncio.CancelledError):
                            try: await client.stop_notify(char.uuid)
                            except: pass
                        nt = Table(box=box.SIMPLE, header_style=f"bold {BLUE}", show_edge=False)
                        nt.add_column("Time", style=GREY, width=14)
                        nt.add_column("Value", style=WHITE)
                        nt.add_column("Hex", style=GREY)
                        for ts, d in received:
                            nt.add_row(ts, format_value(d, str(char.uuid)), d.hex(" ").upper())
                        console.print(Panel(nt, title=f"[{CYAN}]Notifications[/]", border_style=BLUE))
                elif choice == "4":
                    values = await ble_read_all_dict(client, service_list)
                    at = Table(box=box.SIMPLE_HEAD, header_style=f"bold {BLUE}", min_width=80)
                    at.add_column("Characteristic", style=WHITE, min_width=38)
                    at.add_column("Value", style=GREEN, min_width=20)
                    for label, val in values.items():
                        at.add_row(label, val)
                    console.print(Panel(at, title=f"[bold {CYAN}]All Values[/]", border_style=BLUE))

    except BleakError as e:
        console.print(f"\n  [{RED}]✗ BLE failed:[/] {e}")
    except asyncio.TimeoutError:
        console.print(f"\n  [{RED}]✗ Timed out.[/]")


async def session_single(device: BTDevice):
    """Route single device to correct session type."""
    if device.mode == "ble":
        await session_ble(device)
    elif device.mode == "classic":
        await session_classic(device)
    else:
        console.print(f"\n  [{CYAN}]Dual-mode device — choose interface:[/]\n")
        console.print(f"  [{WHITE}]1.[/] Classic (ping · info · SDP)")
        console.print(f"  [{WHITE}]2.[/] BLE/GATT (read · write · notify)\n")
        c = Prompt.ask(f"  [{CYAN}]>[/]", choices=["1","2"], default="1")
        if c == "1": await session_classic(device)
        else:        await session_ble(device)

# ══════════════════════════════════════════════════════════════════════════════
# MULTI-DEVICE: BROADCAST MODE
# ══════════════════════════════════════════════════════════════════════════════

async def broadcast_menu(devices: list[BTDevice]):
    """
    Send the same command to all selected devices in parallel.
    Works best when all devices are the same type (all BLE or all Classic).
    """
    console.print()
    console.print(Rule(f"[bold {CYAN}]BROADCAST MODE[/]  [{GREY}]{len(devices)} device(s)[/]", style=BLUE))

    # Show selected devices with their colours
    for i, d in enumerate(devices):
        console.print(f"  [{device_color(i)}]●[/] [{WHITE}]{d.label()}[/]  [{GREY}]{d.address}  {d.mode.upper()}[/]")

    ble_devs     = [d for d in devices if d.mode in ("ble", "dual")]
    classic_devs = [d for d in devices if d.mode in ("classic", "dual")]

    while True:
        console.print(f"\n  [{CYAN}]Broadcast command:[/]\n")
        if classic_devs:
            console.print(f"  [{WHITE}]1.[/] Ping all Classic devices")
            console.print(f"  [{WHITE}]2.[/] Device info all Classic devices")
            console.print(f"  [{WHITE}]3.[/] SDP services all Classic devices")
        if ble_devs:
            console.print(f"  [{WHITE}]4.[/] Read all BLE characteristics (all BLE devices)")
            console.print(f"  [{WHITE}]5.[/] Write to UUID on all BLE devices")
        console.print(f"  [{WHITE}]0.[/] Back\n")

        valid = ["0"]
        if classic_devs: valid += ["1", "2", "3"]
        if ble_devs:     valid += ["4", "5"]
        choice = Prompt.ask(f"  [{CYAN}]>[/]", choices=valid, default="0")

        if choice == "0":
            break

        elif choice == "1":
            count = IntPrompt.ask(f"\n  [{CYAN}]Ping count per device[/]", default=3)
            console.print(f"\n  [{CYAN}]Pinging {len(classic_devs)} device(s) in parallel…[/]\n")
            tasks   = [asyncio.create_task(classic_ping(d, count)) for d in classic_devs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, (d, res) in enumerate(zip(classic_devs, results)):
                color = device_color(devices.index(d))
                console.print(f"  [{color}]━━ {d.label()} ({d.address}) ━━[/]")
                if isinstance(res, Exception):
                    console.print(f"  [{RED}]Error: {res}[/]")
                else:
                    for line in res:
                        console.print(f"  {line}")
                console.print()

        elif choice == "2":
            console.print(f"\n  [{CYAN}]Fetching info for {len(classic_devs)} device(s) in parallel…[/]\n")
            tasks   = [asyncio.create_task(classic_info_dict(d)) for d in classic_devs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, (d, res) in enumerate(zip(classic_devs, results)):
                color = device_color(devices.index(d))
                if isinstance(res, Exception):
                    console.print(Panel(f"[{RED}]Error: {res}[/]",
                        title=f"[{color}]{d.label()}[/]", border_style=color))
                else:
                    t = Table(box=box.MINIMAL, show_edge=False, show_header=False)
                    t.add_column("Key",   style=f"bold {BLUE}", width=22)
                    t.add_column("Value", style=WHITE)
                    for k, v in res.items():
                        t.add_row(k, v)
                    if t.row_count == 0:
                        t.add_row("Note", "No info cached (try pairing first)")
                    console.print(Panel(t, title=f"[bold {color}]{d.label()}[/]", border_style=color))

        elif choice == "3":
            console.print(f"\n  [{CYAN}]Querying SDP for {len(classic_devs)} device(s) in parallel…[/]\n")
            tasks   = [asyncio.create_task(classic_sdp_list(d)) for d in classic_devs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for d, res in zip(classic_devs, results):
                color = device_color(devices.index(d))
                services = [str(res)] if isinstance(res, Exception) else res
                t = Table(box=box.SIMPLE_HEAD, header_style=f"bold {BLUE}", min_width=44)
                t.add_column("#", style=f"bold {CYAN}", width=4, justify="right")
                t.add_column("Service", style=WHITE)
                for j, s in enumerate(services, 1):
                    t.add_row(str(j), s)
                console.print(Panel(t, title=f"[bold {color}]{d.label()}[/]", border_style=color))

        elif choice == "4":
            console.print(f"\n  [{CYAN}]Reading all characteristics on {len(ble_devs)} device(s) in parallel…[/]\n")

            async def read_all_for(device: BTDevice):
                async with BleakClient(device.address, timeout=15.0) as client:
                    return await ble_read_all_dict(client, list(client.services))

            tasks   = [asyncio.create_task(read_all_for(d)) for d in ble_devs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for d, res in zip(ble_devs, results):
                color = device_color(devices.index(d))
                if isinstance(res, Exception):
                    console.print(Panel(f"[{RED}]{res}[/]",
                        title=f"[{color}]{d.label()}[/]", border_style=color))
                else:
                    t = Table(box=box.SIMPLE_HEAD, header_style=f"bold {BLUE}", min_width=70)
                    t.add_column("Characteristic", style=WHITE, min_width=36)
                    t.add_column("Value", style=GREEN, min_width=20)
                    for label, val in res.items():
                        t.add_row(label, val)
                    console.print(Panel(t, title=f"[bold {color}]{d.label()}[/]", border_style=color))

        elif choice == "5":
            uuid = Prompt.ask(f"\n  [{CYAN}]Characteristic UUID to write to[/]")
            raw  = Prompt.ask(f"  [{CYAN}]Data (hex 'FF 01' or plain text)[/]")
            try:
                data = bytes.fromhex(raw.replace(" ", ""))
            except ValueError:
                data = raw.encode()

            console.print(f"\n  [{CYAN}]Writing to {len(ble_devs)} device(s) in parallel…[/]\n")

            async def write_to(device: BTDevice):
                async with BleakClient(device.address, timeout=15.0) as client:
                    await client.write_gatt_char(uuid, data)
                    return f"Written {len(data)} byte(s)"

            tasks   = [asyncio.create_task(write_to(d)) for d in ble_devs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for d, res in zip(ble_devs, results):
                color = device_color(devices.index(d))
                if isinstance(res, Exception):
                    console.print(f"  [{color}]●[/] [{WHITE}]{d.label()}[/]  [{RED}]✗ {res}[/]")
                else:
                    console.print(f"  [{color}]●[/] [{WHITE}]{d.label()}[/]  [{GREEN}]✓ {res}[/]")

# ══════════════════════════════════════════════════════════════════════════════
# MULTI-DEVICE: INDEPENDENT MODE
# ══════════════════════════════════════════════════════════════════════════════

async def independent_menu(devices: list[BTDevice]):
    """
    Cycle through each selected device one at a time for full per-device control.
    """
    console.print()
    console.print(Rule(f"[bold {CYAN}]INDEPENDENT MODE[/]  [{GREY}]{len(devices)} device(s)[/]", style=BLUE))
    console.print(f"  [{GREY}]You'll interact with each device in turn.[/]\n")

    for i, d in enumerate(devices):
        color = device_color(i)
        console.print(f"  [{color}]━━━━━ Device {i+1}/{len(devices)}: {d.label()} ━━━━━[/]\n")
        await session_single(d)
        console.print()
        if i < len(devices) - 1:
            if not Confirm.ask(f"  [{CYAN}]Continue to next device ({devices[i+1].label()})?[/]", default=True):
                break

    console.print(f"\n  [{GREY}]Independent session complete.[/]")

# ══════════════════════════════════════════════════════════════════════════════
# MULTI-DEVICE ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

async def handle_multi(selected_devices: list[BTDevice]):
    console.print()
    console.print(Rule(f"[bold {CYAN}]MULTI-DEVICE[/]  [{GREY}]{len(selected_devices)} selected[/]", style=BLUE))
    console.print()
    for i, d in enumerate(selected_devices):
        console.print(f"  [{device_color(i)}]●[/] [{WHITE}]{d.label()}[/]  [{GREY}]{d.address}  {d.mode.upper()}[/]")

    console.print(f"\n  [{CYAN}]Choose a mode:[/]\n")
    console.print(f"  [{WHITE}]1.[/] [{CYAN}]Broadcast[/]  [{GREY}]— same command sent to all devices in parallel[/]")
    console.print(f"  [{WHITE}]2.[/] [{CYAN}]Independent[/] [{GREY}]— interact with each device one by one[/]")
    console.print(f"  [{WHITE}]0.[/] Back\n")

    choice = Prompt.ask(f"  [{CYAN}]>[/]", choices=["0","1","2"], default="1")
    if choice == "1":
        await broadcast_menu(selected_devices)
    elif choice == "2":
        await independent_menu(selected_devices)

# ══════════════════════════════════════════════════════════════════════════════
# PREREQUISITES
# ══════════════════════════════════════════════════════════════════════════════

def check_prerequisites():
    missing = [
        (t, p, d) for t, p, d in [
            ("bluetoothctl", "bluez", "Classic scan + device info"),
            ("hcitool",      "bluez", "Classic scan fallback"),
            ("l2ping",       "bluez", "Ping"),
            ("sdptool",      "bluez", "SDP service listing"),
        ] if not check_tool(t)
    ]
    if missing:
        lines = "\n".join(
            f"  [{YELLOW}]⚠  {t}[/] [{GREY}]({d})[/]  →  [{WHITE}]sudo apt install {p}[/]"
            for t, p, d in missing
        )
        console.print(Panel(lines, title=f"[{YELLOW}]Optional tools not found[/]", border_style=YELLOW))
        console.print(f"  [{GREY}]BLE scanning still works. Classic BT needs bluez.[/]\n")

# ══════════════════════════════════════════════════════════════════════════════
# BLE ADVERTISE — broadcast your Linux machine as a custom BLE peripheral
# Uses raw HCI commands via hcitool/hciconfig (part of bluez, no extra deps)
# ══════════════════════════════════════════════════════════════════════════════

# ── Advertisement payload builders ───────────────────────────────────────────
# Each returns a hex string suitable for: hcitool -i hci0 cmd 0x08 0x0008 ...
# Format: length | type | data  (AD structures, no BT header)

def _adv_name(name: str) -> bytes:
    """Complete Local Name (type 0x09)."""
    n = name.encode("utf-8")[:28]
    return bytes([len(n) + 1, 0x09]) + n

def _adv_flags(flags: int = 0x06) -> bytes:
    """Flags (type 0x01). 0x06 = LE General Discoverable + BR/EDR not supported."""
    return bytes([0x02, 0x01, flags])

def _adv_manufacturer(company_id: int, payload: bytes) -> bytes:
    """Manufacturer Specific Data (type 0xFF)."""
    data = bytes([company_id & 0xFF, (company_id >> 8) & 0xFF]) + payload
    return bytes([len(data) + 1, 0xFF]) + data

def _adv_tx_power(dbm: int = 0) -> bytes:
    """TX Power Level (type 0x0A)."""
    return bytes([0x02, 0x0A, dbm & 0xFF])

def _build_payload(*parts: bytes) -> bytes:
    """Concatenate AD structures, pad/truncate to 31 bytes."""
    combined = b"".join(parts)
    if len(combined) > 31:
        combined = combined[:31]
    return combined.ljust(31, b"\x00")


# ── Device presets ────────────────────────────────────────────────────────────
# Each preset dict:
#   name        : display label
#   group       : "samsung" | "apple" | "windows" | "android" | "generic"
#   description : shown in menu
#   payload_fn  : callable(_ignored_name) -> bytes  (31-byte adv payload)
#   scan_fn     : optional callable(_ignored_name) -> bytes (31-byte scan rsp)
#
# Samsung fast-pair  — company ID 0x0075 (Samsung Electronics)
# Apple proximity    — company ID 0x004C
# Windows Swift Pair — company ID 0x0006
# Android Fast Pair  — service UUID 0xFE2C + 3-byte model ID
#
# Payloads are fixed hardware fingerprints; the "name" argument is unused for
# fast-pair presets because the device name comes from Samsung/Apple/Google's
# cloud lookup of the model ID embedded in the payload.

def _adv_service_data16(uuid16: int, data: bytes) -> bytes:
    """Service Data — 16-bit UUID (type 0x16)."""
    body = bytes([uuid16 & 0xFF, (uuid16 >> 8) & 0xFF]) + data
    return bytes([len(body) + 1, 0x16]) + body

def _adv_uuid16_complete(uuid16: int) -> bytes:
    """Complete List of 16-bit UUIDs (type 0x03)."""
    return bytes([0x03, 0x03, uuid16 & 0xFF, (uuid16 >> 8) & 0xFF])

# ── Samsung Galaxy Buds presets ───────────────────────────────────────────────
# Triggers native "Galaxy Buds" pairing card on Samsung/Android phones.
# company ID 0x0075, adv + scan response both carry manufacturer data.

def _samsung_buds2(_=None):
    # Galaxy Buds 2
    adv_data  = bytes.fromhex("42 09 81 02 14 15 03 21 01 09 AB 0C 01 46 06 3C DD 0A 00 00 00 00 A7 00".replace(" ",""))
    scan_data = bytes.fromhex("00 C3 A3 D7 B1 17 40 52 64 64 00 01 04".replace(" ",""))
    return _build_payload(_adv_flags(0x06), _adv_manufacturer(0x0075, adv_data))

def _samsung_buds2_scan(_=None):
    scan_data = bytes.fromhex("00C3A3D7B11740526464000104")
    return _build_payload(_adv_manufacturer(0x0075, scan_data))

def _samsung_buds2pro(_=None):
    # Galaxy Buds 2 Pro
    adv_data = bytes.fromhex("4209810214150321010920000146063CDD0A00000000A700")
    return _build_payload(_adv_flags(0x06), _adv_manufacturer(0x0075, adv_data))

def _samsung_buds2pro_scan(_=None):
    scan_data = bytes.fromhex("00C3A3D7B11740526464000104")
    return _build_payload(_adv_manufacturer(0x0075, scan_data))

def _samsung_budsfe(_=None):
    # Galaxy Buds FE
    adv_data = bytes.fromhex("420981021415032101094F000146063CDD0A00000000A700")
    return _build_payload(_adv_flags(0x06), _adv_manufacturer(0x0075, adv_data))

def _samsung_budsfe_scan(_=None):
    scan_data = bytes.fromhex("00C3A3D7B11740526464000104")
    return _build_payload(_adv_manufacturer(0x0075, scan_data))

def _samsung_buds3(_=None):
    # Galaxy Buds 3
    adv_data = bytes.fromhex("42098102141503210109BE000146063CDD0A00000000A700")
    return _build_payload(_adv_flags(0x06), _adv_manufacturer(0x0075, adv_data))

def _samsung_buds3_scan(_=None):
    scan_data = bytes.fromhex("00C3A3D7B11740526464000104")
    return _build_payload(_adv_manufacturer(0x0075, scan_data))

# ── Apple proximity presets ───────────────────────────────────────────────────
# Triggers native "AirPods" / device card popup on iPhone/iPad.
# company ID 0x004C.  Byte at offset 4 (0-indexed in raw-data) = model nibble.

def _apple_airpods(_=None):
    raw = bytes.fromhex("071907022075aa3001000045121212000000000000000000000000")
    return _build_payload(_adv_flags(0x1A), _adv_manufacturer(0x004C, raw))

def _apple_airpods_pro(_=None):
    raw = bytes.fromhex("0719070e2075aa3001000045121212000000000000000000000000")
    return _build_payload(_adv_flags(0x1A), _adv_manufacturer(0x004C, raw))

def _apple_airpods_pro2(_=None):
    raw = bytes.fromhex("071907142075aa3001000045121212000000000000000000000000")
    return _build_payload(_adv_flags(0x1A), _adv_manufacturer(0x004C, raw))

def _apple_airpods_max(_=None):
    raw = bytes.fromhex("0719070a2075aa3001000045121212000000000000000000000000")
    return _build_payload(_adv_flags(0x1A), _adv_manufacturer(0x004C, raw))

def _apple_airpods3(_=None):
    raw = bytes.fromhex("071907132075aa3001000045121212000000000000000000000000")
    return _build_payload(_adv_flags(0x1A), _adv_manufacturer(0x004C, raw))

def _apple_airpods2(_=None):
    raw = bytes.fromhex("0719070f2075aa3001000045121212000000000000000000000000")
    return _build_payload(_adv_flags(0x1A), _adv_manufacturer(0x004C, raw))

def _apple_homepod(_=None):
    raw = bytes.fromhex("04042a0000000f05c10b604c950000100000000000")
    return _build_payload(_adv_flags(0x1A), _adv_manufacturer(0x004C, raw))

# ── Windows Swift Pair presets ────────────────────────────────────────────────
# Triggers native Swift Pair popup on Windows 10/11.
# company ID 0x0006 (Microsoft).  Format: 03 00 <pairing_mode> <utf8 name hex>

def _windows_swiftpair(name: str = "My BT Device") -> bytes:
    name_hex = name.encode("utf-8")[:20]
    payload  = bytes([0x03, 0x00, 0x08]) + name_hex
    return _build_payload(_adv_flags(0x06), _adv_manufacturer(0x0006, payload))

# ── Android Fast Pair presets ─────────────────────────────────────────────────
# Triggers Google Fast Pair popup on Android 6+.
# Uses service UUID 0xFE2C + 3-byte model ID.  Google resolves the model ID
# to a device name + image from their cloud database.

def _android_fastpair_svc(model_id_bytes: bytes) -> bytes:
    """Build adv payload with Fast Pair service data."""
    return _build_payload(
        _adv_flags(0x06),
        _adv_tx_power(0),
        _adv_uuid16_complete(0xFE2C),
        _adv_service_data16(0xFE2C, model_id_bytes),
    )

def _android_pixel_buds(_=None):
    return _android_fastpair_svc(bytes.fromhex("92BBBD"))

def _android_jbl_flip6(_=None):
    return _android_fastpair_svc(bytes.fromhex("821F66"))

def _android_sony_xm5(_=None):
    return _android_fastpair_svc(bytes.fromhex("D446A7"))

def _android_bose_nc700(_=None):
    return _android_fastpair_svc(bytes.fromhex("CD8256"))

def _android_jbl_buds_pro(_=None):
    return _android_fastpair_svc(bytes.fromhex("F52494"))

# ── Generic presets ───────────────────────────────────────────────────────────

def _preset_generic_audio(name: str) -> bytes:
    return _build_payload(
        _adv_flags(0x06),
        _adv_uuid16_complete(0x110B),
        _adv_name(name),
    )

def _preset_generic_audio_scan(name: str) -> bytes:
    return _build_payload(_adv_name(name), _adv_tx_power(4))

def _preset_hid(name: str) -> bytes:
    return _build_payload(_adv_flags(0x06), _adv_uuid16_complete(0x1812), _adv_name(name))

def _preset_generic(name: str) -> bytes:
    return _build_payload(_adv_flags(0x06), _adv_uuid16_complete(0x1800), _adv_name(name))


# ── Preset registry ───────────────────────────────────────────────────────────

PRESETS = [
    # ── Samsung ──────────────────────────────────────────────────────────────
    {
        "group": "samsung", "name": "Galaxy Buds 2",
        "description": "Fast-pair popup on Samsung / Android phones",
        "payload_fn": _samsung_buds2, "scan_fn": _samsung_buds2_scan,
    },
    {
        "group": "samsung", "name": "Galaxy Buds 2 Pro",
        "description": "Fast-pair popup on Samsung / Android phones",
        "payload_fn": _samsung_buds2pro, "scan_fn": _samsung_buds2pro_scan,
    },
    {
        "group": "samsung", "name": "Galaxy Buds FE",
        "description": "Fast-pair popup on Samsung / Android phones",
        "payload_fn": _samsung_budsfe, "scan_fn": _samsung_budsfe_scan,
    },
    {
        "group": "samsung", "name": "Galaxy Buds 3",
        "description": "Fast-pair popup on Samsung / Android phones",
        "payload_fn": _samsung_buds3, "scan_fn": _samsung_buds3_scan,
    },
    # ── Apple ─────────────────────────────────────────────────────────────────
    {
        "group": "apple", "name": "AirPods (1st gen)",
        "description": "Proximity popup on iPhone / iPad",
        "payload_fn": _apple_airpods, "scan_fn": None,
    },
    {
        "group": "apple", "name": "AirPods 2",
        "description": "Proximity popup on iPhone / iPad",
        "payload_fn": _apple_airpods2, "scan_fn": None,
    },
    {
        "group": "apple", "name": "AirPods 3",
        "description": "Proximity popup on iPhone / iPad",
        "payload_fn": _apple_airpods3, "scan_fn": None,
    },
    {
        "group": "apple", "name": "AirPods Pro",
        "description": "Proximity popup on iPhone / iPad",
        "payload_fn": _apple_airpods_pro, "scan_fn": None,
    },
    {
        "group": "apple", "name": "AirPods Pro 2",
        "description": "Proximity popup on iPhone / iPad",
        "payload_fn": _apple_airpods_pro2, "scan_fn": None,
    },
    {
        "group": "apple", "name": "AirPods Max",
        "description": "Proximity popup on iPhone / iPad",
        "payload_fn": _apple_airpods_max, "scan_fn": None,
    },
    {
        "group": "apple", "name": "HomePod Setup",
        "description": "HomePod setup card on iPhone / iPad",
        "payload_fn": _apple_homepod, "scan_fn": None,
    },
    # ── Windows ───────────────────────────────────────────────────────────────
    {
        "group": "windows", "name": "Windows Swift Pair (custom name)",
        "description": "Swift Pair popup on Windows 10/11 — you set the device name",
        "payload_fn": _windows_swiftpair, "scan_fn": None,
    },
    # ── Android Fast Pair ─────────────────────────────────────────────────────
    {
        "group": "android", "name": "Google Pixel Buds",
        "description": "Fast Pair popup on Android 6+ (Google)",
        "payload_fn": _android_pixel_buds, "scan_fn": None,
    },
    {
        "group": "android", "name": "JBL Flip 6",
        "description": "Fast Pair popup on Android 6+",
        "payload_fn": _android_jbl_flip6, "scan_fn": None,
    },
    {
        "group": "android", "name": "Sony WH-1000XM5",
        "description": "Fast Pair popup on Android 6+",
        "payload_fn": _android_sony_xm5, "scan_fn": None,
    },
    {
        "group": "android", "name": "Bose NC 700",
        "description": "Fast Pair popup on Android 6+",
        "payload_fn": _android_bose_nc700, "scan_fn": None,
    },
    {
        "group": "android", "name": "JBL Buds Pro",
        "description": "Fast Pair popup on Android 6+",
        "payload_fn": _android_jbl_buds_pro, "scan_fn": None,
    },
    # ── Generic ───────────────────────────────────────────────────────────────
    {
        "group": "generic", "name": "Generic Audio Device",
        "description": "Audio Sink — shows in standard BT scanners on any OS",
        "payload_fn": _preset_generic_audio, "scan_fn": _preset_generic_audio_scan,
    },
    {
        "group": "generic", "name": "BLE HID / Keyboard",
        "description": "HID service — shows as input device",
        "payload_fn": _preset_hid, "scan_fn": None,
    },
    {
        "group": "generic", "name": "Generic BLE Device",
        "description": "Minimal — discoverable by all BT scanners",
        "payload_fn": _preset_generic, "scan_fn": None,
    },
    # ── Custom ────────────────────────────────────────────────────────────────
    {
        "group": "custom", "name": "Custom (build your own)",
        "description": "Choose services, manufacturer data, TX power manually",
        "payload_fn": None, "scan_fn": None,
    },
]

GROUP_LABELS = {
    "samsung": f"📱 Samsung",
    "apple":   f"🍎 Apple",
    "windows": f"🪟 Windows",
    "android": f"🤖 Android Fast Pair",
    "generic": f"📡 Generic BLE",
    "custom":  f"🔧 Custom",
}


# ── HCI helpers ───────────────────────────────────────────────────────────────

async def _hci_cmd(hci_iface: str, ogf: int, ocf: int, params: bytes) -> bool:
    """
    Send a raw HCI command via: hcitool -i <iface> cmd <ogf> <ocf> <params...>
    Returns True on success.
    """
    if not check_tool("hcitool"):
        console.print(f"  [{RED}]✗ hcitool not found. Install bluez.[/]")
        return False
    hex_params = " ".join(f"0x{b:02x}" for b in params)
    cmd = ["sudo", "hcitool", "-i", hci_iface, "cmd",
           f"0x{ogf:02x}", f"0x{ocf:02x}"] + hex_params.split()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=3)
        return proc.returncode == 0
    except Exception:
        return False


async def hci_set_adv_data(iface: str, payload: bytes) -> bool:
    """HCI LE Set Advertising Data (OGF=0x08, OCF=0x0008)."""
    assert len(payload) == 31
    # Param: 1 byte length of significant part + 31 bytes data
    sig_len = next((i for i in range(30, -1, -1) if payload[i] != 0), 0) + 1
    params = bytes([sig_len]) + payload
    return await _hci_cmd(iface, 0x08, 0x0008, params)


async def hci_set_scan_rsp(iface: str, payload: bytes) -> bool:
    """HCI LE Set Scan Response Data (OGF=0x08, OCF=0x0009)."""
    assert len(payload) == 31
    sig_len = next((i for i in range(30, -1, -1) if payload[i] != 0), 0) + 1
    params = bytes([sig_len]) + payload
    return await _hci_cmd(iface, 0x08, 0x0009, params)


async def hci_set_adv_params(iface: str,
                              interval_ms: float = 100.0,
                              adv_type: int = 0x00) -> bool:
    """
    HCI LE Set Advertising Parameters (OGF=0x08, OCF=0x0006).
    adv_type 0x00 = ADV_IND (connectable undirected, most visible)
    adv_type 0x02 = ADV_SCAN_IND (scannable, non-connectable)
    adv_type 0x03 = ADV_NONCONN_IND (non-connectable, non-scannable)
    """
    interval = int(interval_ms / 0.625)
    lo_min = interval & 0xFF; hi_min = (interval >> 8) & 0xFF
    lo_max = interval & 0xFF; hi_max = (interval >> 8) & 0xFF
    params = bytes([
        lo_min, hi_min,   # min interval
        lo_max, hi_max,   # max interval
        adv_type,         # advertising type
        0x00,             # own address type: public
        0x00,             # peer address type
        0x00,0x00,0x00,0x00,0x00,0x00,  # peer address
        0x07,             # channel map: 37+38+39
        0x00,             # filter policy: all
    ])
    return await _hci_cmd(iface, 0x08, 0x0006, params)


async def hci_set_adv_enable(iface: str, enable: bool) -> bool:
    """HCI LE Set Advertise Enable (OGF=0x08, OCF=0x000A)."""
    return await _hci_cmd(iface, 0x08, 0x000A, bytes([0x01 if enable else 0x00]))


async def hci_set_local_name(iface: str, name: str) -> bool:
    """Set the HCI local name (shows in Classic inquiry and some BLE stacks)."""
    if not check_tool("hciconfig"):
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "hciconfig", iface, "name", name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        return proc.returncode == 0
    except Exception:
        return False


def _list_hci_interfaces() -> list[str]:
    """Return available hciX interface names."""
    try:
        result = subprocess.run(
            ["hciconfig"], capture_output=True, text=True, timeout=3
        )
        return re.findall(r"^(hci\d+)", result.stdout, re.MULTILINE)
    except Exception:
        return ["hci0"]


# ── Custom payload builder ────────────────────────────────────────────────────

def build_custom_payload(device_name: str) -> tuple[bytes, Optional[bytes]]:
    """Interactive wizard to build a custom advertisement payload."""
    console.print(f"\n  [{CYAN}]Custom Advertisement Builder[/]\n")

    parts: list[bytes] = [_adv_flags(0x06)]
    scan_parts: list[bytes] = []

    # Services
    console.print(f"  [{GREY}]Common service UUIDs (16-bit hex):[/]")
    svc_table = Table(box=box.MINIMAL, show_edge=False, show_header=False)
    svc_table.add_column("UUID", style=CYAN, width=8)
    svc_table.add_column("Name", style=WHITE)
    for uuid, name in [
        ("0x180D", "Heart Rate"), ("0x180F", "Battery"),
        ("0x1812", "HID/Keyboard"), ("0x110B", "Audio Sink"),
        ("0x110A", "Audio Source"), ("0x1816", "Cycling Speed"),
        ("0x180A", "Device Info"), ("0x1800", "Generic Access"),
    ]:
        svc_table.add_row(uuid, name)
    console.print(svc_table)

    raw_uuids = Prompt.ask(
        f"\n  [{CYAN}]Enter service UUIDs (comma-separated hex, e.g. 0x180D,0x180F) or blank to skip[/]",
        default=""
    ).strip()
    if raw_uuids:
        for u in raw_uuids.split(","):
            try:
                uid = int(u.strip(), 16)
                parts.append(_adv_uuid16(uid))
            except ValueError:
                console.print(f"  [{YELLOW}]Skipping invalid UUID: {u}[/]")

    # TX Power
    if Confirm.ask(f"  [{CYAN}]Include TX power level?[/]", default=False):
        dbm = IntPrompt.ask(f"  [{CYAN}]TX power (dBm, typically -20 to +4)[/]", default=0)
        parts.append(_adv_tx_power(dbm))

    # Manufacturer data
    if Confirm.ask(f"  [{CYAN}]Include manufacturer-specific data?[/]", default=False):
        company_raw = Prompt.ask(f"  [{CYAN}]Company ID (hex, e.g. 0x004C for Apple, 0x0075 for Samsung)[/]", default="0x FFFF")
        payload_raw = Prompt.ask(f"  [{CYAN}]Manufacturer payload (hex bytes, e.g. 01 02 03)[/]", default="")
        try:
            company_id = int(company_raw.strip(), 16)
            mfr_data   = bytes.fromhex(payload_raw.replace(" ", "")) if payload_raw.strip() else b"\x00"
            parts.append(_adv_manufacturer(company_id, mfr_data))
        except ValueError as e:
            console.print(f"  [{YELLOW}]Skipping manufacturer data: {e}[/]")

    # Name in adv payload
    parts.append(_adv_name(device_name))

    # Scan response
    scan_rsp = None
    if Confirm.ask(f"  [{CYAN}]Also set a scan response (extra data sent when scanned)?[/]", default=True):
        scan_parts.append(_adv_name(device_name))
        scan_parts.append(_adv_tx_power(0))
        scan_rsp = _build_payload(*scan_parts)

    return _build_payload(*parts), scan_rsp


# ── Advertise session ─────────────────────────────────────────────────────────

async def advertise_menu():
    console.print()
    console.print(Rule(f"[bold {CYAN}]BLE ADVERTISE[/]  [{GREY}]broadcast this machine as a BLE peripheral[/]", style=BLUE))
    console.print()

    # Check tools
    if not check_tool("hcitool") or not check_tool("hciconfig"):
        console.print(Panel(
            f"  [{RED}]hcitool / hciconfig not found.[/]\n\n"
            f"  Install with:  [{WHITE}]sudo apt install bluez[/]\n"
            f"  This feature requires sudo.",
            border_style=RED, expand=False,
        ))
        return

    # Pick HCI interface
    interfaces = _list_hci_interfaces()
    if not interfaces:
        console.print(f"  [{RED}]No Bluetooth interfaces found (hci0, hci1…)[/]")
        return

    if len(interfaces) == 1:
        iface = interfaces[0]
        console.print(f"  [{GREY}]Using interface:[/] [{WHITE}]{iface}[/]\n")
    else:
        for i, ifc in enumerate(interfaces, 1):
            console.print(f"  [{WHITE}]{i}.[/] {ifc}")
        idx = IntPrompt.ask(f"  [{CYAN}]Select interface[/]", default=1) - 1
        iface = interfaces[max(0, min(idx, len(interfaces)-1))]

    # Show preset menu grouped by platform
    console.print(f"\n  [{CYAN}]Choose a device preset to advertise as:[/]\n")
    preset_table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {BLUE}", min_width=76)
    preset_table.add_column("#",           style=f"bold {CYAN}", width=4, justify="right")
    preset_table.add_column("Platform",    style=BLUE, width=20)
    preset_table.add_column("Device",      style=WHITE, min_width=26)
    preset_table.add_column("Description", style=GREY)

    last_group = None
    for i, p in enumerate(PRESETS, 1):
        group_label = GROUP_LABELS.get(p["group"], p["group"])
        display_group = group_label if p["group"] != last_group else ""
        last_group = p["group"]
        preset_table.add_row(str(i), display_group, p["name"], p["description"])

    console.print(preset_table)

    preset_idx = IntPrompt.ask(f"\n  [{CYAN}]Select preset[/]", default=1) - 1
    preset_idx = max(0, min(preset_idx, len(PRESETS) - 1))
    preset = PRESETS[preset_idx]

    # Device name — only meaningful for Windows Swift Pair and Generic/Custom.
    # For Samsung/Apple/Android the display name comes from the vendor cloud
    # model lookup; the HCI local name field is ignored by those stacks.
    needs_name = preset["group"] in ("windows", "generic", "custom")
    if needs_name:
        default_name = preset["name"] if preset["payload_fn"] else "My BLE Device"
        device_name = Prompt.ask(
            f"  [{CYAN}]Device name to broadcast[/]",
            default=default_name,
        )
    else:
        device_name = preset["name"]
        console.print(
            f"\n  [{GREY}]ℹ  Device name is resolved by {preset['group'].title()} "
            f"from their cloud model registry — local name field unused.[/]"
        )

    # Advertisement interval
    interval_ms = float(Prompt.ask(
        f"  [{CYAN}]Advertisement interval (ms, default 100)[/]",
        default="100",
    ))

    # Advertisement type
    console.print(f"\n  [{CYAN}]Advertisement type:[/]")
    console.print(f"  [{WHITE}]1.[/] Connectable undirected  [{GREY}](ADV_IND — most visible, default)[/]")
    console.print(f"  [{WHITE}]2.[/] Scannable non-connectable [{GREY}](ADV_SCAN_IND — visible, not connectable)[/]")
    console.print(f"  [{WHITE}]3.[/] Non-connectable          [{GREY}](ADV_NONCONN_IND — passive beacon)[/]")
    adv_type_map = {"1": 0x00, "2": 0x02, "3": 0x03}
    adv_type = adv_type_map[Prompt.ask(f"  [{CYAN}]>[/]", choices=["1","2","3"], default="1")]

    # Build payload
    if preset["payload_fn"] is None:
        # Custom
        adv_payload, scan_payload = build_custom_payload(device_name)
    else:
        adv_payload  = preset["payload_fn"](device_name)
        scan_fn      = preset.get("scan_fn")
        scan_payload = scan_fn(device_name) if scan_fn else None

    # Show what we're about to broadcast
    console.print(f"\n  [{CYAN}]Advertisement payload ({len(adv_payload)} bytes):[/]")
    console.print(f"  [{GREY}]{adv_payload.hex(' ').upper()}[/]")
    if scan_payload:
        console.print(f"  [{CYAN}]Scan response payload:[/]")
        console.print(f"  [{GREY}]{scan_payload.hex(' ').upper()}[/]")
    console.print()

    if not Confirm.ask(f"  [{CYAN}]Start advertising?[/]  [{GREY}](requires sudo)[/]", default=True):
        return

    # Start advertising
    console.print(f"\n  [{CYAN}]Configuring {iface}…[/]")

    # Bring interface up
    await asyncio.create_subprocess_exec(
        "sudo", "hciconfig", iface, "up",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.sleep(0.3)

    # Stop any existing advertising first
    await hci_set_adv_enable(iface, False)
    await asyncio.sleep(0.1)

    # Set local name
    await hci_set_local_name(iface, device_name)

    # Set parameters
    ok = await hci_set_adv_params(iface, interval_ms=interval_ms, adv_type=adv_type)
    if not ok:
        console.print(f"  [{YELLOW}]⚠  Could not set adv params (continuing anyway)[/]")

    # Set advertisement data
    ok = await hci_set_adv_data(iface, adv_payload)
    if not ok:
        console.print(f"  [{RED}]✗ Failed to set advertisement data. Are you running with sudo?[/]")
        return

    # Set scan response if provided
    if scan_payload:
        await hci_set_scan_rsp(iface, scan_payload)

    # Enable advertising
    ok = await hci_set_adv_enable(iface, True)
    if not ok:
        console.print(f"  [{RED}]✗ Failed to enable advertising.[/]")
        return

    console.print(f"\n  [{GREEN}]✓ Broadcasting as:[/] [{WHITE}]{device_name}[/]")
    console.print(f"  [{GREEN}]  Preset:[/]   [{WHITE}]{preset['name']}[/]")
    console.print(f"  [{GREEN}]  Interface:[/] [{WHITE}]{iface}[/]")
    console.print(f"  [{GREEN}]  Interval:[/]  [{WHITE}]{interval_ms} ms[/]")
    console.print(f"\n  [{GREY}]Your device should now appear in the Bluetooth scanner of nearby devices.[/]")
    console.print(f"  [{GREY}]Press [{WHITE}]Enter[/][{GREY}] to stop advertising.[/]\n")

    # Keep advertising until user presses Enter
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input)
    except (KeyboardInterrupt, EOFError):
        pass

    # Stop advertising
    await hci_set_adv_enable(iface, False)
    console.print(f"\n  [{CYAN}]✓ Advertising stopped.[/]")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    print_banner()
    check_prerequisites()

    console.print(Panel(
        f"  [{CYAN}]📡 Modes:[/]\n\n"
        f"  [{WHITE}]scan[/]  [{GREY}]Discover nearby Classic + BLE devices and interact with them[/]\n"
        f"  [{WHITE}]adv[/]   [{GREY}]Advertise this machine as a custom BLE peripheral[/]",
        border_style=BLUE, expand=False,
    ))
    console.print()

    while True:
        mode = Prompt.ask(
            f"[{CYAN}]Mode[/] [{GREY}]([{WHITE}]scan[/] / [{WHITE}]adv[/] / [{WHITE}]q[/]uit)[/]",
            default="scan",
        ).strip().lower()

        if mode in ("q", "quit"):
            break

        elif mode in ("adv", "advertise"):
            await advertise_menu()
            console.print()
            print_banner()
            continue

        # ── SCAN mode ──────────────────────────────────────────────────────
        console.print(f"\n  [{GREY}]📱 To find a phone: open Settings → Bluetooth and set it to Discoverable.[/]")
        console.print(f"  [{GREY}]Select one device (#) or multiple (1,3,5 or 1-4 or 'all').[/]\n")

        raw = Prompt.ask(f"[{CYAN}]Scan duration[/] [{GREY}](seconds, default 12)[/]", default="12").strip()
        try:
            duration = float(raw)
        except ValueError:
            duration = 12.0

        console.print()
        devices = await scan_all(duration)

        if not devices:
            console.print(f"\n  [{YELLOW}]No devices found.[/]  [{GREY}]Bluetooth on? Phone discoverable?[/]\n")
            if not Confirm.ask(f"  [{CYAN}]Try again?[/]", default=True):
                break
            print_banner()
            continue

        devices.sort(key=lambda d: (d.mode == "ble", -(d.rssi or -200)))

        console.print()
        show_device_table(devices, set())

        counts = {m: sum(1 for d in devices if d.mode == m) for m in ("classic", "ble", "dual")}
        console.print(
            f"  [{GREY}]Found {len(devices)} — "
            f"CLASSIC {counts['classic']}  BLE {counts['ble']}  DUAL {counts['dual']}[/]\n"
        )

        console.print(
            f"  [{GREY}]Enter device number(s):  [/]"
            f"[{WHITE}]1[/] [{GREY}]or[/] [{WHITE}]1,3[/] [{GREY}]or[/] [{WHITE}]1-4[/] [{GREY}]or[/] [{WHITE}]all[/]\n"
            f"  [{WHITE}]s[/] [{GREY}]= rescan  [/][{WHITE}]q[/] [{GREY}]= quit[/]"
        )

        raw_choice = Prompt.ask(f"\n  [{CYAN}]>[/]").strip().lower()

        if raw_choice == "q":
            break
        if raw_choice == "s":
            print_banner()
            continue

        indices = parse_selection(raw_choice, len(devices))
        if not indices:
            console.print(f"  [{RED}]No valid device numbers found.[/]")
            continue

        selected_devices = [devices[i - 1] for i in indices]

        console.print()
        show_device_table(devices, set(indices))

        if len(selected_devices) == 1:
            await session_single(selected_devices[0])
        else:
            await handle_multi(selected_devices)

        console.print()
        if not Confirm.ask(f"  [{CYAN}]Return to main menu?[/]", default=True):
            break
        print_banner()

    console.print(f"\n  [{CYAN}]Goodbye.[/]\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print(f"\n\n  [{GREY}]Interrupted.[/]\n")
