import logging
from typing import Any, Dict, List, Optional, Tuple
import base64
import os
import sys

import mcp.types as types
# Import vnc_client from the current directory
from vnc_client import VNCClient, capture_vnc_screen

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('action_handlers')
logger.setLevel(logging.DEBUG)

# Load environment variables for VNC connection
MACOS_HOST = os.environ.get('MACOS_HOST', '')
MACOS_PORT = int(os.environ.get('MACOS_PORT', '5900'))
MACOS_USERNAME = os.environ.get('MACOS_USERNAME', '')
MACOS_PASSWORD = os.environ.get('MACOS_PASSWORD', '')
VNC_ENCRYPTION = os.environ.get('VNC_ENCRYPTION', 'prefer_on')

# Log environment variable status (without exposing actual values)
logger.info(f"MACOS_HOST from environment: {'Set' if MACOS_HOST else 'Not set'}")
logger.info(f"MACOS_PORT from environment: {MACOS_PORT}")
logger.info(f"MACOS_USERNAME from environment: {'Set' if MACOS_USERNAME else 'Not set'}")
logger.info(f"MACOS_PASSWORD from environment: {'Set' if MACOS_PASSWORD else 'Not set (Required)'}")
logger.info(f"VNC_ENCRYPTION from environment: {VNC_ENCRYPTION}")

# Check for required environment variables - use strict checking only in server.py, not when importing
if not MACOS_HOST:
    logger.warning("MACOS_HOST environment variable is not set")

if not MACOS_PASSWORD:
    logger.warning("MACOS_PASSWORD environment variable is not set")


async def handle_remote_macos_get_screen(arguments: dict[str, Any]) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Connect to a remote MacOs machine and get a screenshot of the remote desktop."""
    # Use environment variables
    host = MACOS_HOST
    port = MACOS_PORT
    password = MACOS_PASSWORD
    username = MACOS_USERNAME
    encryption = VNC_ENCRYPTION

    # Capture screen using helper method
    success, screen_data, error_message, dimensions = await capture_vnc_screen(
        host=host, port=port, password=password, username=username, encryption=encryption
    )

    if not success:
        return [types.TextContent(type="text", text=error_message)]

    # Encode image in base64
    base64_data = base64.b64encode(screen_data).decode('utf-8')

    # Return image content with dimensions
    width, height = dimensions
    return [
        types.ImageContent(
            type="image",
            data=base64_data,
            mimeType="image/png",
            alt_text=f"Screenshot from remote MacOs machine at {host}:{port}"
        ),
        types.TextContent(
            type="text",
            text=f"Image dimensions: {width}x{height}"
        )
    ]


def handle_remote_macos_mouse_scroll(arguments: dict[str, Any]) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Perform a mouse scroll action on a remote MacOs machine."""
    # Use environment variables
    host = MACOS_HOST
    port = MACOS_PORT
    password = MACOS_PASSWORD
    username = MACOS_USERNAME
    encryption = VNC_ENCRYPTION

    # Get required parameters from arguments
    x = arguments.get("x")
    y = arguments.get("y")
    source_width = int(arguments.get("source_width", 1366))
    source_height = int(arguments.get("source_height", 768))
    direction = arguments.get("direction", "down")

    if x is None or y is None:
        raise ValueError("x and y coordinates are required")

    # Ensure source dimensions are positive
    if source_width <= 0 or source_height <= 0:
        raise ValueError("Source dimensions must be positive values")

    # Initialize VNC client
    vnc = VNCClient(host=host, port=port, password=password, username=username, encryption=encryption)

    # Connect to remote MacOs machine
    success, error_message = vnc.connect()
    if not success:
        error_msg = f"Failed to connect to remote MacOs machine at {host}:{port}. {error_message}"
        return [types.TextContent(type="text", text=error_msg)]

    try:
        # Get target screen dimensions
        target_width = vnc.width
        target_height = vnc.height

        # Scale coordinates
        scaled_x = int((x / source_width) * target_width)
        scaled_y = int((y / source_height) * target_height)

        # Ensure coordinates are within the screen bounds
        scaled_x = max(0, min(scaled_x, target_width - 1))
        scaled_y = max(0, min(scaled_y, target_height - 1))

        # First move the mouse to the target location without clicking
        move_result = vnc.send_pointer_event(scaled_x, scaled_y, 0)

        # Map of special keys for page up/down
        special_keys = {
            "up": 0xff55,    # Page Up key
            "down": 0xff56,  # Page Down key
        }

        # Send the appropriate page key based on direction
        key = special_keys["up" if direction.lower() == "up" else "down"]
        key_result = vnc.send_key_event(key, True) and vnc.send_key_event(key, False)

        # Prepare the response with useful details
        scale_factors = {
            "x": target_width / source_width,
            "y": target_height / source_height
        }

        return [types.TextContent(
            type="text",
            text=f"""Mouse move to ({scaled_x}, {scaled_y}) {'succeeded' if move_result else 'failed'}
Page {direction} key press {'succeeded' if key_result else 'failed'}
Source dimensions: {source_width}x{source_height}
Target dimensions: {target_width}x{target_height}
Scale factors: {scale_factors['x']:.4f}x, {scale_factors['y']:.4f}y"""
        )]
    finally:
        # Close VNC connection
        vnc.close()


