# Test Coverage Gap Analysis Report

**Generated:** January 2025
**Overall Coverage:** 71%
**Tests:** 442 passed, 3 skipped

---

## Executive Summary

The Pi-Health project has good test coverage overall (71%), but several key modules have significant gaps that need attention. This report identifies the gaps and provides specific guidance for writing tests.

---

## Priority 1: Critical Gaps (Coverage < 40%)

These files are core to the application and urgently need better test coverage.

### 1. `pihealth_helper.py` - 23% Coverage

**What it does:** The privileged helper that runs as root to execute system commands (mount, unmount, systemctl, etc.)

**Why it's hard to test:** Many functions interact directly with the system (mounting filesystems, managing systemd services, running privileged commands).

**Missing coverage for these functions:**
| Function | Lines | Description |
|----------|-------|-------------|
| `cmd_mount` | 83-118 | Mount filesystems |
| `cmd_umount` | 122-141 | Unmount filesystems |
| `cmd_fstab_add` | 203-274 | Add entries to /etc/fstab |
| `cmd_fstab_remove` | 279-326 | Remove entries from /etc/fstab |
| `cmd_smb_share_*` | 336-433 | Samba share management |
| `cmd_systemctl` | 654-664 | Manage systemd services |
| `cmd_tailscale_*` | 705-774 | Tailscale install/status/logout |
| `cmd_network_info` | 779-859 | Host network information |
| `cmd_snapraid` | 944-1080 | SnapRAID operations |
| `cmd_mergerfs_*` | 1085-1195 | MergerFS mount/unmount |
| `cmd_sshfs_*` | 1414-1593 | SSHFS mount management |
| `cmd_rclone_*` | 1686-1917 | Rclone mount management |
| `cmd_backup_*` | 1942-2024 | Backup create/restore |

**How to test:**
```python
# Example: Testing cmd_network_info with mocked subprocess
def test_cmd_network_info(mocker):
    # Mock the run_command function
    mocker.patch('pihealth_helper.run_command', side_effect=[
        # ip -j addr output
        {'returncode': 0, 'stdout': json.dumps([{
            'ifname': 'eth0',
            'operstate': 'UP',
            'address': '00:11:22:33:44:55',
            'mtu': 1500,
            'addr_info': [{'family': 'inet', 'local': '192.168.1.100', 'prefixlen': 24}]
        }])},
        # ip -j route show default
        {'returncode': 0, 'stdout': json.dumps([{'gateway': '192.168.1.1', 'dev': 'eth0'}])},
        # curl for public IP
        {'returncode': 0, 'stdout': '1.2.3.4'}
    ])

    # Mock reading /etc/resolv.conf
    mocker.patch('builtins.open', mocker.mock_open(read_data='nameserver 8.8.8.8\n'))

    result = cmd_network_info({})

    assert result['success'] is True
    assert result['hostname'] is not None
    assert len(result['interfaces']) > 0
```

**Test file to create:** `tests/test_pihealth_helper_extended.py`

---

### 2. `storage_plugins/__init__.py` - 26% Coverage

**What it does:** Flask blueprint that exposes REST API endpoints for all storage plugins.

**Missing coverage for these endpoints:**
| Endpoint | Method | Lines | Description |
|----------|--------|-------|-------------|
| `/api/storage/plugins` | GET | 16-22 | List all plugins |
| `/api/storage/plugins/<id>` | GET | 28-41 | Get plugin details |
| `/api/storage/plugins/<id>/config` | GET/POST | 47-81 | Get/set plugin config |
| `/api/storage/plugins/<id>/command/<cmd>` | POST | 87-126 | Run plugin command |
| `/api/storage/mounts/<plugin>` | GET | 132-141 | List mounts for plugin |
| `/api/storage/mounts/<plugin>` | POST | 150-172 | Add new mount |
| `/api/storage/mounts/<plugin>/<id>` | PUT/DELETE | 178-230 | Update/delete mount |
| `/api/storage/mounts/<plugin>/<id>/mount` | POST | 244-253 | Mount a configured mount |
| `/api/storage/mounts/<plugin>/<id>/unmount` | POST | 260-271 | Unmount |

