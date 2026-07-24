# Guided Media-Stack Onboarding Delivery Plan

Status: Active
Owner: LimeOS maintainers
Created: 2026-07-20
Target platforms: Debian Bookworm on Raspberry Pi arm64 and x86-64

## Purpose

This plan defines the supported journey from a fresh Debian Bookworm host to a working,
reboot-safe media stack. The operator starts with SSH access and one or more USB drives. LimeOS
must guide them through installation, storage assignment, stack deployment, configuration backup,
and validation without requiring manual Compose edits or permission repairs.

This plan extends `Docs/MEDIA_STACK_SEED_DEPLOYMENT_PLAN.md`. Where the older plan assumes
`/home/pi`, UID/GID 1000, mandatory VPN use, immediate API availability, or separate configuration
sources, this plan supplies the requirements for fresh-host onboarding. Reconcile those conflicts
before implementation.

## Outcomes

An operator who accepts the recommended defaults can:

1. Install LimeOS on a minimal Bookworm host through one documented command path.
2. Assign attached storage by role without relying on `/dev/sdX` names.
3. Deploy a correctly wired media stack with stable container paths.
4. Use direct play without configuring transcoding.
5. Enable detected hardware transcoding as an option.
6. Back up LimeOS, stack, and application configuration to a USB stick or another mounted target.
7. Reboot without containers writing to unmounted directories on the OS filesystem.
8. See whether the stack is merely running or fully operational.

## Supported deployment envelope

The onboarding flow supports:

- Raspberry Pi arm64 and x86-64 hosts running Debian Bookworm.
- One USB data drive and an optional USB stick for configuration backups.
- Separate media and download drives.
- One to three 5-bay USB DAS enclosures.
- Direct play by default.
- Optional detected hardware transcoding.
- VPN and non-VPN deployments.
- A storage model that can later grow from one disk to a multi-disk pool.

The first delivery does not need to implement live pool growth. It must avoid assumptions that
would prevent later growth.

## Product rules

### Keep container paths fixed

Managed applications always use these paths:

| Purpose | Container path |
| --- | --- |
| Media | `/data/media` |
| Downloads | `/data/downloads` |
| Application configuration | `/config` |

The standard content tree is:

```text
/data/media/
├── movies/
├── tv/
└── music/

/data/downloads/
├── complete/
└── incomplete/
```

Host paths may change by storage profile. Catalog templates, application seed data, and application
databases must use the fixed container paths.

### Assign roles, not guessed paths

LimeOS assigns each disk or partition one of these roles:

- Data
- Downloads
- Parity
- Configuration backup
- Unassigned

Persist filesystem UUIDs and hardware serials. Treat kernel names such as `/dev/sdb` as transient
observations.

### Use one storage configuration

Create one versioned storage configuration consumed by:

- Disk and mount management
- Media quickstart
- Stack generation
- Application seeding
- Backup jobs
- MergerFS and SnapRAID configuration
- Systemd mount dependencies
- Health and status reporting

Retire the split between media-path and media-layout state after a compatibility migration.

### Preserve existing installations explicitly

Compatibility follows these rules:

1. A valid `storage-contract.json` is authoritative for host paths and the media UID/GID.
2. When the contract is absent, existing `media_paths.json`, `media_layout.json`, and legacy
   defaults continue to behave exactly as before.
3. An invalid or unreadable contract fails closed. Consumers must not silently fall back to a
   legacy file and create split-brain storage state.
4. Legacy path and layout endpoints may return contract-derived values, but they must reject
   writes with a conflict once guided storage owns the configuration.
5. Existing `/home/pi` paths remain valid for legacy installations. They are not valid
   fresh-install defaults.
6. LimeOS never synthesizes a storage contract from legacy path files automatically. Those files
   do not contain enough evidence to infer filesystem UUIDs, disk roles, or safe mount ownership.
7. A future migration flow must discover the attached filesystems, match the proposed paths,
   display the resulting role assignments, and require explicit confirmation before saving the
   contract.
8. Removing or disabling guided storage is not a rollback mechanism. A supported rollback must
   restore a reviewed legacy configuration explicitly.

### Protect the OS filesystem

LimeOS must verify every required mount before it creates content directories, starts containers,
or runs backups. An absent drive must stop the affected workload. LimeOS must never replace a
missing mount with an ordinary directory on the boot filesystem.

### Expose complexity progressively

The normal flow offers recommended profiles and role assignments. An Advanced section permits
custom host paths and Compose overrides. Custom host paths never change the managed container path
contract.

## Storage profiles

### Profile A: One data drive

