import os
import sys
import pytest
import socket
from unittest.mock import AsyncMock, patch, MagicMock, create_autospec, PropertyMock
from typing import Tuple, Optional, Dict, Any
import inspect

# Add the source directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock socket to prevent real network connections
@pytest.fixture(autouse=True)
def mock_socket():
    with patch('socket.socket') as mock_socket:
        # Configure the mock to return a mock socket instance that doesn't
        # try to make real connections
        mock_instance = MagicMock()
        mock_socket.return_value = mock_instance
        yield mock_socket

# Direct imports with absolute paths
import src.action_handlers as action_handlers
from src.action_handlers import (
    handle_remote_macos_get_screen,
    handle_remote_macos_mouse_scroll,
    handle_remote_macos_mouse_click,
    handle_remote_macos_mouse_double_click,
    handle_remote_macos_mouse_move,
    handle_remote_macos_send_keys,
)

# Patch paths - the key insight is that we need to patch where the object is USED, not where it's defined
# In action_handlers.py, the import is "from src.vnc_client import VNCClient, capture_vnc_screen"
ACTION_HANDLERS_PATH = 'src.action_handlers'
VNC_CLIENT_PATH = 'src.action_handlers.VNCClient'  # Need to patch where it's used
CAPTURE_VNC_SCREEN_PATH = 'src.action_handlers.capture_vnc_screen'  # Need to patch where it's used

# Check which functions are async
IS_GET_SCREEN_ASYNC = inspect.iscoroutinefunction(handle_remote_macos_get_screen)
IS_MOUSE_SCROLL_ASYNC = inspect.iscoroutinefunction(handle_remote_macos_mouse_scroll)
IS_MOUSE_CLICK_ASYNC = inspect.iscoroutinefunction(handle_remote_macos_mouse_click)
IS_MOUSE_DOUBLE_CLICK_ASYNC = inspect.iscoroutinefunction(handle_remote_macos_mouse_double_click)
IS_MOUSE_MOVE_ASYNC = inspect.iscoroutinefunction(handle_remote_macos_mouse_move)
IS_SEND_KEYS_ASYNC = inspect.iscoroutinefunction(handle_remote_macos_send_keys)

# Use actual MCP types for validation
import mcp.types as types

# Constants for testing (must match what's in conftest.py)
TEST_HOST = 'test-host'
TEST_PORT = 5900
TEST_USERNAME = 'test-user'
TEST_PASSWORD = 'test-password'

@pytest.fixture
def mock_env_vars():
    """Mock environment variables for testing."""
    with patch.dict(os.environ, {
        'MACOS_HOST': TEST_HOST,
        'MACOS_PORT': str(TEST_PORT),
        'MACOS_USERNAME': TEST_USERNAME,
        'MACOS_PASSWORD': TEST_PASSWORD,
        'VNC_ENCRYPTION': 'prefer_on'
    }):
        yield

@pytest.mark.asyncio
@patch(CAPTURE_VNC_SCREEN_PATH, new_callable=AsyncMock)
async def test_handle_remote_macos_get_screen_success(mock_capture_vnc_screen, mock_env_vars):
    """Test successful screen capture handling."""
    # Arrange
    mock_capture_vnc_screen.return_value = (
        True,                   # success
        b'test_image_data',     # screen_data
        None,                   # error_message
        (1366, 768)             # dimensions
    )
    
    # Act
    if IS_GET_SCREEN_ASYNC:
        result = await handle_remote_macos_get_screen({})
    else:
        result = handle_remote_macos_get_screen({})
    
    # Assert
    assert len(result) == 2
    assert result[0].type == "image"
    assert result[0].mimeType == "image/png"
    assert result[1].text == "Image dimensions: 1366x768"
    mock_capture_vnc_screen.assert_called_once_with(
        host=TEST_HOST,
        port=TEST_PORT,
        password=TEST_PASSWORD,
        username=TEST_USERNAME,
        encryption='prefer_on'
    )

