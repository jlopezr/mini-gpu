"""Monitor de diagnostico para desconexiones del FTDI y su cadena USB.

Windows expone la topologia y el estado PnP mediante cmdlets de PowerShell. El
monitor toma una instantanea periodica, conserva solo los cambios en JSONL y
escribe mensajes legibles en pantalla. No cambia ninguna configuracion.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


POWERSHELL_SNAPSHOT = r"""
$ErrorActionPreference = 'Stop'
$all = @(Get-PnpDevice -PresentOnly)
$ftdi = @($all | Where-Object {
    $_.InstanceId -match '^FTDIBUS\\' -or
    $_.InstanceId -match '^USB\\VID_0403' -or
    $_.FriendlyName -match 'FTDI|USB Serial'
})
$ids = [System.Collections.Generic.List[string]]::new()
foreach ($trackedId in @(__TRACKED_IDS__)) {
    if ($trackedId -and -not $ids.Contains($trackedId)) { $ids.Add($trackedId) }
}
foreach ($dev in $ftdi) {
    $id = $dev.InstanceId
    while ($id -and -not $ids.Contains($id)) {
        $ids.Add($id)
        $parent = Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_Device_Parent `
            -ErrorAction SilentlyContinue
        $id = if ($parent) { [string]$parent.Data } else { $null }
    }
}
$devices = foreach ($id in $ids) {
    $dev = Get-PnpDevice -InstanceId $id -ErrorAction SilentlyContinue
    $isPresent = [bool]($all | Where-Object { $_.InstanceId -eq $id })
    $base = "HKLM:\SYSTEM\CurrentControlSet\Enum\$id\Device Parameters"
    $params = Get-ItemProperty -LiteralPath $base -ErrorAction SilentlyContinue
    $wdf = Get-ItemProperty -LiteralPath "$base\WDF" -ErrorAction SilentlyContinue
    [ordered]@{
        instance_id = $id
        present = $isPresent
        status = if ($dev) { [string]$dev.Status } else { $null }
        class = if ($dev) { [string]$dev.Class } else { $null }
        name = if ($dev) { [string]$dev.FriendlyName } else { $null }
        parent = [string](Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_Device_Parent `
            -ErrorAction SilentlyContinue).Data
        enhanced_power_management = $params.EnhancedPowerManagementEnabled
        selective_suspend = $params.SelectiveSuspendEnabled
        allow_idle_irp_in_d3 = $params.AllowIdleIrpInD3
        device_selective_suspended = $params.DeviceSelectiveSuspended
        idle_in_working_state = $wdf.IdleInWorkingState
    }
}
[ordered]@{
    ftdi_count = $ftdi.Count
    devices = @($devices)
} | ConvertTo-Json -Depth 5 -Compress
"""


def _powershell() -> str:
    for candidate in ("pwsh", "powershell"):
        found = shutil.which(candidate)
        if found:
            return found
    raise RuntimeError("No encuentro PowerShell (pwsh.exe o powershell.exe).")


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def snapshot(executable: str, tracked_ids: list[str]) -> dict:
    script = POWERSHELL_SNAPSHOT.replace(
        "__TRACKED_IDS__", ",".join(_ps_literal(item) for item in tracked_ids)
    )
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        detail = _decode_output(result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"PowerShell termino con codigo {result.returncode}")
    return json.loads(_decode_output(result.stdout))


def _decode_output(raw: bytes) -> str:
    """Acepta UTF-8 de pwsh y la pagina OEM usada por Windows PowerShell."""
    for encoding in ("utf-8-sig", "cp850", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def append_record(output: Path, record: dict) -> None:
    """Escribe un evento y cierra el archivo antes de continuar."""
    with output.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def signature(data: dict) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def describe(data: dict) -> str:
    devices = data.get("devices", [])
    present = [d for d in devices if d.get("present")]
    com = next((d.get("name") for d in present if d.get("class") == "Ports"), None)
    return f"FTDI={data.get('ftdi_count', 0)}, cadena={len(present)}, puerto={com or '-'}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Registra cambios del FTDI y sus hubs USB para diagnosticar apagados."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(f"usb-power-{datetime.now():%Y%m%d-%H%M%S}.jsonl"),
        help="archivo JSONL de salida (por defecto: usb-power-FECHA-HORA.jsonl)",
    )
    parser.add_argument("--interval", type=float, default=1.0, help="segundos entre muestras")
    parser.add_argument("--duration", type=float, help="duracion maxima en minutos")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.interval < 0.5:
        raise SystemExit("--interval debe ser al menos 0.5 segundos")
    if args.duration is not None and args.duration <= 0:
        raise SystemExit("--duration debe ser positiva")

    executable = _powershell()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.duration * 60 if args.duration else None
    previous = None
    tracked_ids: list[str] = []

    print(f"Registro: {output}")
    print("Deja que la pantalla se apague. Pulsa Ctrl+C despues de reproducir el fallo.")
    try:
        while deadline is None or time.monotonic() < deadline:
            timestamp = now_iso()
            try:
                data = snapshot(executable, tracked_ids)
                for device in data.get("devices", []):
                    instance_id = device.get("instance_id")
                    if instance_id and instance_id not in tracked_ids:
                        tracked_ids.append(instance_id)
                current = signature(data)
                if current != previous:
                    record = {"timestamp": timestamp, "type": "snapshot", **data}
                    append_record(output, record)
                    print(f"[{timestamp}] {describe(data)}")
                    previous = current
            except Exception as exc:  # keep monitoring after transient PnP errors
                record = {"timestamp": timestamp, "type": "error", "message": str(exc)}
                append_record(output, record)
                print(f"[{timestamp}] ERROR: {exc}", file=sys.stderr)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitor detenido; el registro se ha guardado.")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
