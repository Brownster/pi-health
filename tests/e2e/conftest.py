import pytest
import docker
import time
import os
from playwright.sync_api import Page, expect

# Default credentials from appropriate environment variables or defaults
USERNAME = os.getenv('PIHEALTH_USER', 'admin')
PASSWORD = os.getenv('PIHEALTH_PASSWORD', 'pihealth')
BASE_URL = os.getenv('BASE_URL', 'http://localhost:8002')

@pytest.fixture(scope="session")
def test_user_credentials():
    return {"username": USERNAME, "password": PASSWORD, "base_url": BASE_URL}

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """
    Configure the browser context (e.g., viewport size, ignoring https errors).
    """
    return {
        **browser_context_args,
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 720}
    }

@pytest.fixture(scope="function")
def authenticated_page(page: Page):
    """
    Returns a Page object that is already logged in.
    """
    # Go to the login page
    page.goto(f"{BASE_URL}/login.html")
    
    # Check if we are already redirected to home (if session persisted, though scope is function/new context usually)
    if "login.html" in page.url:
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("button.login-button")
        
        # Expect to be redirected to the home page
        expect(page).to_have_url(f"{BASE_URL}/")
    
    return page

@pytest.fixture(scope="session")
def docker_client():
    """Returns a docker client."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        pytest.skip(f"Docker not available: {e}")

@pytest.fixture(scope="function")
def test_container(docker_client):
    """
    Creates a temporary container for testing purposes.
    Returns the container object.
    Teardown removes the container.
    """
    container_name = "pihealth-e2e-test-container"
    
    # Cleanup if it already exists
    try:
        old = docker_client.containers.get(container_name)
        old.remove(force=True)
    except docker.errors.NotFound:
        pass

    # Run a simple container that stays alive (alpine sleep)
    print(f"Starting test container: {container_name}")
    container = docker_client.containers.run(
        "alpine:latest",
        "sleep 300",
        name=container_name,
        detach=True
    )
    
    # Wait a moment for it to be fully registered/up
    time.sleep(2)
    
    yield container
    
    # Teardown
    print(f"Removing test container: {container_name}")
    try:
        container.remove(force=True)
    except Exception:
        pass
