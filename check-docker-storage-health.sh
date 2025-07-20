#!/bin/bash

# Docker Storage Health Check Script
# This script verifies that pooled storage is accessible before Docker containers start

set -euo pipefail

# Configuration
STORAGE_MOUNT="/mnt/storage"
REQUIRED_DIRS=("Movies" "TVShows" "downloads")
TIMEOUT=60
CHECK_INTERVAL=2

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >&2
}

# Check if MergerFS mount is available
check_mergerfs_mount() {
    if ! mountpoint -q "$STORAGE_MOUNT"; then
        log "ERROR: MergerFS mount $STORAGE_MOUNT is not available"
        return 1
    fi
    
    log "INFO: MergerFS mount $STORAGE_MOUNT is available"
    return 0
}

# Check if required directories exist and are writable
check_required_directories() {
    for dir in "${REQUIRED_DIRS[@]}"; do
        local full_path="$STORAGE_MOUNT/$dir"
        
        if [[ ! -d "$full_path" ]]; then
            log "ERROR: Required directory $full_path does not exist"
            return 1
        fi
        
        if [[ ! -w "$full_path" ]]; then
            log "ERROR: Required directory $full_path is not writable"
            return 1
        fi
        
        log "INFO: Directory $full_path is accessible and writable"
    done
    
    return 0
}

# Check storage space availability
check_storage_space() {
    local available_space
    available_space=$(df "$STORAGE_MOUNT" | awk 'NR==2 {print $4}')
    
    if [[ -z "$available_space" ]] || [[ "$available_space" -eq 0 ]]; then
        log "ERROR: No available space on $STORAGE_MOUNT"
        return 1
    fi
    
    # Convert to GB for logging
    local available_gb=$((available_space / 1024 / 1024))
    log "INFO: Available space on $STORAGE_MOUNT: ${available_gb}GB"
    
    # Warn if less than 1GB available
    if [[ "$available_gb" -lt 1 ]]; then
        log "WARNING: Low disk space on $STORAGE_MOUNT (${available_gb}GB remaining)"
    fi
    
    return 0
}

# Check if SnapRAID is configured and healthy (if available)
check_snapraid_health() {
    if command -v snapraid &> /dev/null && [[ -f /etc/snapraid/snapraid.conf ]]; then
        log "INFO: Checking SnapRAID health..."
        
        # Run snapraid status with timeout
        if timeout 30 snapraid status &> /dev/null; then
            log "INFO: SnapRAID status check passed"
        else
            log "WARNING: SnapRAID status check failed or timed out"
            # Don't fail the health check for SnapRAID issues
        fi
    else
        log "INFO: SnapRAID not configured, skipping health check"
    fi
}

# Test file I/O operations
test_file_operations() {
    local test_file="$STORAGE_MOUNT/.docker-health-test"
    local test_content="Docker storage health test - $(date)"
    
    # Test write operation
    if ! echo "$test_content" > "$test_file" 2>/dev/null; then
        log "ERROR: Cannot write to storage mount $STORAGE_MOUNT"
        return 1
    fi
    
    # Test read operation
    if ! cat "$test_file" &> /dev/null; then
        log "ERROR: Cannot read from storage mount $STORAGE_MOUNT"
        rm -f "$test_file" 2>/dev/null || true
        return 1
    fi
    
    # Test delete operation
    if ! rm "$test_file" 2>/dev/null; then
        log "ERROR: Cannot delete from storage mount $STORAGE_MOUNT"
        return 1
    fi
    
    log "INFO: File I/O operations test passed"
    return 0
}

# Wait for storage to become available
wait_for_storage() {
    local elapsed=0
    
    log "INFO: Waiting for storage to become available (timeout: ${TIMEOUT}s)"
    
    while [[ $elapsed -lt $TIMEOUT ]]; do
        if check_mergerfs_mount; then
            log "INFO: Storage became available after ${elapsed}s"
            return 0
        fi
        
        sleep $CHECK_INTERVAL
        elapsed=$((elapsed + CHECK_INTERVAL))
    done
    
    log "ERROR: Storage did not become available within ${TIMEOUT}s"
    return 1
}

# Main health check function
main() {
    log "INFO: Starting Docker storage health check"
    
    # Wait for storage to be available
    if ! wait_for_storage; then
        log "ERROR: Storage availability check failed"
        exit 1
    fi
    
    # Check required directories
    if ! check_required_directories; then
        log "ERROR: Required directories check failed"
        exit 1
    fi
    
    # Check storage space
    if ! check_storage_space; then
        log "ERROR: Storage space check failed"
        exit 1
    fi
    
    # Test file operations
    if ! test_file_operations; then
        log "ERROR: File operations test failed"
        exit 1
    fi
    
    # Check SnapRAID health (non-critical)
    check_snapraid_health
    
    log "INFO: Docker storage health check completed successfully"
    exit 0
}

# Handle script termination
cleanup() {
    local test_file="$STORAGE_MOUNT/.docker-health-test"
    rm -f "$test_file" 2>/dev/null || true
}

trap cleanup EXIT

# Run main function
main "$@"