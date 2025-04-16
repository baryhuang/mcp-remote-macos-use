import logging
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv
import base64
import socket
import time
import io
from PIL import Image
import asyncio
import pyDes
import json
import os
from base64 import b64encode
from datetime import datetime
import sys
import paramiko  # Add paramiko import for SSH

# Import MCP server libraries
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

# Import LiveKit
from .livekit_client import LiveKitClient

# Import VNC client functionality from the src directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vnc_client import VNCClient, capture_vnc_screen

# Import action handlers from the src directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from action_handlers import (
    handle_remote_macos_get_screen,
    handle_remote_macos_mouse_scroll,
    handle_remote_macos_send_keys,
    handle_remote_macos_mouse_move,
    handle_remote_macos_mouse_click,
    handle_remote_macos_mouse_double_click,
    handle_remote_macos_open_application,
    handle_remote_macos_mouse_drag_n_drop
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mcp_remote_macos_use')
logger.setLevel(logging.DEBUG)

# Load environment variables for VNC connection
MACOS_HOST = os.environ.get('MACOS_HOST', '')
MACOS_PORT = int(os.environ.get('MACOS_PORT', '5900'))
MACOS_USERNAME = os.environ.get('MACOS_USERNAME', '')
MACOS_PASSWORD = os.environ.get('MACOS_PASSWORD', '')
VNC_ENCRYPTION = os.environ.get('VNC_ENCRYPTION', 'prefer_on')

# LiveKit configuration
LIVEKIT_URL = os.environ.get('LIVEKIT_URL', '')

# Token file location on the remote Mac
TOKEN_FILE_PATH = "~/mcp_tokens/current_session.json"

# Log environment variable status (without exposing actual values)
logger.info(f"MACOS_HOST from environment: {'Set' if MACOS_HOST else 'Not set'}")
logger.info(f"MACOS_PORT from environment: {MACOS_PORT}")
logger.info(f"MACOS_USERNAME from environment: {'Set' if MACOS_USERNAME else 'Not set'}")
logger.info(f"MACOS_PASSWORD from environment: {'Set' if MACOS_PASSWORD else 'Not set (Required)'}")
logger.info(f"VNC_ENCRYPTION from environment: {VNC_ENCRYPTION}")
logger.info(f"LIVEKIT_URL from environment: {'Set' if LIVEKIT_URL else 'Not set'}")

# Validate required environment variables
if not MACOS_HOST:
    logger.error("MACOS_HOST environment variable is required but not set")
    raise ValueError("MACOS_HOST environment variable is required but not set")

if not MACOS_PASSWORD:
    logger.error("MACOS_PASSWORD environment variable is required but not set")
    raise ValueError("MACOS_PASSWORD environment variable is required but not set")


def get_token_from_remote_mac() -> Optional[Dict]:
    """Retrieve token information from the remote Mac via SSH"""
    try:
        logger.info(f"Retrieving token from remote Mac at {MACOS_HOST}")
        
        # Set up SSH client
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Connect to the remote Mac
        client.connect(
            hostname=MACOS_HOST,
            username=MACOS_USERNAME,
            password=MACOS_PASSWORD,
            port=22  # Default SSH port
        )
        
        # Execute command to read the token file
        # Use the ~ directly in the SSH command so it's expanded on the remote system
        cmd = f"cat {TOKEN_FILE_PATH}"
        _, stdout, stderr = client.exec_command(cmd)
        
        # Check for errors
        error = stderr.read().decode().strip()
        if error:
            logger.error(f"Error reading token file: {error}")
            client.close()
            return None
        
        # Read and parse token data
        token_data = stdout.read().decode().strip()
        if not token_data:
            logger.error("Token file is empty or does not exist")
            client.close()
            return None
        
        # Parse JSON data
        token_info = json.loads(token_data)
        logger.info(f"Successfully retrieved token for room: {token_info.get('room_name')}")
        
        # Close connection
        client.close()
        
        return token_info
    
    except Exception as e:
        logger.error(f"Failed to retrieve token from remote Mac: {str(e)}")
        return None