Mount the data filesystem at `/mnt/storage`:

```text
/mnt/storage/
├── media/
│   ├── movies/
│   ├── tv/
│   └── music/
└── downloads/
    ├── complete/
    └── incomplete/
```

Mount the filesystem once inside media containers so imports can use hardlinks and atomic moves.
LimeOS may expose `/mnt/storage/downloads` at `/mnt/downloads` as a host-facing bind mount, but the
container mapping must preserve the single-filesystem layout.

### Profile B: Separate media and download drives

Use the stable host endpoints:

```text
/mnt/storage
/mnt/downloads
```

Map them to `/data/media` and `/data/downloads`. Explain that cross-filesystem imports copy and
delete data instead of using hardlinks.

### Profile C: Protected pool

Use individual disk mountpoints and a stable pool endpoint:

```text
/mnt/disks/data-01
/mnt/disks/data-02
/mnt/disks/data-N
/mnt/parity/parity-01
/mnt/storage
/mnt/downloads
```

MergerFS presents the media pool at `/mnt/storage`. Downloads may use a separate disk or a
pool-backed directory. Application paths remain unchanged.

### Configuration backup

Use `/mnt/backup/limeos` as the default destination. A configuration backup includes:

- LimeOS configuration and storage metadata
- Stack definitions and managed profiles
- Application configuration
- Recovery metadata

The UI and documentation must state that the USB stick does not back up the media library and that
SnapRAID parity is not a backup.

## Delivery plan

### OB-000: Freeze the onboarding contract

Status: In progress

Deliverables:

- [x] Define the versioned storage configuration schema.
- [x] Define fixed container paths and standard library names.
- [x] Define disk roles and valid role combinations.
- [x] Define the application configuration root.
- [ ] Define the dashboard service account and media UID/GID model.
- [ ] Define supported filesystems and formatting policy.
- [ ] Define `running`, `integrated`, and `operational` completion states.
- [x] Document compatibility rules for existing installations.

Recommended ownership model:

- Run the dashboard as a dedicated unprivileged service account.
- Keep privileged disk operations behind the helper boundary.
- Store a separate media UID/GID, initially derived from the interactive SSH user.
- Store managed application configuration outside `/home/pi`, for example under
  `/var/lib/limeos/apps`.

Exit gate:

- No fresh-install default contains `/home/pi` or assumes UID/GID 1000.
- Every storage consumer can derive its paths from the proposed configuration.
- Existing installations have a documented migration or compatibility path.

### OB-100: Build a reliable bootstrap

Status: In progress
Depends on: OB-000

Deliverables:

- [x] Establish one canonical README installation path.
- [x] Check the Debian release and architecture.
- [x] Detect the interactive user, home directory, UID, and GID.
- [x] Install Git or document a bootstrap command that does not require it.
- [ ] Install Docker, Compose, and advertised filesystem packages.
- [ ] Create and correctly own runtime, stack, and application directories.
- [ ] Prompt securely for the dashboard administrator credentials.
- [x] Start the privileged helper before the dashboard.
- [x] Verify Docker, Compose, systemd units, helper connectivity, and port 8002.
- [ ] Print the dashboard URL and recovery commands.
- [ ] Make every installer step safe to rerun.

Exit gate:

> A fresh minimal Bookworm arm64 or amd64 host reaches a working login page by following the README,
> without manual file edits, permission changes, or service recovery.

### OB-200: Add storage discovery and role assignment

Status: Not started
Depends on: OB-000, OB-100

Deliverables:

- [ ] Discover disks, partitions, filesystems, labels, UUIDs, models, serials, and capacities.
- [ ] Exclude the OS filesystem and its parent disk.
- [ ] Group disks by USB enclosure when the system exposes enough information.
- [ ] Recommend a storage profile from the available devices.
- [ ] Let the operator assign or change disk roles.
- [ ] Detect duplicate mountpoints, UUIDs, labels, and role conflicts.
- [ ] Preview all mount, directory, ownership, and configuration changes.
- [ ] Persist mounts using stable identifiers.
- [ ] Mount and validate every selected filesystem.
- [ ] Create the standard directory tree only after mount validation.
- [ ] Validate ownership, permissions, and available space.
- [ ] Add actionable warnings for USB power, hubs, and unstable device identity.

Formatting policy:

- Never format a disk automatically.
- Mount existing supported filesystems without destructive changes.
- Offer ext4 formatting for blank disks only after a separate confirmation that shows the exact
  model, serial, capacity, and affected partition.
- Confirm each destructive target individually.

Exit gate:

- An absent mount cannot redirect media, download, parity, or backup writes to the OS disk.
- Reordering USB devices across reboot does not change assignments.
- The model represents one, two, five, and fifteen-disk systems.
- Two visually identical disks remain distinguishable by serial and role.

### OB-300: Implement the first-run media wizard

Status: Not started
Depends on: OB-200

Wizard sequence:

1. Select the storage profile.
2. Confirm disk roles and mount health.
3. Confirm timezone and media UID/GID.
4. Select libraries.
5. Select one downloader.
6. Choose VPN or direct networking.
7. Choose direct play or detected hardware acceleration.
8. Supply required credentials.
9. Review the deployment plan.
10. Install, validate, and display next steps.

Defaults:

- [ ] Direct play; expose no GPU or video devices.
- [ ] One downloader instead of Transmission and SABnzbd together.
- [ ] VPN remains optional.
- [ ] Use `movies`, `tv`, and `music` as lowercase library names.
- [ ] Recommend LAN or Tailscale access rather than direct WAN exposure.

Optional hardware acceleration:

- [ ] Offer Intel or AMD acceleration only when `/dev/dri` and required group access exist.
- [ ] Offer Raspberry Pi acceleration only when compatible video devices exist.
- [ ] Place Nvidia support behind an advanced option and validate its runtime.
- [ ] Keep hardware acceleration out of the critical path.

Exit gate:

- Accepting the defaults produces a valid deployment plan without exposing implementation paths.
- Unsupported hardware choices do not appear.
- The wizard can resume after interruption without repeating completed destructive operations.

### OB-400: Make stack deployment deterministic

Status: Not started
Depends on: OB-300

Deployment state machine:

```text
Preflight
  -> Generate
  -> Validate Compose
  -> Start infrastructure
  -> Wait for readiness
  -> Configure downloader
  -> Configure Sonarr, Radarr, and optional applications
  -> Configure Prowlarr
  -> Configure Jellyfin
  -> Verify integrations
  -> Report completion
```

Deliverables:

- [ ] Validate mounts, ports, credentials, image architecture, and free space before deployment.
- [ ] Validate VPN credentials before starting Gluetun.
- [ ] Support a complete non-VPN path.
- [ ] Poll application readiness with bounded timeouts and actionable errors.
- [ ] Use Prowlarr's `/api/v1` endpoints.
- [ ] Generate downloader payloads from the target application's API schema.
- [ ] Complete or explicitly defer Jellyfin administrator setup.
- [ ] Make each seed operation idempotent.
- [ ] Persist step status and offer Resume after failure.
- [ ] Report each application's result independently.
- [ ] Preserve logs without exposing passwords, API keys, or VPN credentials.

Completion states:

| State | Meaning |
| --- | --- |
| Running | Containers have started. |
| Responding | Application health endpoints answer. |
| Integrated | Managed applications can communicate with each other. |
| Operational | Required providers work and an end-to-end workflow passes. |

Exit gate:

- A second run makes no duplicate root folders, clients, applications, or libraries.
- Missing provider configuration produces a clear incomplete state rather than false success.
- A failed application does not hide successful work or prevent a safe resume.

### OB-500: Enforce boot, backup, and network safety

Status: Not started
Depends on: OB-200, OB-400

Boot deliverables:

- [ ] Add mount dependencies for every managed stack.
- [ ] Start containers only after their required mountpoints pass validation.
- [ ] Keep affected stacks stopped when a mount is absent.
- [ ] Surface missing mounts prominently in the dashboard.
- [ ] Verify storage and stack health after reboot.

Backup deliverables:

- [ ] Configure a scheduled backup to a verified backup-role filesystem.
- [ ] Stop the job when `/mnt/backup` is not mounted.
- [ ] Back up LimeOS state, stack definitions, profiles, and application configurations.
- [ ] Retain a bounded history.
- [ ] Provide a restore preview and documented recovery procedure.
- [ ] Permit an explicit backup opt-out.

Network deliverables:

- [ ] Show every published port and bound interface.
- [ ] Recommend trusted LAN or Tailscale access.
- [ ] Warn against direct WAN port forwarding.
- [ ] Explain that Docker-published ports may not follow host firewall expectations.

Exit gate:

- Rebooting with all drives present restores the stack without intervention.
- Rebooting with a required drive absent leaves the affected stack stopped and the OS disk clean.
- Backup status distinguishes success, skipped because unmounted, and failure.

### OB-600: Consolidate documentation

Status: Not started
Depends on: OB-100 through OB-500

Deliverables:

- [ ] Rewrite the README around the canonical onboarding path.
- [ ] Update or retire stale Docker, port 80, Setup, Plugins, and Tailscale instructions.
- [ ] Remove or label legacy Compose examples that conflict with managed paths.
- [ ] Document the one-drive profile.
- [ ] Document separate media and download drives.
- [ ] Document a protected DAS pool.
- [ ] Explain configuration backup, parity, and media backup separately.
- [ ] Document direct play and optional hardware acceleration.
- [ ] Provide VPN and non-VPN examples.
- [ ] Publish service URLs, recovery commands, and a troubleshooting checklist.

Exit gate:

- Every documented control and route exists in the current product.
- A clean-host test follows the published instructions verbatim.
- The README contains no conflicting installation path.

### OB-700: Validate and release

Status: Not started
Depends on: OB-600

Required test matrix:

| Dimension | Coverage |
| --- | --- |
| Architecture | amd64 and Raspberry Pi arm64 |
| Storage profile | One drive, separate downloads, protected pool |
| Scale | 1, 2, 5, and simulated 15 disks |
| Filesystem | ext4 baseline plus every additionally advertised filesystem |
| VPN | Disabled, configured, and missing credentials |
| Playback | Direct play and optional detected acceleration |
| Lifecycle | Clean install, installer rerun, reboot, and deployment resume |
| Failure | Missing disk, full disk, API timeout, and network failure |
| Safety | OS disk exclusion, unmounted paths, and reordered device names |
| Integration | Real downloader, Sonarr, Radarr, Prowlarr, and Jellyfin APIs |

Release evidence:

- [ ] Complete one clean-host run on a real Raspberry Pi.
- [ ] Complete one clean-host run on a real x86-64 host.
- [ ] Test at least one physical multi-bay USB enclosure.
- [ ] Exercise the fifteen-disk model with loop devices or equivalent fixtures.
- [ ] Complete an end-to-end download/import/library test.
- [ ] Complete a reboot test with all drives present.
- [ ] Complete a reboot test with a required drive absent.
- [ ] Complete a configuration backup and restore drill.
- [ ] Record commands, results, logs, and known limitations in a release sign-off document.

Exit gate:

> The documented default journey passes on real arm64 and amd64 hardware, survives reboot, protects
> the OS filesystem when storage is missing, and reports an honest operational state.

## Dependency order

```text
OB-000 Contract
  -> OB-100 Bootstrap
  -> OB-200 Storage
  -> OB-300 Wizard
  -> OB-400 Deployment
  -> OB-500 Boot, backup, and network safety
  -> OB-600 Documentation
  -> OB-700 Validation and release
```

Work within a milestone may proceed in parallel after its contract and fixtures exist. Do not build
the first-run UI before storage and deployment services expose stable, tested contracts.

## Definition of done

The onboarding epic is complete when:

- [ ] A fresh Bookworm user follows one README path from SSH to a working login.
- [ ] The installation requires no manual file editing or ownership repair.
- [ ] One data drive and one configuration-backup stick work through the default profile.
- [ ] Larger DAS layouts use the same application configuration.
- [ ] Direct play is the default and transcoding is optional.
- [ ] Missing mounts cannot redirect writes to the boot disk.
- [ ] The complete installation survives reboot.
- [ ] Installer and wizard operations are safe to rerun.
- [ ] Deployment resumes safely after partial failure.
- [ ] Configuration backups run only against a verified mount.
- [ ] The dashboard reports running, responding, integrated, and operational states accurately.
- [ ] Published instructions pass on real arm64 and amd64 hosts.

## Deferred work

The following work remains outside this delivery:

- Adding disks to a live pool
- Removing or replacing failed pool disks
- Full media-library backup
- Migration of arbitrary third-party Compose stacks
- Automatic creation of external indexer accounts
- Public internet exposure
- Support for every VPN provider
- Support for every hardware transcoding platform

The storage schema and fixed container path contract must leave room for these features without
requiring application reconfiguration.

## Tracking summary

| ID | Milestone | Status | Depends on |
| --- | --- | --- | --- |
| OB-000 | Onboarding contract | In progress | None |
| OB-100 | Reliable bootstrap | In progress | OB-000 |
| OB-200 | Storage discovery and roles | Not started | OB-000, OB-100 |
| OB-300 | First-run media wizard | Not started | OB-200 |
| OB-400 | Deterministic deployment | Not started | OB-300 |
| OB-500 | Boot, backup, and network safety | Not started | OB-200, OB-400 |
| OB-600 | Documentation | Not started | OB-100 through OB-500 |
| OB-700 | Validation and release | Not started | OB-600 |
