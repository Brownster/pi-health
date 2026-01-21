# App Catalog YAML Guide

Pi-Health reads app definitions from YAML files in the `catalog/` directory.
Each file describes metadata, input fields, and a Docker Compose service
template that Pi-Health renders at install time.

## File location

- Place files in `catalog/`
- File name should match `id`, e.g. `navidrome.yaml`

## Minimal template

```yaml
id: navidrome
name: Navidrome
description: Music server
requires: []
disabled_by_default: false
fields:
  - key: TZ
    label: Timezone
    default: "Europe/London"
service:
  image: deluan/navidrome:latest
  container_name: navidrome
  network_mode: bridge
  environment:
    - TZ={{TZ}}
  ports:
    - "{{PORT}}:4533"
  volumes:
    - "{{CONFIG_DIR}}/navidrome:/data"
  restart: unless-stopped
```

## Top-level keys

- `id` (string, required): Unique ID used as file name.
- `name` (string, required): Display name.
- `description` (string): Short description for the UI.
- `requires` (list): Dependencies like `vpn`.
- `disabled_by_default` (bool): Hide from catalog by default.
- `fields` (list): User-provided inputs (see below).
- `service` (object, required): Docker Compose service template.

## Fields

Each field becomes an input in the App Store install dialog.

Supported keys:

- `key` (string, required): Token used in the template, e.g. `PORT`.
- `label` (string, required): UI label.
- `default` (string): Default value.
- `required` (bool, optional): Defaults to true.

Tokens use `{{KEY}}` syntax inside the `service` template.

## Service template

The `service` object should be valid Compose service syntax.
Any string values can use `{{KEY}}` tokens from `fields`.

Common sections:

- `image`
- `container_name`
- `network_mode`
- `environment` (list of `KEY=VALUE`)
- `volumes` (list of `host:container[:mode]`)
- `ports` (list of `host:container`)
- `restart`

## Adding to the App Store

1. Create a new YAML file in `catalog/`.
2. Refresh the App Store page or click **Refresh**.

## Import from unRAID XML

You can convert unRAID Community Apps XML templates into Pi-Health YAML using:

```bash
tools/import_unraid_xml.sh /path/to/template.xml
```

Output is written to `catalog/<id>.yaml`. Use `-o` to change the output
directory or `-f` to overwrite.

Notes:
- Only `Port`, `Path`, and `Variable` Config types are mapped.
- Some unRAID-specific fields are ignored.