async def main():
    """Run the Remote MacOS MCP server."""
    logger.info("Remote MacOS computer use server starting")

    # Initialize LiveKit handler if environment variables are set
    livekit_client = None
    if LIVEKIT_URL:
        livekit_client = LiveKitClient()
        
        # Try to get token from the remote Mac
        token_info = get_token_from_remote_mac()
        
        if token_info:
            # Use the token information retrieved from the remote Mac
            room_name = token_info.get("room_name")
            server_token = token_info.get("server_token")
            server_url = token_info.get("server_url", LIVEKIT_URL)
            
            logger.info(f"Using retrieved token information for room: {room_name}")
            
            # Start LiveKit connection with the retrieved token
            success = await livekit_client.start(room_name, server_token)
            if success:
                logger.info(f"LiveKit connection established to room: {room_name}")
            else:
                logger.warning("Failed to establish LiveKit connection with retrieved token")
                livekit_client = None
        else:
            # No token could be retrieved from remote Mac
            logger.warning("Failed to retrieve token from remote Mac")
            logger.info("LiveKit connection will not be established - tokens must be generated by the remote Mac")
            livekit_client = None

    # Validate required environment variables
    if not MACOS_HOST:
        logger.error("MACOS_HOST environment variable is required but not set")
        raise ValueError("MACOS_HOST environment variable is required but not set")

    if not MACOS_PASSWORD:
        logger.error("MACOS_PASSWORD environment variable is required but not set")
        raise ValueError("MACOS_PASSWORD environment variable is required but not set")

    server = Server("remote-macos-client")

    @server.list_resources()
    async def handle_list_resources() -> list[types.Resource]:
        return []

    @server.read_resource()
    async def handle_read_resource(uri: types.AnyUrl) -> str:
        return ""

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available tools"""
        return [
            types.Tool(
                name="remote_macos_get_screen",
                description="Connect to a remote MacOs machine and get a full screenshot of the remote desktop.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                },
            ),
            types.Tool(
                name="remote_macos_mouse_scroll",
                description="Perform a mouse scroll at specified coordinates on a remote MacOs machine, with automatic coordinate scaling.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate for mouse position (in source dimensions)"},
                        "y": {"type": "integer", "description": "Y coordinate for mouse position (in source dimensions)"},
                        "source_width": {"type": "integer", "description": "Width of the reference screen for coordinate scaling", "default": 1366},
                        "source_height": {"type": "integer", "description": "Height of the reference screen for coordinate scaling", "default": 768},
                        "direction": {
                            "type": "string",
                            "description": "Scroll direction",
                            "enum": ["up", "down"],
                            "default": "down"
                        }
                    },
                    "required": ["x", "y"]
                },
            ),
            types.Tool(
                name="remote_macos_send_keys",
                description="Send keyboard input to a remote MacOs machine.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to send as keystrokes"},
                        "special_key": {"type": "string", "description": "Special key to send (e.g., 'enter', 'backspace', 'tab', 'escape', etc.)"},
                        "key_combination": {"type": "string", "description": "Key combination to send (e.g., 'ctrl+c', 'cmd+q', 'ctrl+alt+delete', etc.)"}
                    },
                    "required": []
                },
            ),
            types.Tool(
                name="remote_macos_mouse_move",
                description="Move the mouse cursor to specified coordinates on a remote MacOs machine, with automatic coordinate scaling.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate for mouse position (in source dimensions)"},
                        "y": {"type": "integer", "description": "Y coordinate for mouse position (in source dimensions)"},
                        "source_width": {"type": "integer", "description": "Width of the reference screen for coordinate scaling", "default": 1366},
                        "source_height": {"type": "integer", "description": "Height of the reference screen for coordinate scaling", "default": 768}
                    },
                    "required": ["x", "y"]
                },
            ),
            types.Tool(
                name="remote_macos_mouse_click",
                description="Perform a mouse click at specified coordinates on a remote MacOs machine, with automatic coordinate scaling.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate for mouse position (in source dimensions)"},
                        "y": {"type": "integer", "description": "Y coordinate for mouse position (in source dimensions)"},
                        "source_width": {"type": "integer", "description": "Width of the reference screen for coordinate scaling", "default": 1366},
                        "source_height": {"type": "integer", "description": "Height of the reference screen for coordinate scaling", "default": 768},
                        "button": {"type": "integer", "description": "Mouse button (1=left, 2=middle, 3=right)", "default": 1}
                    },
                    "required": ["x", "y"]
                },
            ),
            types.Tool(
                name="remote_macos_mouse_double_click",
                description="Perform a mouse double-click at specified coordinates on a remote MacOs machine, with automatic coordinate scaling.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate for mouse position (in source dimensions)"},
                        "y": {"type": "integer", "description": "Y coordinate for mouse position (in source dimensions)"},
                        "source_width": {"type": "integer", "description": "Width of the reference screen for coordinate scaling", "default": 1366},
                        "source_height": {"type": "integer", "description": "Height of the reference screen for coordinate scaling", "default": 768},
                        "button": {"type": "integer", "description": "Mouse button (1=left, 2=middle, 3=right)", "default": 1}
                    },
                    "required": ["x", "y"]
                },
            ),
            types.Tool(
                name="remote_macos_open_application",
                description="Opens/activates an application and returns its PID for further interactions.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "identifier": {
                            "type": "string",
                            "description": "REQUIRED. App name, path, or bundle ID."
                        }
                    },
                    "required": ["identifier"]
                },
            ),
            types.Tool(
                name="remote_macos_mouse_drag_n_drop",
                description="Perform a mouse drag operation from start point and drop to end point on a remote MacOs machine, with automatic coordinate scaling.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "start_x": {"type": "integer", "description": "Starting X coordinate (in source dimensions)"},
                        "start_y": {"type": "integer", "description": "Starting Y coordinate (in source dimensions)"},
                        "end_x": {"type": "integer", "description": "Ending X coordinate (in source dimensions)"},
                        "end_y": {"type": "integer", "description": "Ending Y coordinate (in source dimensions)"},
                        "source_width": {"type": "integer", "description": "Width of the reference screen for coordinate scaling", "default": 1366},
                        "source_height": {"type": "integer", "description": "Height of the reference screen for coordinate scaling", "default": 768},
                        "button": {"type": "integer", "description": "Mouse button (1=left, 2=middle, 3=right)", "default": 1},
                        "steps": {"type": "integer", "description": "Number of intermediate points for smooth dragging", "default": 10},
                        "delay_ms": {"type": "integer", "description": "Delay between steps in milliseconds", "default": 10}
                    },
                    "required": ["start_x", "start_y", "end_x", "end_y"]
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Handle tool execution requests"""
        try:
            if not arguments:
                arguments = {}

            if name == "remote_macos_get_screen":
                return await handle_remote_macos_get_screen(arguments, livekit_client)

            elif name == "remote_macos_mouse_scroll":
                return handle_remote_macos_mouse_scroll(arguments)

            elif name == "remote_macos_send_keys":
                return handle_remote_macos_send_keys(arguments)

            elif name == "remote_macos_mouse_move":
                return handle_remote_macos_mouse_move(arguments)

            elif name == "remote_macos_mouse_click":
                return handle_remote_macos_mouse_click(arguments)

            elif name == "remote_macos_mouse_double_click":
                return handle_remote_macos_mouse_double_click(arguments)

            elif name == "remote_macos_open_application":
                return handle_remote_macos_open_application(arguments)

            elif name == "remote_macos_mouse_drag_n_drop":
                return handle_remote_macos_mouse_drag_n_drop(arguments)

            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            logger.error(f"Error in handle_call_tool: {str(e)}", exc_info=True)
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logger.info("Server running with stdio transport")
        try:
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="vnc-client",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
        finally:
            if livekit_client:
                await livekit_client.stop()

if __name__ == "__main__":
    # Load environment variables from .env file if it exists
    load_dotenv()

    try:
        # Run the server
        asyncio.run(main())
    except ValueError as e:
        logger.error(f"Initialization failed: {str(e)}")
        print(f"ERROR: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        print(f"ERROR: Unexpected error occurred: {str(e)}")
        sys.exit(1)