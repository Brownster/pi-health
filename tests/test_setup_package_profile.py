from pathlib import Path


SETUP = Path("setup.sh").read_text()


def test_fresh_install_defaults_include_required_foundation():
    assert 'INSTALL_DOCKER="${INSTALL_DOCKER:-1}"' in SETUP
    assert 'INSTALL_SMARTMONTOOLS="${INSTALL_SMARTMONTOOLS:-1}"' in SETUP
    assert 'fct_prompt_install "Docker and Compose" INSTALL_DOCKER docker 1' in SETUP


def test_optional_capabilities_are_explicit_opt_ins():
    assert 'ENABLE_TAILSCALE="${ENABLE_TAILSCALE:-0}"' in SETUP
    assert 'ENABLE_VPN="${ENABLE_VPN:-0}"' in SETUP
    assert 'INSTALL_SNAPRAID="${INSTALL_SNAPRAID:-0}"' in SETUP
    assert 'INSTALL_MERGERFS="${INSTALL_MERGERFS:-0}"' in SETUP
    assert 'INSTALL_SSHFS="${INSTALL_SSHFS:-0}"' in SETUP
    assert (
        'INSTALL_LEGACY_EXAMPLE_STACKS="${INSTALL_LEGACY_EXAMPLE_STACKS:-0}"'
        in SETUP
    )


def test_install_options_are_validated_before_package_mutation():
    validation = SETUP.index("\nfct_validate_install_options\n")
    first_package_mutation = SETUP.index("apt-get update")

    assert validation < first_package_mutation
    assert "must be 0, 1, or auto" in SETUP


def test_auto_mode_does_not_block_without_a_terminal():
    assert 'if [[ ! -t 0 ]]; then' in SETUP
    assert "auto without a terminal" in SETUP


def test_docker_rerun_requires_compose_and_reconciles_service():
    assert '"${installed_command}" compose version' in SETUP
    assert "eval " not in SETUP
    assert 'systemctl enable --now docker' in SETUP


def test_legacy_examples_are_not_interactively_offered():
    legacy_function = SETUP[
        SETUP.index("fct_install_legacy_example_stacks()"):
        SETUP.index("\nfct_validate_install_options\n")
    ]

    assert 'INSTALL_LEGACY_EXAMPLE_STACKS}" != "1"' in legacy_function
    assert "read -r" not in legacy_function
    assert 'cp -R "${REPO_DIR}/examples/stacks/${stack}"' in legacy_function
    assert 'install -m 0640 -o "${RUN_USER}" -g pihealth' in legacy_function


def test_legacy_examples_install_only_after_group_creation():
    group_creation = SETUP.index("groupadd pihealth")
    legacy_install = SETUP.rindex("\nfct_install_legacy_example_stacks\n")

    assert group_creation < legacy_install