@pytest.mark.asyncio
@patch(CAPTURE_VNC_SCREEN_PATH, new_callable=AsyncMock)
async def test_handle_remote_macos_get_screen_failure(mock_capture_vnc_screen, mock_env_vars):
    """Test failed screen capture handling."""
    # Arrange
    mock_capture_vnc_screen.return_value = (
        False,                   # success
        None,                    # screen_data
        "Connection failed",     # error_message
        None                     # dimensions
    )
    
    # Act
    if IS_GET_SCREEN_ASYNC:
        result = await handle_remote_macos_get_screen({})
    else:
        result = handle_remote_macos_get_screen({})
    
    # Assert
    assert len(result) == 1
    assert result[0].type == "text"
    assert "Connection failed" in result[0].text
    mock_capture_vnc_screen.assert_called_once()

@pytest.mark.asyncio
async def test_handle_remote_macos_mouse_scroll(mock_env_vars):
    """Test mouse scroll handling with VNCClient patching."""
    with patch(VNC_CLIENT_PATH) as MockVNCClass:
        # Setup mock VNC instance
        mock_instance = MagicMock()
        MockVNCClass.return_value = mock_instance
        
        # Configure mock behavior
        mock_instance.connect.return_value = (True, None)
        mock_instance.width = 1920
        mock_instance.height = 1080
        mock_instance.send_pointer_event.return_value = True
        mock_instance.send_key_event.return_value = True
        
        # Act
        if IS_MOUSE_SCROLL_ASYNC:
            result = await handle_remote_macos_mouse_scroll({
                "x": 100,
                "y": 200,
                "direction": "down"
            })
        else:
            result = handle_remote_macos_mouse_scroll({
                "x": 100,
                "y": 200,
                "direction": "down"
            })
        
        # Assert
        assert len(result) == 1
        assert result[0].type == "text"
        mock_instance.connect.assert_called_once()
        mock_instance.close.assert_called_once()

@pytest.mark.asyncio
async def test_handle_remote_macos_mouse_click(mock_env_vars):
    """Test mouse click handling with VNCClient patching."""
    with patch(VNC_CLIENT_PATH) as MockVNCClass:
        # Setup mock VNC instance
        mock_instance = MagicMock()
        MockVNCClass.return_value = mock_instance
        
        # Configure mock behavior
        mock_instance.connect.return_value = (True, None)
        mock_instance.width = 1920
        mock_instance.height = 1080
        mock_instance.send_mouse_click.return_value = True
        
        # Act
        if IS_MOUSE_CLICK_ASYNC:
            result = await handle_remote_macos_mouse_click({
                "x": 100,
                "y": 200,
                "button": 1
            })
        else:
            result = handle_remote_macos_mouse_click({
                "x": 100,
                "y": 200,
                "button": 1
            })
        
        # Assert
        assert len(result) == 1
        assert result[0].type == "text"
        mock_instance.connect.assert_called_once()
        mock_instance.send_mouse_click.assert_called_once()
        mock_instance.close.assert_called_once()

@pytest.mark.asyncio
async def test_handle_remote_macos_mouse_double_click(mock_env_vars):
    """Test mouse double-click handling with VNCClient patching."""
    with patch(VNC_CLIENT_PATH) as MockVNCClass:
        # Setup mock VNC instance
        mock_instance = MagicMock()
        MockVNCClass.return_value = mock_instance
        
        # Configure mock behavior
        mock_instance.connect.return_value = (True, None)
        mock_instance.width = 1920
        mock_instance.height = 1080
        mock_instance.send_mouse_click.return_value = True
        
        # Act
        if IS_MOUSE_DOUBLE_CLICK_ASYNC:
            result = await handle_remote_macos_mouse_double_click({
                "x": 100,
                "y": 200,
                "button": 1
            })
        else:
            result = handle_remote_macos_mouse_double_click({
                "x": 100,
                "y": 200,
                "button": 1
            })
        
        # Assert
        assert len(result) == 1
        assert result[0].type == "text"
        mock_instance.connect.assert_called_once()
        mock_instance.send_mouse_click.assert_called_once()
        mock_instance.close.assert_called_once()

@pytest.mark.asyncio
async def test_handle_remote_macos_mouse_move(mock_env_vars):
    """Test mouse move handling with VNCClient patching."""
    with patch(VNC_CLIENT_PATH) as MockVNCClass:
        # Setup mock VNC instance
        mock_instance = MagicMock()
        MockVNCClass.return_value = mock_instance
        
        # Configure mock behavior
        mock_instance.connect.return_value = (True, None)
        mock_instance.width = 1920
        mock_instance.height = 1080
        mock_instance.send_pointer_event.return_value = True
        
        # Act
        if IS_MOUSE_MOVE_ASYNC:
            result = await handle_remote_macos_mouse_move({
                "x": 100,
                "y": 200
            })
        else:
            result = handle_remote_macos_mouse_move({
                "x": 100,
                "y": 200
            })
        
        # Assert
        assert len(result) == 1
        assert result[0].type == "text"
        mock_instance.connect.assert_called_once()
        mock_instance.send_pointer_event.assert_called_once()
        mock_instance.close.assert_called_once()

