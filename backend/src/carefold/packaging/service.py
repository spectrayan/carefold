# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""OS background service descriptor generators for local-first Carefold runtime (AU-81).

Generates user-level background daemon definitions for:
- macOS `launchd` (`~/Library/LaunchAgents/com.spectrayan.carefold.plist`)
- Linux `systemd --user` (`~/.config/systemd/user/carefold.service`)
- Windows Task Scheduler (`%USERPROFILE%\\.carefold\\carefold-task.xml`)

All descriptors bind strictly to `127.0.0.1` by default (`Mode L` privacy boundary)
and configure automatic crash recovery (`KeepAlive` / `Restart=on-failure`).
"""

from __future__ import annotations

from html import escape as xml_escape
from typing import Dict, List


def _validate_port(port: int) -> int:
    port_num = int(port)
    if port_num < 1 or port_num > 65535:
        raise ValueError(f"Invalid service port: {port}. Must be between 1 and 65535.")
    return port_num


def generate_macos_launchd_plist(
    carefold_bin: str = "/usr/local/bin/carefold",
    working_dir: str = "~/.carefold",
    port: int = 8000,
) -> Dict[str, str]:
    """Generates a macOS `launchd` LaunchAgent plist descriptor bound to `127.0.0.1`."""
    valid_port = _validate_port(port)
    escaped_bin = xml_escape((carefold_bin or "/usr/local/bin/carefold").strip())
    escaped_dir = xml_escape((working_dir or "~/.carefold").strip())

    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spectrayan.carefold</string>
    <key>ProgramArguments</key>
    <array>
        <string>{escaped_bin}</string>
        <string>serve</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>{valid_port}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{escaped_dir}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>CAREFOLD_HOST</key>
        <string>127.0.0.1</string>
        <key>CAREFOLD_PORT</key>
        <string>{valid_port}</string>
    </dict>
</dict>
</plist>
"""
    return {
        "platform": "macos_launchd",
        "filename": "com.spectrayan.carefold.plist",
        "install_path": "~/Library/LaunchAgents/com.spectrayan.carefold.plist",
        "content": content,
        "install_command": "launchctl load -w ~/Library/LaunchAgents/com.spectrayan.carefold.plist",
    }


def generate_linux_systemd_unit(
    carefold_bin: str = "/usr/local/bin/carefold",
    working_dir: str = "%h/.carefold",
    port: int = 8000,
) -> Dict[str, str]:
    """Generates a Linux `systemd --user` unit descriptor bound to `127.0.0.1`."""
    valid_port = _validate_port(port)
    clean_bin = (carefold_bin or "/usr/local/bin/carefold").strip()
    clean_dir = (working_dir or "%h/.carefold").strip()

    content = f"""[Unit]
Description=Carefold Local-First Healthcare AI Runtime
After=network.target

[Service]
Type=simple
WorkingDirectory={clean_dir}
Environment="CAREFOLD_HOST=127.0.0.1"
Environment="CAREFOLD_PORT={valid_port}"
ExecStart={clean_bin} serve --host 127.0.0.1 --port {valid_port}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
    return {
        "platform": "linux_systemd",
        "filename": "carefold.service",
        "install_path": "~/.config/systemd/user/carefold.service",
        "content": content,
        "install_command": "systemctl --user enable --now carefold.service",
    }


def generate_windows_task_xml(
    carefold_bin: str = "C:\\Program Files\\Carefold\\carefold.exe",
    working_dir: str = "%USERPROFILE%\\.carefold",
    port: int = 8000,
) -> Dict[str, str]:
    """Generates a Windows Task Scheduler XML definition bound to `127.0.0.1`."""
    valid_port = _validate_port(port)
    escaped_bin = xml_escape((carefold_bin or "C:\\Program Files\\Carefold\\carefold.exe").strip())
    escaped_dir = xml_escape((working_dir or "%USERPROFILE%\\.carefold").strip())

    content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Carefold Local-First Healthcare AI Runtime</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escaped_bin}</Command>
      <Arguments>serve --host 127.0.0.1 --port {valid_port}</Arguments>
      <WorkingDirectory>{escaped_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""
    return {
        "platform": "windows_task_scheduler",
        "filename": "carefold-task.xml",
        "install_path": "%USERPROFILE%\\.carefold\\carefold-task.xml",
        "content": content,
        "install_command": "schtasks /Create /XML carefold-task.xml /TN CarefoldRuntime",
    }


def list_os_service_descriptors(
    port: int = 8000,
) -> List[Dict[str, str]]:
    """Returns all three OS background service packaging descriptors."""
    valid_port = _validate_port(port)
    return [
        generate_macos_launchd_plist(port=valid_port),
        generate_linux_systemd_unit(port=valid_port),
        generate_windows_task_xml(port=valid_port),
    ]
