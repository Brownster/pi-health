#!/usr/bin/env bash
#
# Read-only host suitability check for LimeOS guided onboarding.

set -Eeuo pipefail

readonly SCRIPT_VERSION="0.1.0"
readonly SCRIPT_PATH="${BASH_SOURCE[0]}"
readonly SCRIPT_NAME="${SCRIPT_PATH##*/}"
readonly DEFAULT_OS_RELEASE_FILE="/etc/os-release"

BLOCKERS=0

fct_usage() {
	printf '%s\n' \
		"${SCRIPT_NAME} v${SCRIPT_VERSION}" \
		"Read-only Debian Bookworm onboarding preflight." \
		"" \
		"Usage:" \
		"  ${SCRIPT_NAME} [--help] [--version]" \
		"" \
		"Exit codes:" \
		"  0  Host is supported" \
		"  2  Host has one or more blocking compatibility problems"
}

fct_pass() {
	printf '[PASS] %s: %s\n' "${1}" "${2}"
}

fct_info() {
	printf '[INFO] %s: %s\n' "${1}" "${2}"
}

fct_block() {
	printf '[BLOCK] %s: %s\n' "${1}" "${2}"
	BLOCKERS=$((BLOCKERS + 1))
}

fct_strip_os_release_value() {
	local value="${1}"

	if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
		value="${value:1:${#value}-2}"
	elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
		value="${value:1:${#value}-2}"
	fi
	printf '%s' "${value}"
}

fct_read_os_release_value() {
	local requested_key="${1}"
	local os_release_file="${2}"
	local key=""
	local value=""

	while IFS='=' read -r key value || [[ -n "${key}" ]]; do
		if [[ "${key}" == "${requested_key}" ]]; then
			fct_strip_os_release_value "${value}"
			return 0
		fi
	done <"${os_release_file}"
	return 1
}

fct_detect_operator() {
	if [[ ${LIMEOS_OPERATOR+x} ]]; then
		printf '%s' "${LIMEOS_OPERATOR}"
	elif [[ -n "${SUDO_USER:-}" ]]; then
		printf '%s' "${SUDO_USER}"
	else
		printf '%s' "${USER:-}"
	fi
}

fct_check_platform() {
	local os_release_file="${LIMEOS_OS_RELEASE_FILE:-${DEFAULT_OS_RELEASE_FILE}}"
	local os_id=""
	local codename=""
	local machine="${LIMEOS_MACHINE:-$(uname -m)}"

	if [[ ! -r "${os_release_file}" ]]; then
		fct_block "operating-system" "Cannot read ${os_release_file}"
	else
		os_id="$(fct_read_os_release_value "ID" "${os_release_file}" || true)"
		codename="$(
			fct_read_os_release_value "VERSION_CODENAME" "${os_release_file}" || true
		)"
		if [[ "${os_id}" == "debian" && "${codename}" == "bookworm" ]]; then
			fct_pass "operating-system" "Debian bookworm"
		else
			fct_block "operating-system" \
				"Requires Debian bookworm; found ${os_id:-unknown} ${codename:-unknown}"
		fi
	fi

	case "${machine}" in
	aarch64 | arm64)
		fct_pass "architecture" "arm64 (${machine})"
		;;
	x86_64 | amd64)
		fct_pass "architecture" "amd64 (${machine})"
		;;
	*)
		fct_block "architecture" \
			"Requires arm64 or amd64; found ${machine:-unknown}"
		;;
	esac
}

fct_check_operator() {
	local operator=""
	local operator_uid=""
	local operator_gid=""
	local operator_home=""
	local can_escalate="${LIMEOS_CAN_ESCALATE:-auto}"

	operator="$(fct_detect_operator)"
	if [[ -z "${operator}" ]] || ! id "${operator}" >/dev/null 2>&1; then
		fct_block "operator" "Unable to resolve the interactive SSH user"
		return
	fi

	operator_uid="$(id -u "${operator}")"
	operator_gid="$(id -g "${operator}")"
	operator_home="$(getent passwd "${operator}" | cut -d: -f6)"
	if [[ -z "${operator_home}" || "${operator_home}" != /* ]]; then
		fct_block "operator-home" "Unable to resolve an absolute home for ${operator}"
	else
		fct_pass "operator" \
			"${operator} uid=${operator_uid} gid=${operator_gid} home=${operator_home}"
	fi

	if [[ "${can_escalate}" == "1" || "${EUID}" -eq 0 ]]; then
		fct_pass "privilege" "Root access is available"
	elif [[ "${can_escalate}" == "0" ]] || ! command -v sudo >/dev/null 2>&1; then
		fct_block "privilege" "Install sudo or run the installer as root"
	else
		fct_pass "privilege" "sudo is available"
	fi
}

fct_check_bootstrap_tools() {
	local command_name=""
	local missing=()

	for command_name in git curl python3; do
		if ! command -v "${command_name}" >/dev/null 2>&1; then
			missing+=("${command_name}")
		fi
	done

	if [[ ${#missing[@]} -eq 0 ]]; then
		fct_pass "bootstrap-tools" "git, curl, and python3 are available"
	else
		fct_info "bootstrap-tools" \
			"Installer must add: ${missing[*]}"
	fi
}

fct_check_usb_storage() {
	local usb_count="${LIMEOS_USB_DEVICE_COUNT:-}"

	if [[ -z "${usb_count}" ]]; then
		if command -v lsblk >/dev/null 2>&1 &&
			command -v awk >/dev/null 2>&1; then
			usb_count="$(
				lsblk -dnro TRAN,TYPE 2>/dev/null |
					awk '$1 == "usb" && $2 == "disk" { count++ } END { print count + 0 }'
			)"
		else
			usb_count="unknown"
		fi
	fi

	if [[ "${usb_count}" == "0" ]]; then
		fct_info "usb-storage" "No USB disks detected; connect drives before storage setup"
	else
		fct_info "usb-storage" "${usb_count} USB disk(s) detected"
	fi
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
		*)
			printf 'Unknown option: %s\n' "${1}" >&2
			fct_usage >&2
			exit 64
			;;
		esac
	done
}

fct_main() {
	fct_parse_arguments "$@"
	printf 'LimeOS onboarding preflight\n'
	fct_check_platform
	fct_check_operator
	fct_check_bootstrap_tools
	fct_check_usb_storage

	if ((BLOCKERS > 0)); then
		printf 'Result: BLOCKED (%d issue(s))\n' "${BLOCKERS}"
		exit 2
	fi
	printf 'Result: READY\n'
}

fct_main "$@"