**How to test:**
```python
# tests/test_storage_api.py
import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def auth_client(client):
    with client.session_transaction() as sess:
        sess['authenticated'] = True
    return client

def test_list_plugins(auth_client, mocker):
    # Mock the registry
    mocker.patch('storage_plugins.get_registry', return_value=MockRegistry())

    response = auth_client.get('/api/storage/plugins')
    assert response.status_code == 200
    data = response.get_json()
    assert 'plugins' in data

def test_get_plugin_config(auth_client, mocker):
    mock_plugin = mocker.MagicMock()
    mock_plugin.get_config.return_value = {'enabled': True}
    mock_plugin.get_schema.return_value = {'type': 'object'}

    mock_registry = mocker.MagicMock()
    mock_registry.get.return_value = mock_plugin
    mocker.patch('storage_plugins.get_registry', return_value=mock_registry)

    response = auth_client.get('/api/storage/plugins/snapraid/config')
    assert response.status_code == 200
```

**Test file to create:** `tests/test_storage_api.py`

---

### 3. `plugin_manager.py` - 36% Coverage

**What it does:** Manages plugin enable/disable state and external plugin installation.

**Missing coverage:**
| Function | Lines | Description |
|----------|-------|-------------|
| `toggle_plugin` | 109-120 | Enable/disable a plugin |
| `get_plugin_state` | 124-163 | Get plugin enabled state |
| `install_plugin` | 167-234 | Install external plugin from URL |
| `remove_plugin` | 238-253 | Remove installed plugin |
| `_download_plugin` | 265-292 | Download plugin from GitHub |

**How to test:**
```python
# tests/test_plugin_manager.py
def test_toggle_plugin(tmp_path, mocker):
    mocker.patch('plugin_manager.PLUGINS_STATE_FILE', str(tmp_path / 'plugins.json'))

    from plugin_manager import toggle_plugin, get_plugin_state

    # Toggle on
    result = toggle_plugin('snapraid', True)
    assert result['success'] is True

    state = get_plugin_state('snapraid')
    assert state['enabled'] is True

    # Toggle off
    result = toggle_plugin('snapraid', False)
    assert result['success'] is True

def test_install_plugin_invalid_url():
    from plugin_manager import install_plugin

    result = install_plugin('not-a-url')
    assert result['success'] is False
    assert 'error' in result
```

**Test file to create:** `tests/test_plugin_manager.py` (expand existing)

---

### 4. `setup_manager.py` - 39% Coverage

**What it does:** Handles initial setup tasks (Tailscale, VPN configuration).

**Missing coverage:**
| Endpoint | Lines | Description |
|----------|-------|-------------|
| `/api/setup/tailscale` | 25-42 | Install and configure Tailscale |
| `/api/tailscale/status` | 49-56 | Get Tailscale status |
| `/api/tailscale/logout` | 63-72 | Logout from Tailscale |
| `/api/network/info` | 79-86 | Get host network info |
| `/api/setup/vpn` | 93-130 | Configure VPN |

**How to test:**
```python
# tests/test_setup_manager.py (expand existing)
def test_tailscale_status(auth_client, mocker):
    mocker.patch('setup_manager.helper_available', return_value=True)
    mocker.patch('setup_manager.helper_call', return_value={
        'success': True,
        'installed': True,
        'running': True,
        'tailscale_ips': ['100.100.100.1'],
        'hostname': 'pi-health',
        'online': True
    })

    response = auth_client.get('/api/tailscale/status')
    assert response.status_code == 200
    data = response.get_json()
    assert data['installed'] is True

def test_network_info(auth_client, mocker):
    mocker.patch('setup_manager.helper_available', return_value=True)
    mocker.patch('setup_manager.helper_call', return_value={
        'success': True,
        'hostname': 'pi-health',
        'interfaces': [{'name': 'eth0', 'state': 'UP'}]
    })

    response = auth_client.get('/api/network/info')
    assert response.status_code == 200
```

---

## Priority 2: Medium Gaps (Coverage 40-60%)

### 5. `storage_plugins/snapraid_plugin.py` - 43% Coverage

**Missing coverage:**
- `run_command()` generator for sync/scrub/status (lines 395-463)
- `_parse_status_output()` (lines 514-601)
- `_parse_diff_output()` (lines 604-639)
- Actual sync/scrub operations

**How to test:**
```python
def test_snapraid_sync_command(mocker, snapraid_plugin):
    # Mock helper_call to simulate streaming output
    mocker.patch.object(snapraid_plugin, '_run_snapraid', return_value=iter([
        'Loading state...',
        'Syncing...',
        '100% completed'
    ]))

    output = list(snapraid_plugin.run_command('sync'))
    assert any('completed' in line for line in output)
```

---