def handle_remote_macos_mouse_click(arguments: dict[str, Any]) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Perform a mouse click action on a remote MacOs machine."""
    # Use environment variables
    host = MACOS_HOST
    port = MACOS_PORT
    password = MACOS_PASSWORD
    username = MACOS_USERNAME
    encryption = VNC_ENCRYPTION

    # Get required parameters from arguments
    x = arguments.get("x")
    y = arguments.get("y")
    source_width = int(arguments.get("source_width", 1366))
    source_height = int(arguments.get("source_height", 768))
    button = int(arguments.get("button", 1))

    if x is None or y is None:
        raise ValueError("x and y coordinates are required")

    # Ensure source dimensions are positive
    if source_width <= 0 or source_height <= 0:
        raise ValueError("Source dimensions must be positive values")

    # Initialize VNC client
    vnc = VNCClient(host=host, port=port, password=password, username=username, encryption=encryption)

    # Connect to remote MacOs machine
    success, error_message = vnc.connect()
    if not success:
        error_msg = f"Failed to connect to remote MacOs machine at {host}:{port}. {error_message}"
        return [types.TextContent(type="text", text=error_msg)]

    try:
        # Get target screen dimensions
        target_width = vnc.width
        target_height = vnc.height

        # Scale coordinates
        scaled_x = int((x / source_width) * target_width)
        scaled_y = int((y / source_height) * target_height)

        # Ensure coordinates are within the screen bounds
        scaled_x = max(0, min(scaled_x, target_width - 1))
        scaled_y = max(0, min(scaled_y, target_height - 1))

        # Single click
        result = vnc.send_mouse_click(scaled_x, scaled_y, button, False)

        # Prepare the response with useful details
        scale_factors = {
            "x": target_width / source_width,
            "y": target_height / source_height
        }

        return [types.TextContent(
            type="text",
            text=f"""Mouse click (button {button}) from source ({x}, {y}) to target ({scaled_x}, {scaled_y}) {'succeeded' if result else 'failed'}
