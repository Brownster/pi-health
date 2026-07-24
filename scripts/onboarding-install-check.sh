#!/usr/bin/env bash
#
# Verify that a LimeOS installation is ready before setup reports success.

set -Eeuo pipefail

readonly SCRIPT_VERSION="0.1.0"
readonly SCRIPT_PATH="${BASH_SOURCE[0]}"
readonly SCRIPT_NAME="${SCRIPT_PATH##*/}"

readonly SYSTEMCTL_BIN="${LIMEOS_SYSTEMCTL_BIN:-systemctl}"
readonly DOCKER_BIN="${LIMEOS_DOCKER_BIN:-docker}"
readonly CURL_BIN="${LIMEOS_CURL_BIN:-curl}"
readonly SOCKET_TEST_BIN="${LIMEOS_SOCKET_TEST_BIN:-test}"
readonly HELPER_SOCKET="${LIMEOS_HELPER_SOCKET:-/run/pihealth/helper.sock}"
readonly HEALTH_URL="${LIMEOS_HEALTH_URL:-http://127.0.0.1:8002/api/health}"
readonly READY_ATTEMPTS="${LIMEOS_READY_ATTEMPTS:-30}"
readonly READY_DELAY_SECONDS="${LIMEOS_READY_DELAY_SECONDS:-1}"

SKIP_DOCKER=0
FAILURES=0

fct_usage() {
	printf '%s\n' \
		"${SCRIPT_NAME} v${SCRIPT_VERSION}" \
		"Verify a completed LimeOS installation." \
		"" \
		"Usage:" \
		"  ${SCRIPT_NAME} [--help] [--version] [--skip-docker]" \
		"" \
		"Exit codes:" \
		"  0  Installation is ready" \
		"  2  One or more installation checks failed"
}

fct_pass() {
	printf '[PASS] %s: %s\n' "${1}" "${2}"
}

fct_warn() {
	printf '[WARN] %s: %s\n' "${1}" "${2}"
}

fct_block() {
	printf '[BLOCK] %s: %s\n' "${1}" "${2}" >&2
	FAILURES=$((FAILURES + 1))
}

fct_parse_arguments() {
	while [[ $# -gt 0 ]]; do
		case "${1}" in
		-h | --help)
			fct_usage
			exit 0
			;;
		-V | --version)
			printf '%s v%s\n' "${SCRIPT_NAME}" "${SCRIPT_VERSION}"
			exit 0
			;;
		--skip-docker)
			SKIP_DOCKER=1
			shift
			;;
		*)
			printf 'Unknown option: %s\n' "${1}" >&2
			fct_usage >&2
			exit 64
			;;
		esac
	done
}

fct_validate_settings() {
	if [[ ! "${READY_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]]; then
		printf 'LIMEOS_READY_ATTEMPTS must be a positive integer.\n' >&2
		exit 64
	fi
	if [[ ! "${READY_DELAY_SECONDS}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
		printf 'LIMEOS_READY_DELAY_SECONDS must be a non-negative number.\n' >&2
		exit 64
	fi
}

fct_check_docker() {
	if [[ "${SKIP_DOCKER}" -eq 1 ]]; then
		fct_warn "docker" \
			"Verification skipped explicitly; media stacks will be unavailable"
		return
	fi

	if ! command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
		fct_block "docker" "Docker is not installed"
		return
	fi
	if ! "${DOCKER_BIN}" info >/dev/null 2>&1; then
		fct_block "docker" "Docker daemon is not responding"
		return
	fi
	if ! "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
		fct_block "docker-compose" "Docker Compose plugin is unavailable"
		return
	fi
	fct_pass "docker" "Docker daemon and Compose plugin are available"
}

fct_check_unit() {
	local unit="${1}"

	if ! "${SYSTEMCTL_BIN}" is-enabled --quiet "${unit}"; then
		fct_block "${unit}" "Unit is not enabled"
		return
	fi
	if ! "${SYSTEMCTL_BIN}" is-active --quiet "${unit}"; then
		fct_block "${unit}" "Unit is not active"
		return
	fi
	fct_pass "${unit}" "Enabled and active"
}

fct_wait_for_runtime() {
	local attempt=0
	local health_response=""

	for ((attempt = 1; attempt <= READY_ATTEMPTS; attempt++)); do
		health_response="$(
			"${CURL_BIN}" --fail --silent --show-error --max-time 2 \
				"${HEALTH_URL}" 2>/dev/null || true
		)"
		if "${SOCKET_TEST_BIN}" -S "${HELPER_SOCKET}" &&
			[[ "${health_response}" == *'"status":"ok"'* ||
				"${health_response}" == *'"status": "ok"'* ]]; then
			fct_pass "helper-connectivity" "Socket is available at ${HELPER_SOCKET}"
			fct_pass "dashboard-health" "${HEALTH_URL} returned status ok"
			return
		fi
		if ((attempt < READY_ATTEMPTS)); then
			sleep "${READY_DELAY_SECONDS}"
		fi
	done

	if ! "${SOCKET_TEST_BIN}" -S "${HELPER_SOCKET}"; then
		fct_block "helper-connectivity" \
			"Socket did not appear at ${HELPER_SOCKET}"
	fi
	if [[ "${health_response}" != *'"status":"ok"'* &&
		"${health_response}" != *'"status": "ok"'* ]]; then
		fct_block "dashboard-health" \
			"${HEALTH_URL} did not return status ok"
	fi
}

fct_show_failure_diagnostics() {
	local unit=""

	printf '%s\n' "Installation diagnostics:" >&2
	for unit in pihealth-helper.service pi-health.service \
		limeos-metrics-collector.timer; do
		"${SYSTEMCTL_BIN}" status --no-pager "${unit}" >&2 || true
	done
}

fct_main() {
	fct_parse_arguments "$@"
	fct_validate_settings

	printf '%s\n' "LimeOS installation verification"
	fct_check_docker
	fct_check_unit "pihealth-helper.service"
	fct_check_unit "pi-health.service"
	fct_check_unit "limeos-metrics-collector.timer"
	fct_wait_for_runtime

	if [[ "${FAILURES}" -gt 0 ]]; then
		printf 'Result: BLOCKED (%d failed check(s))\n' "${FAILURES}" >&2
		fct_show_failure_diagnostics
		exit 2
	fi

	printf '%s\n' "Result: READY"
}

fct_main "$@"
