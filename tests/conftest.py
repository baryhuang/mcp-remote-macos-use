import os
import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# Add the source directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import and configure asyncio for CI environment
from tests.asyncio_config import configure_event_loop

# Configure asyncio at the start of testing
configure_event_loop()

# Set environment variables for testing
os.environ['MACOS_HOST'] = 'test-host'
os.environ['MACOS_PORT'] = '5900'
os.environ['MACOS_USERNAME'] = 'test-user'
os.environ['MACOS_PASSWORD'] = 'test-password'
os.environ['VNC_ENCRYPTION'] = 'prefer_on'

# Let CI environments know they are running in CI
if not os.environ.get('CI') and os.environ.get('GITHUB_ACTIONS'):
    os.environ['CI'] = 'true'

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