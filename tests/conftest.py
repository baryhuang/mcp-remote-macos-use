import os
import sys
import pytest
import asyncio
import platform
from unittest.mock import patch, MagicMock, AsyncMock

# Add the source directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configure asyncio for CI environment
def configure_event_loop():
    """
    Configure the event loop policy based on the environment.
    - Use WindowsSelectorEventLoopPolicy on Windows
    - Use default policy on other platforms but with a custom loop factory for CI
    """
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    else:
        # Check if we're in a CI environment
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
            # Set default event loop policy but with a simple loop factory
            # This avoids issues with file descriptors in containers
            
            # Create a new event loop that doesn't try to add file descriptors
            # that might cause permission issues in CI environments
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Disable signal handling in event loops to avoid permission issues
            if hasattr(loop, '_handle_signals'):
                loop._handle_signals = lambda: None
            
            if hasattr(loop, '_signal_handlers'):
                loop._signal_handlers = {}

# Configure asyncio at the start of testing
configure_event_loop()

# Let CI environments know they are running in CI
if not os.environ.get('CI') and os.environ.get('GITHUB_ACTIONS'):
    os.environ['CI'] = 'true'

# Set environment variables for testing
os.environ['MACOS_HOST'] = 'test-host'
os.environ['MACOS_PORT'] = '5900'
os.environ['MACOS_USERNAME'] = 'test-user'
os.environ['MACOS_PASSWORD'] = 'test-password'
os.environ['VNC_ENCRYPTION'] = 'prefer_on'

@pytest.fixture
def mock_global_env_vars():
    """Mock environment variables for testing."""
    with patch.dict(os.environ, {
        'MACOS_HOST': 'test-host',
        'MACOS_PORT': '5900',
        'MACOS_USERNAME': 'test-user',
        'MACOS_PASSWORD': 'test-password',
        'VNC_ENCRYPTION': 'prefer_on'
    }):
        yield

@pytest.fixture
def global_mock_vnc_client():
    """Provide a mock VNCClient for testing."""
    with patch('src.vnc_client.VNCClient') as mock_vnc_class:
        mock_instance = MagicMock()
        mock_vnc_class.return_value = mock_instance
        
        # Set up common mock properties
        mock_instance.width = 1366
        mock_instance.height = 768
        mock_instance.connect.return_value = (True, None)
        
        yield mock_instance 