@pytest.mark.asyncio
async def test_handle_remote_macos_send_keys_text(mock_env_vars):
    """Test sending text keys with VNCClient patching."""
    with patch(VNC_CLIENT_PATH) as MockVNCClass:
        # Setup mock VNC instance
        mock_instance = MagicMock()
        MockVNCClass.return_value = mock_instance
        
        # Configure mock behavior
        mock_instance.connect.return_value = (True, None)
        mock_instance.send_text.return_value = True
        
        # Act
        if IS_SEND_KEYS_ASYNC:
            result = await handle_remote_macos_send_keys({
                "text": "Hello World"
            })
        else:
            result = handle_remote_macos_send_keys({
                "text": "Hello World"
            })
        
        # Assert
        assert len(result) == 1
        assert result[0].type == "text"
        mock_instance.connect.assert_called_once()
        mock_instance.send_text.assert_called_once_with("Hello World")
        mock_instance.close.assert_called_once()

@pytest.mark.asyncio
async def test_handle_remote_macos_send_keys_special(mock_env_vars):
    """Test sending special keys with VNCClient patching."""
    with patch(VNC_CLIENT_PATH) as MockVNCClass:
        # Setup mock VNC instance
        mock_instance = MagicMock()
        MockVNCClass.return_value = mock_instance
        
        # Configure mock behavior
        mock_instance.connect.return_value = (True, None)
        mock_instance.send_key_event.return_value = True
        
        # Act
        if IS_SEND_KEYS_ASYNC:
            result = await handle_remote_macos_send_keys({
                "special_key": "enter"
            })
        else:
            result = handle_remote_macos_send_keys({
                "special_key": "enter"
            })
        
        # Assert
        assert len(result) == 1
        assert result[0].type == "text"
        mock_instance.connect.assert_called_once()
        mock_instance.send_key_event.assert_called()
        mock_instance.close.assert_called_once()

@pytest.mark.asyncio
async def test_handle_remote_macos_send_keys_combination(mock_env_vars):
    """Test sending key combinations with VNCClient patching."""
    with patch(VNC_CLIENT_PATH) as MockVNCClass:
        # Setup mock VNC instance
        mock_instance = MagicMock()
        MockVNCClass.return_value = mock_instance
        
        # Configure mock behavior
        mock_instance.connect.return_value = (True, None)
        mock_instance.send_key_combination.return_value = True
        
        # Act
        if IS_SEND_KEYS_ASYNC:
            result = await handle_remote_macos_send_keys({
                "key_combination": "cmd+c"
            })
        else:
            result = handle_remote_macos_send_keys({
                "key_combination": "cmd+c"
            })
        
        # Assert
        assert len(result) == 1
        assert result[0].type == "text"
        mock_instance.connect.assert_called_once()
        mock_instance.send_key_combination.assert_called_once()
        mock_instance.close.assert_called_once()

@pytest.mark.asyncio
async def test_handle_connection_error(mock_env_vars):
    """Test handling connection errors with VNCClient patching."""
    with patch(VNC_CLIENT_PATH) as MockVNCClass:
        # Setup mock VNC instance
        mock_instance = MagicMock()
        MockVNCClass.return_value = mock_instance
        
        # Configure mock behavior to simulate connection failure
        mock_instance.connect.return_value = (False, "Connection failed")
        
        # Act
        if IS_MOUSE_CLICK_ASYNC:
            result = await handle_remote_macos_mouse_click({
                "x": 100,
                "y": 200,
                "button": 1
            })
        else:
            result = handle_remote_macos_mouse_click({
                "x": 100,
                "y": 200,
                "button": 1
            })
        
        # Assert
        assert len(result) == 1
        assert result[0].type == "text"
        assert "Failed to connect" in result[0].text
        assert "Connection failed" in result[0].text
        mock_instance.connect.assert_called_once()
        # Note: close() is not called when connection fails because we return early
        # This is correct behavior based on the implementation 