Source dimensions: {source_width}x{source_height}
Target dimensions: {target_width}x{target_height}
Scale factors: {scale_factors['x']:.4f}x, {scale_factors['y']:.4f}y"""
        )]
    finally:
        # Close VNC connection
        vnc.close()


def handle_remote_macos_send_keys(arguments: dict[str, Any]) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Send keyboard input to a remote MacOs machine."""
    # Use environment variables
    host = MACOS_HOST
    port = MACOS_PORT
    password = MACOS_PASSWORD
    username = MACOS_USERNAME
    encryption = VNC_ENCRYPTION

    # Get required parameters from arguments
    text = arguments.get("text")
    special_key = arguments.get("special_key")
    key_combination = arguments.get("key_combination")

    if not text and not special_key and not key_combination:
        raise ValueError("Either text, special_key, or key_combination must be provided")

    # Initialize VNC client
    vnc = VNCClient(host=host, port=port, password=password, username=username, encryption=encryption)

    # Connect to remote MacOs machine
    success, error_message = vnc.connect()
    if not success:
        error_msg = f"Failed to connect to remote MacOs machine at {host}:{port}. {error_message}"
        return [types.TextContent(type="text", text=error_msg)]

    try:
        result_message = []

        # Map of special key names to X11 keysyms
        special_keys = {
            "enter": 0xff0d,
            "return": 0xff0d,
            "backspace": 0xff08,
            "tab": 0xff09,
            "escape": 0xff1b,
            "esc": 0xff1b,
            "delete": 0xffff,
            "del": 0xffff,
            "home": 0xff50,
            "end": 0xff57,
            "page_up": 0xff55,
            "page_down": 0xff56,
            "left": 0xff51,
            "up": 0xff52,
            "right": 0xff53,
            "down": 0xff54,
            "f1": 0xffbe,
            "f2": 0xffbf,
            "f3": 0xffc0,
            "f4": 0xffc1,
            "f5": 0xffc2,
            "f6": 0xffc3,
            "f7": 0xffc4,
            "f8": 0xffc5,
            "f9": 0xffc6,
            "f10": 0xffc7,
            "f11": 0xffc8,
            "f12": 0xffc9,
            "space": 0x20,
        }

        # Map of modifier key names to X11 keysyms
        modifier_keys = {
            "ctrl": 0xffe3,    # Control_L
            "control": 0xffe3,  # Control_L
            "shift": 0xffe1,   # Shift_L
            "alt": 0xffe9,     # Alt_L
            "option": 0xffe9,  # Alt_L (Mac convention)
            "cmd": 0xffeb,     # Command_L (Mac convention)
            "command": 0xffeb,  # Command_L (Mac convention)
            "win": 0xffeb,     # Command_L
            "super": 0xffeb,   # Command_L
            "fn": 0xffed,      # Function key
            "meta": 0xffeb,    # Command_L (Mac convention)
        }

        # Map for letter keys (a-z)
        letter_keys = {chr(i): i for i in range(ord('a'), ord('z') + 1)}

        # Map for number keys (0-9)
        number_keys = {str(i): ord(str(i)) for i in range(10)}

        # Process special key
        if special_key:
            if special_key.lower() in special_keys:
                key = special_keys[special_key.lower()]
                if vnc.send_key_event(key, True) and vnc.send_key_event(key, False):
                    result_message.append(f"Sent special key: {special_key}")
                else:
                    result_message.append(f"Failed to send special key: {special_key}")
            else:
                result_message.append(f"Unknown special key: {special_key}")
                result_message.append(f"Supported special keys: {', '.join(special_keys.keys())}")

        # Process text
        if text:
            if vnc.send_text(text):
                result_message.append(f"Sent text: '{text}'")
            else:
                result_message.append(f"Failed to send text: '{text}'")

        # Process key combination
        if key_combination:
            keys = []
            for part in key_combination.lower().split('+'):
                part = part.strip()
                if part in modifier_keys:
                    keys.append(modifier_keys[part])
                elif part in special_keys:
                    keys.append(special_keys[part])
                elif part in letter_keys:
                    keys.append(letter_keys[part])
                elif part in number_keys:
                    keys.append(number_keys[part])
                elif len(part) == 1:
                    # For any other single character keys
                    keys.append(ord(part))
                else:
                    result_message.append(f"Unknown key in combination: {part}")
                    break

            if len(keys) == len(key_combination.split('+')):
                if vnc.send_key_combination(keys):
                    result_message.append(f"Sent key combination: {key_combination}")
                else:
                    result_message.append(f"Failed to send key combination: {key_combination}")

        return [types.TextContent(type="text", text="\n".join(result_message))]
    finally:
        vnc.close()