### 6. `storage_plugins/mergerfs_plugin.py` - 44% Coverage

**Missing coverage:**
- `mount()` and `unmount()` operations
- `apply_config()` to create pool
- Branch management (add/remove branches)
- Policy configuration

---

### 7. `stack_manager.py` - 56% Coverage

**Missing coverage:**
- Stack creation with docker-compose
- Stack start/stop/restart operations
- Log streaming
- Environment variable handling

---

### 8. `storage_plugins/remote_base.py` - 56% Coverage

**Missing coverage:**
- Abstract method implementations
- Mount/unmount operations
- Status checking

---

## Priority 3: Lower Priority (Coverage 60-80%)

| File | Coverage | Key Missing Areas |
|------|----------|-------------------|
| `disk_manager.py` | 66% | Startup service generation, fstab management |
| `storage_plugins/rclone_plugin.py` | 66% | Mount/unmount operations |
| `storage_plugins/sshfs_plugin.py` | 65% | Mount/unmount, credential handling |
| `storage_plugins/registry.py` | 70% | Plugin discovery, external plugin loading |
| `app.py` | 71% | Various API endpoints |
| `backup_scheduler.py` | 78% | Actual backup execution |
| `update_scheduler.py` | 80% | Update checking logic |

---

## Test Writing Guidelines for Junior Developers

### 1. Setting Up Test Files

```python
# Always start with these imports
import pytest
import json
from unittest.mock import MagicMock, patch, mock_open

# For Flask app tests
from app import app

# Create fixtures for common setup
@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def authenticated_client(client):
    with client.session_transaction() as sess:
        sess['authenticated'] = True
        sess['username'] = 'testuser'
    return client
```

### 2. Mocking External Dependencies

```python
# Mock helper_call for privileged operations
def test_with_helper(mocker):
    mocker.patch('module.helper_call', return_value={'success': True})

# Mock file operations
def test_file_read(mocker):
    mocker.patch('builtins.open', mock_open(read_data='file content'))

# Mock subprocess
def test_subprocess(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = 'output'
```

### 3. Testing API Endpoints

```python
def test_api_endpoint(authenticated_client):
    # GET request
    response = authenticated_client.get('/api/endpoint')
    assert response.status_code == 200

    # POST request with JSON
    response = authenticated_client.post('/api/endpoint',
        data=json.dumps({'key': 'value'}),
        content_type='application/json'
    )
    assert response.status_code == 200

    # Check response data
    data = response.get_json()
    assert 'expected_key' in data
```

### 4. Testing Error Cases

```python
def test_error_handling(authenticated_client, mocker):
    # Test when helper is unavailable
    mocker.patch('module.helper_available', return_value=False)
    response = authenticated_client.get('/api/endpoint')
    assert response.status_code == 503

    # Test with invalid input
    response = authenticated_client.post('/api/endpoint',
        data=json.dumps({'invalid': 'data'}),
        content_type='application/json'
    )
    assert response.status_code == 400
```

### 5. Testing with Temporary Files

```python
def test_with_temp_files(tmp_path):
    # Create a temp config file
    config_file = tmp_path / "config.json"
    config_file.write_text('{"key": "value"}')

    # Use it in your test
    result = load_config(str(config_file))
    assert result['key'] == 'value'
```

---

## Recommended Test Creation Order

1. **Week 1:** `tests/test_setup_manager_extended.py`
   - Network info endpoint
   - Tailscale status endpoint
   - VPN setup endpoint

2. **Week 2:** `tests/test_storage_api.py`
   - Plugin listing
   - Plugin configuration
   - Mount operations

3. **Week 3:** `tests/test_plugin_manager_extended.py`
   - Plugin toggle
   - Plugin installation
   - Plugin removal

4. **Week 4:** `tests/test_pihealth_helper_extended.py`
   - Network info command
   - Tailscale commands
   - Mount/unmount commands

---

## Running Tests

```bash
# Run all tests
python -m pytest

# Run with coverage
python -m pytest --cov=. --cov-report=term-missing

# Run specific test file
python -m pytest tests/test_setup_manager.py -v

# Run tests matching a pattern
python -m pytest -k "test_tailscale" -v

# Run with verbose output
python -m pytest -v --tb=short
```

---

## Coverage Goals

| Timeframe | Target Coverage |
|-----------|-----------------|
| Current | 71% |
| 1 month | 75% |
| 2 months | 80% |
| 3 months | 85% |

Focus on the Priority 1 files first to get the biggest coverage improvements.
