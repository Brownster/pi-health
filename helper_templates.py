"""Fixed templates owned by the privileged-helper contract."""

import shlex


def render_startup_files(mount_points, compose_file):
    mounts = ' '.join(shlex.quote(value) for value in mount_points)
    script = f"""#!/usr/bin/env bash
set -eu

MOUNT_POINTS=({mounts})
DOCKER_COMPOSE_FILE={shlex.quote(compose_file)}

if [ "${{#MOUNT_POINTS[@]}}" -gt 0 ]; then
  while true; do
    missing=0
    for mount_point in "${{MOUNT_POINTS[@]}}"; do
      if ! mountpoint -q "$mount_point"; then
        missing=1
      fi
    done
    if [ "$missing" -eq 0 ]; then
      break
    fi
    sleep 5
  done
fi

/usr/bin/docker compose -f "$DOCKER_COMPOSE_FILE" up -d
"""
    service = """[Unit]
Description=Ensure drives are mounted and start Docker containers
Requires=local-fs.target
After=local-fs.target docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check_mount_and_start.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""
    return script, service


def cron_to_oncalendar(cron):
    if not isinstance(cron, str):
        return None
    parts = cron.split()
    if len(parts) != 5:
        return None
    minute, hour, day, month, dow = parts
    fields = ((minute, 0, 59), (hour, 0, 23), (day, 1, 31), (month, 1, 12), (dow, 0, 7))
    for value, minimum, maximum in fields:
        if value == '*':
            continue
        if not value.isdigit() or not minimum <= int(value) <= maximum:
            return None

    dow_names = {'0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu', '5': 'Fri', '6': 'Sat', '7': 'Sun'}
    time_value = f"{int(hour) if hour != '*' else '*'}:{int(minute) if minute != '*' else '*'}:00"
    if dow != '*':
        return f"{dow_names[dow]} *-*-* {time_value}"
    return f"*-{month}-{day} {time_value}"


def render_package_reconcile_schedule(on_calendar, exec_start, *, user, working_dir, pythonpath):
    """systemd (service, timer) for the nightly package-baseline reconcile.

    ``exec_start`` is supplied by the helper so the unit routes the run back through the
    privileged helper over its socket (audited), rather than shelling apt directly from the
    timer. It therefore runs as ``user`` (in the helper's client group) with the app on the
    ``pythonpath`` so ``helper_client`` is importable.
    """
    service = (
        "[Unit]\n"
        "Description=LimeOS nightly package baseline reconcile\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"User={user}\n"
        f"WorkingDirectory={working_dir}\n"
        f"Environment=PYTHONPATH={pythonpath}\n"
        f"ExecStart={exec_start}\n"
        "Nice=19\n"
        "IOSchedulingClass=idle\n"
    )
    timer = (
        "[Unit]\n"
        "Description=LimeOS nightly package baseline reconcile timer\n\n"
        "[Timer]\n"
        f"OnCalendar={on_calendar}\n"
        "RandomizedDelaySec=3600\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service, timer


def render_snapraid_schedule(job_type, on_calendar):
    service = (
        "[Unit]\n"
        f"Description=SnapRAID {job_type}\n"
        "After=local-fs.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/usr/bin/snapraid {job_type}\n"
        "Nice=19\n"
        "IOSchedulingClass=idle\n"
    )
    timer = (
        "[Unit]\n"
        f"Description=SnapRAID {job_type} timer\n\n"
        "[Timer]\n"
        f"OnCalendar={on_calendar}\n"
        "RandomizedDelaySec=1800\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service, timer
