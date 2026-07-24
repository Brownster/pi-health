#!/usr/bin/env bash
#
# Create the initial LimeOS dashboard credential file without handling plaintext.

set -Eeuo pipefail

readonly SCRIPT_VERSION="0.1.0"
readonly SCRIPT_PATH="${BASH_SOURCE[0]}"
readonly SCRIPT_NAME="${SCRIPT_PATH##*/}"
readonly SCRIPT_DIR="$(cd "${SCRIPT_PATH%/*}" >/dev/null 2>&1 && pwd -P)"

readonly CREDENTIALS_FILE="${LIMEOS_CREDENTIALS_FILE:-/etc/limeos/credentials.env}"
readonly CREDENTIAL_OWNER="${LIMEOS_CREDENTIAL_OWNER:-root}"
readonly CREDENTIAL_GROUP="${LIMEOS_CREDENTIAL_GROUP:-pihealth}"
readonly ADMIN_USER="${LIMEOS_ADMIN_USER:-admin}"
readonly ADMIN_PASSWORD_HASH="${LIMEOS_ADMIN_PASSWORD_HASH:-}"
readonly PYTHON_BIN="${LIMEOS_PYTHON_BIN:-python3}"
readonly PASSWORD_HASH_GENERATOR="${
	LIMEOS_PASSWORD_HASH_GENERATOR:-${SCRIPT_DIR}/generate_password_hash.py
}"

TEMPORARY_FILE=""

fct_usage() {
	printf '%s\n' \
		"${SCRIPT_NAME} v${SCRIPT_VERSION}" \
		"Create the initial LimeOS dashboard credentials." \
		"" \
		"Usage:" \
		"  ${SCRIPT_NAME} [--help] [--version]" \
		"" \
		"Environment:" \
		"  LIMEOS_ADMIN_USER           Initial username (default: admin)" \
		"  LIMEOS_ADMIN_PASSWORD_HASH  Pre-generated hash for unattended setup" \
		"" \
		"Plaintext passwords are accepted only through the hidden interactive prompt."
}

fct_cleanup() {
	if [[ -n "${TEMPORARY_FILE}" && -f "${TEMPORARY_FILE}" ]]; then
		rm -f -- "${TEMPORARY_FILE}"
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

fct_validate_username() {
	if [[ ! "${ADMIN_USER}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,63}$ ]]; then
		printf '%s\n' \
			"LIMEOS_ADMIN_USER must contain 1-64 letters, numbers, or ._@- characters." \
			>&2
		exit 2
	fi
}

fct_validate_password_hash() {
	local password_hash="${1}"
	local pbkdf2_pattern='^pbkdf2:sha256:[1-9][0-9]*\$[^$]+\$[0-9a-fA-F]{64}$'
	local scrypt_pattern='^scrypt:[1-9][0-9]*:[1-9][0-9]*:[1-9][0-9]*\$[^$]+\$[0-9a-fA-F]{128}$'

	if [[ ! "${password_hash}" =~ ${pbkdf2_pattern} &&
		! "${password_hash}" =~ ${scrypt_pattern} ]]; then
		printf '%s\n' \
			"LIMEOS_ADMIN_PASSWORD_HASH must be a Werkzeug PBKDF2-SHA256 or scrypt hash." \
			>&2
		exit 2
	fi
}

fct_collect_password_hash() {
	if [[ -n "${ADMIN_PASSWORD_HASH}" ]]; then
		fct_validate_password_hash "${ADMIN_PASSWORD_HASH}"
		printf '%s' "${ADMIN_PASSWORD_HASH}"
		return
	fi

	if [[ ! -t 0 && ! -t 1 && ! -t 2 ]]; then
		printf '%s\n' \
			"No terminal is available for the password prompt." \
			"Set LIMEOS_ADMIN_PASSWORD_HASH to a pre-generated hash for unattended setup." \
			>&2
		exit 2
	fi
	if [[ ! -f "${PASSWORD_HASH_GENERATOR}" ]]; then
		printf 'Password hash generator not found: %s\n' \
			"${PASSWORD_HASH_GENERATOR}" >&2
		exit 2
	fi

	"${PYTHON_BIN}" "${PASSWORD_HASH_GENERATOR}"
}

fct_write_credentials() {
	local password_hash="${1}"
	local credentials_dir="${CREDENTIALS_FILE%/*}"

	install -d -m 0750 -o "${CREDENTIAL_OWNER}" -g "${CREDENTIAL_GROUP}" \
		"${credentials_dir}"
	umask 0077
	TEMPORARY_FILE="$(mktemp "${CREDENTIALS_FILE}.tmp.XXXXXX")"
	printf 'PIHEALTH_USER=%s\nPIHEALTH_PASSWORD_HASH=%s\n' \
		"${ADMIN_USER}" "${password_hash}" >"${TEMPORARY_FILE}"
	chown "${CREDENTIAL_OWNER}:${CREDENTIAL_GROUP}" "${TEMPORARY_FILE}"
	chmod 0640 "${TEMPORARY_FILE}"
	mv -f -- "${TEMPORARY_FILE}" "${CREDENTIALS_FILE}"
	TEMPORARY_FILE=""
}

fct_main() {
	local password_hash=""

	fct_parse_arguments "$@"
	trap fct_cleanup EXIT INT TERM

	if [[ -s "${CREDENTIALS_FILE}" ]]; then
		printf 'Dashboard credentials already exist at %s; preserving them.\n' \
			"${CREDENTIALS_FILE}"
		return
	fi

	fct_validate_username
	password_hash="$(fct_collect_password_hash)"
	fct_write_credentials "${password_hash}"
	printf 'Created dashboard credentials for %s at %s.\n' \
		"${ADMIN_USER}" "${CREDENTIALS_FILE}"
}

fct_main "$@"