def handle_remote_macos_mouse_double_click(arguments: dict[str, Any]) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Perform a mouse double-click action on a remote MacOs machine."""
    # Use environment variables
    host = MACOS_HOST
    port = MACOS_PORT
    password = MACOS_PASSWORD
    username = MACOS_USERNAME
    encryption = VNC_ENCRYPTION

    # Get required parameters from arguments
    x = arguments.get("x")
    y = arguments.get("y")
    source_width = int(arguments.get("source_width", 1366))
    source_height = int(arguments.get("source_height", 768))
    button = int(arguments.get("button", 1))

    if x is None or y is None:
        raise ValueError("x and y coordinates are required")

    # Ensure source dimensions are positive
    if source_width <= 0 or source_height <= 0:
        raise ValueError("Source dimensions must be positive values")

    # Initialize VNC client
    vnc = VNCClient(host=host, port=port, password=password, username=username, encryption=encryption)

    # Connect to remote MacOs machine
    success, error_message = vnc.connect()
    if not success:
        error_msg = f"Failed to connect to remote MacOs machine at {host}:{port}. {error_message}"
        return [types.TextContent(type="text", text=error_msg)]

    try:
        # Get target screen dimensions
        target_width = vnc.width
        target_height = vnc.height

        # Scale coordinates
        scaled_x = int((x / source_width) * target_width)
        scaled_y = int((y / source_height) * target_height)

        # Ensure coordinates are within the screen bounds
        scaled_x = max(0, min(scaled_x, target_width - 1))
        scaled_y = max(0, min(scaled_y, target_height - 1))

        # Double click
        result = vnc.send_mouse_click(scaled_x, scaled_y, button, True)

        # Prepare the response with useful details
        scale_factors = {
            "x": target_width / source_width,
            "y": target_height / source_height
        }

        return [types.TextContent(
            type="text",
            text=f"""Mouse double-click (button {button}) from source ({x}, {y}) to target ({scaled_x}, {scaled_y}) {'succeeded' if result else 'failed'}
Source dimensions: {source_width}x{source_height}
Target dimensions: {target_width}x{target_height}
Scale factors: {scale_factors['x']:.4f}x, {scale_factors['y']:.4f}y"""
        )]
    finally:
        # Close VNC connection
        vnc.close()


def handle_remote_macos_mouse_move(arguments: dict[str, Any]) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Move the mouse cursor on a remote MacOs machine."""
    # Use environment variables
    host = MACOS_HOST
    port = MACOS_PORT
    password = MACOS_PASSWORD
    username = MACOS_USERNAME
    encryption = VNC_ENCRYPTION

    # Get required parameters from arguments
    x = arguments.get("x")
    y = arguments.get("y")
    source_width = int(arguments.get("source_width", 1366))
    source_height = int(arguments.get("source_height", 768))

    if x is None or y is None:
        raise ValueError("x and y coordinates are required")

    # Ensure source dimensions are positive
    if source_width <= 0 or source_height <= 0:
        raise ValueError("Source dimensions must be positive values")

    # Initialize VNC client
    vnc = VNCClient(host=host, port=port, password=password, username=username, encryption=encryption)

    # Connect to remote MacOs machine
    success, error_message = vnc.connect()
    if not success:
        error_msg = f"Failed to connect to remote MacOs machine at {host}:{port}. {error_message}"
        return [types.TextContent(type="text", text=error_msg)]

    try:
        # Get target screen dimensions
        target_width = vnc.width
        target_height = vnc.height

        # Scale coordinates
        scaled_x = int((x / source_width) * target_width)
        scaled_y = int((y / source_height) * target_height)

        # Ensure coordinates are within the screen bounds
        scaled_x = max(0, min(scaled_x, target_width - 1))
        scaled_y = max(0, min(scaled_y, target_height - 1))

        # Move mouse pointer (button_mask=0 means no buttons are pressed)
        result = vnc.send_pointer_event(scaled_x, scaled_y, 0)

        # Prepare the response with useful details
        scale_factors = {
            "x": target_width / source_width,
            "y": target_height / source_height
        }

        return [types.TextContent(
            type="text",
            text=f"""Mouse move from source ({x}, {y}) to target ({scaled_x}, {scaled_y}) {'succeeded' if result else 'failed'}
Source dimensions: {source_width}x{source_height}
Target dimensions: {target_width}x{target_height}
Scale factors: {scale_factors['x']:.4f}x, {scale_factors['y']:.4f}y"""
        )]
    finally:
        # Close VNC connection
        vnc.close()