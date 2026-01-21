# UI Validation Framework

This project includes an end-to-end (E2E) UI testing framework built with **Playwright** and **pytest**. This framework ensures confidence in core functionality, prevents regressions, and verifies the system from frontend to backend.

## Prerequisites

1.  **Python 3.8+**
2.  **Docker** (required for running test containers)
3.   The **Pi-Health application** must be running locally (default: `http://localhost:8002`).

## Setup

1.  Install the testing requirements:
    ```bash
    pip install -r tests/requirements.txt
    ```

2.  Install Playwright browsers:
    ```bash
    playwright install chromium
    ```

## Running Tests

To run the UI tests, use the following command from the project root:

```bash
pytest tests/e2e
```

### Options

-   **Run in Headed Mode** (to see the browser actions):
    ```bash
    pytest tests/e2e --headed
    ```

-   **Run on a different URL**:
    By default, tests run against `http://localhost:8002`. To change this:
    ```bash
    BASE_URL=http://your-ip:8002 pytest tests/e2e
    ```

-   **Debug Mode** (pause on failure):
    ```bash
    pytest tests/e2e --headed --pdb
    ```

## Test Structure

-   **`tests/e2e/test_ui_workflows.py`**: Contains the test scenarios.
    -   `test_login_success`: Verifies authentication.
    -   `test_container_stop_workflow`: Spins up a test container, stops it via UI, and verifies status.
    -   `test_navigation_regression`: Checks critical pages for loading errors.
-   **`tests/e2e/conftest.py`**: Shared fixtures.
    -   `authenticated_page`: Handles automatic login before tests.
    -   `test_container`: Automatically creates and destroys a Docker container for safe testing.

## CI/CD Integration

To run these tests in a CI environment, we use GitHub Actions.

See [.github/workflows/tests.yml](.github/workflows/tests.yml) for the configuration.

The workflow:
1.  Installs Python dependencies.
2.  Installs Playwright browsers.
3.  Starts the Pi-Health application in the background.
4.  Runs the E2E tests against `http://localhost:8002`.
