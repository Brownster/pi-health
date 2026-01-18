#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: tools/import_unraid_xml.sh [-o OUTPUT_DIR] [-f] TEMPLATE.xml

Convert an unRAID Community Apps XML template into a Pi-Health catalog YAML.

Options:
  -o OUTPUT_DIR  Output directory (default: catalog)
  -f             Overwrite if output file exists
EOF
}

if [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

output_dir="catalog"
force="false"

while getopts ":o:fh" opt; do
  case "$opt" in
    o) output_dir="$OPTARG" ;;
    f) force="true" ;;
    h)
      usage
      exit 0
      ;;
    *)
      usage
      exit 1
      ;;
  esac
done

shift $((OPTIND-1))

if [ "$#" -ne 1 ]; then
  usage
  exit 1
fi

xml_path="$1"
if [ ! -f "$xml_path" ]; then
  echo "XML file not found: $xml_path" >&2
  exit 1
fi

python - "$xml_path" "$output_dir" "$force" <<'PY'
import os
import re
import sys
import xml.etree.ElementTree as ET

xml_path = sys.argv[1]
output_dir = sys.argv[2]
force = sys.argv[3].lower() == "true"

tree = ET.parse(xml_path)
root = tree.getroot()

def text(tag):
    node = root.find(tag)
    return (node.text or "").strip() if node is not None else ""

def slugify(value):
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "app"

def keyify(value):
    value = value.strip().upper()
    value = re.sub(r"[^A-Z0-9]+", "_", value)
    return value.strip("_") or "VALUE"

name = text("Name") or "app"
app_id = slugify(name)
image = text("Repository")
network_mode = text("Network") or "bridge"
description = text("Overview") or ""

fields = []
ports = []
volumes = []
environment = []

for cfg in root.findall("Config"):
    cfg_type = (cfg.attrib.get("Type") or "").strip()
    target = (cfg.attrib.get("Target") or "").strip()
    display_name = (cfg.attrib.get("Name") or target or "Value").strip()
    default = (cfg.text or "").strip() or (cfg.attrib.get("Default") or "").strip()
    mode = (cfg.attrib.get("Mode") or "").strip()
    required = (cfg.attrib.get("Required") or "").strip().lower() == "true"

    if cfg_type == "Port" and target:
        field_key = f"PORT_{keyify(target)}"
        fields.append({
            "key": field_key,
            "label": display_name,
            "default": default or target,
            "required": required
        })
        mapping = f"{{{{{field_key}}}}}:{target}"
        if mode:
            mapping = f"{mapping}/{mode}"
        ports.append(mapping)
    elif cfg_type == "Path" and target:
        field_key = f"{keyify(display_name)}_PATH"
        fields.append({
            "key": field_key,
            "label": display_name,
            "default": default,
            "required": required
        })
        volume_mode = mode or "rw"
        volumes.append(f"{{{{{field_key}}}}}:{target}:{volume_mode}")
    elif cfg_type == "Variable" and target:
        field_key = keyify(target)
        fields.append({
            "key": field_key,
            "label": display_name,
            "default": default,
            "required": required
        })
        environment.append(f"{target}={{{{{field_key}}}}}")

output_path = os.path.join(output_dir, f"{app_id}.yaml")
if os.path.exists(output_path) and not force:
    print(f"Refusing to overwrite {output_path} (use -f to force)", file=sys.stderr)
    sys.exit(1)

os.makedirs(output_dir, exist_ok=True)

def emit_line(handle, indent, value):
    handle.write(" " * indent + value + "\n")

with open(output_path, "w", encoding="utf-8") as handle:
    emit_line(handle, 0, f"id: {app_id}")
    emit_line(handle, 0, f"name: {name}")
    emit_line(handle, 0, f"description: {description}")
    emit_line(handle, 0, "requires: []")
    emit_line(handle, 0, "disabled_by_default: false")
    emit_line(handle, 0, "fields:")
    for field in fields:
        emit_line(handle, 2, f"- key: {field['key']}")
        emit_line(handle, 4, f"label: {field['label']}")
        emit_line(handle, 4, f"default: \"{field['default']}\"")
        if not field["required"]:
            emit_line(handle, 4, "required: false")
    emit_line(handle, 0, "service:")
    emit_line(handle, 2, f"image: {image}")
    emit_line(handle, 2, f"container_name: {app_id}")
    emit_line(handle, 2, f"network_mode: {network_mode}")
    if environment:
        emit_line(handle, 2, "environment:")
        for entry in environment:
            emit_line(handle, 4, f"- {entry}")
    if volumes:
        emit_line(handle, 2, "volumes:")
        for entry in volumes:
            emit_line(handle, 4, f"- \"{entry}\"")
    if ports:
        emit_line(handle, 2, "ports:")
        for entry in ports:
            emit_line(handle, 4, f"- \"{entry}\"")
    emit_line(handle, 2, "restart: unless-stopped")

print(f"Wrote {output_path}")
PY
