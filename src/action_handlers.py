import logging
from typing import Any, Dict, List, Optional, Tuple
import base64
import os
import sys
import subprocess
import time
import json
from datetime import datetime

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

# Create an audit log for tracking actions
# This will store entries with timestamps, action name, and parameters
ACTION_AUDIT_LOG = []
# Maximum number of audit log entries to keep
MAX_AUDIT_LOG_ENTRIES = 100
# Last action timestamp
LAST_ACTION_TIMESTAMP = 0

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


def log_action(action_name: str, arguments: Dict[str, Any]) -> None:
    """Add an entry to the audit log for an action"""
    global LAST_ACTION_TIMESTAMP
    
    # Create a sanitized copy of the arguments for logging
    # Remove any sensitive information like passwords
    safe_args = {k: v for k, v in arguments.items() if k not in ('password', 'token')}
    
    timestamp = time.time()
    LAST_ACTION_TIMESTAMP = timestamp
    
    # Create an audit log entry
    entry = {
        "timestamp": timestamp,
        "iso_time": datetime.fromtimestamp(timestamp).isoformat(),
        "action": action_name,
        "arguments": safe_args
    }
    
    # Add to audit log
    ACTION_AUDIT_LOG.append(entry)
    
    # Trim audit log if it's too large
    if len(ACTION_AUDIT_LOG) > MAX_AUDIT_LOG_ENTRIES:
        ACTION_AUDIT_LOG.pop(0)
    
    logger.info(f"Action logged: {action_name} with arguments: {safe_args}")


async def handle_remote_macos_get_screen(arguments: dict[str, Any], livekit_client=None) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Get the last screen image from LiveKit client's message buffer."""
    # Log this action
    # log_action("remote_macos_get_screen", arguments)
    
    if livekit_client is None:
        return [types.TextContent(
            type="text",
            text="Error: LiveKit client is not available. Make sure LiveKit is properly configured."
        )]
    
    # Try to get screen captures specifically first
    if hasattr(livekit_client, 'get_screen_captures'):
        screen_captures = livekit_client.get_screen_captures()
        if screen_captures:
            # Get the most recent screen capture
            latest_capture = max(screen_captures, key=lambda x: x["timestamp"])
            if "screen_path" in latest_capture:
                # We have a file path to a saved image
                img_path = latest_capture["screen_path"]
                if os.path.exists(img_path):
                    with open(img_path, "rb") as f:
                        image_data = f.read()
                    
                    # Encode to base64
                    base64_data = base64.b64encode(image_data).decode('utf-8')
                    
                    # Get dimensions from the message if available, otherwise use default
                    dimensions = latest_capture.get("message", {}).get("content", {}).get("dimensions", {})
                    width = dimensions.get("width", 1366)
                    height = dimensions.get("height", 768)
                    
                    # Return image content with dimensions
                    return [
                        types.ImageContent(
                            type="image",
                            data=base64_data,
                            mimeType="image/png",
                            alt_text=f"Last screenshot from remote MacOs machine"
                        ),
                        types.TextContent(
                            type="text",
                            text=f"Image dimensions: {width}x{height}"
                        )
                    ]
    
    # Fall back to searching the full message history
    message_history = livekit_client.get_message_history()
    
    # First, look for screen update messages with file paths
    file_messages = [
        msg for msg in message_history 
        if msg.get("message", {}).get("type") == MESSAGE_TYPE_SCREEN_UPDATE and 
        msg.get("message", {}).get("content", {}).get("file_path")
    ]
    
    if file_messages:
        # Get the latest file message
        latest_file_message = max(file_messages, key=lambda x: x["timestamp"])
        img_path = latest_file_message["message"]["content"]["file_path"]
        
        if os.path.exists(img_path):
            with open(img_path, "rb") as f:
                image_data = f.read()
            
            # Encode to base64
            base64_data = base64.b64encode(image_data).decode('utf-8')
            
            # Get dimensions from the message if available, otherwise use default
            dimensions = latest_file_message["message"]["content"].get("dimensions", {})
            width = dimensions.get("width", 1366)
            height = dimensions.get("height", 768)
            
            # Return image content with dimensions
            return [
                types.ImageContent(
                    type="image",
                    data=base64_data,
                    mimeType="image/png",
                    alt_text=f"Last screenshot from remote MacOs machine"
                ),
                types.TextContent(
                    type="text",
                    text=f"Image dimensions: {width}x{height}"
                )
            ]
    
    # Fall back to looking for the old format with base64-encoded images
    image_messages = [
        msg for msg in message_history 
        if (msg.get("message", {}).get("type") == "result" or 
            msg.get("message", {}).get("type") == MESSAGE_TYPE_SCREEN_UPDATE) and 
        msg.get("message", {}).get("content", {}).get("image_data")
    ]
    
    if not image_messages and not file_messages:
        return [types.TextContent(
            type="text",
            text="No screen images found in message history. Try refreshing or waiting for updates."
        )]
    
    # Get the latest image message if we have one
    if image_messages:
        latest_image_message = max(image_messages, key=lambda x: x["timestamp"])
        image_data = latest_image_message["message"]["content"]["image_data"]
        
        # Get dimensions from the message if available
        dimensions = latest_image_message["message"]["content"].get("dimensions", {})
        width = dimensions.get("width", 0)
        height = dimensions.get("height", 0)
        
        # Assume the image data is already in base64 format
        base64_data = image_data
        
        # Return image content with dimensions
        return [
            types.ImageContent(
                type="image",
                data=base64_data,
                mimeType="image/png",
                alt_text=f"Last screenshot from remote MacOs machine"
            ),
            types.TextContent(
                type="text",
                text=f"Image dimensions: {width}x{height}"
            )
        ]
    
    # If we reach here, we couldn't find any usable screen captures
    return [types.TextContent(
        type="text",
        text="No usable screen captures found in message history. Try refreshing or waiting for updates."
    )]


def handle_remote_macos_mouse_scroll(arguments: dict[str, Any]) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Perform a mouse scroll action on a remote MacOs machine."""
    # Log this action
    log_action("remote_macos_mouse_scroll", arguments)
    
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
    # Log this action
    log_action("remote_macos_mouse_click", arguments)
    
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
    # Log this action
    log_action("remote_macos_send_keys", arguments)
    
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
    # Log this action
    log_action("remote_macos_mouse_double_click", arguments)
    
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
    """Move the mouse cursor to specified coordinates on a remote MacOs machine."""
    # Log this action
    log_action("remote_macos_mouse_move", arguments)
    
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


def handle_remote_macos_open_application(arguments: dict[str, Any]) -> List[types.TextContent]:
    """Opens/activates an application on remote MacOS and returns its PID for further interactions."""
    # Log this action
    log_action("remote_macos_open_application", arguments)
    
    # Use environment variables
    host = MACOS_HOST
    port = MACOS_PORT
    password = MACOS_PASSWORD
    username = MACOS_USERNAME
    encryption = VNC_ENCRYPTION

    identifier = arguments.get("identifier")
    if not identifier:
        raise ValueError("identifier is required")

    start_time = time.time()

    # Initialize VNC client
    vnc = VNCClient(host=host, port=port, password=password, username=username, encryption=encryption)

    # Connect to remote MacOs machine
    success, error_message = vnc.connect()
    if not success:
        error_msg = f"Failed to connect to remote MacOs machine at {host}:{port}. {error_message}"
        return [types.TextContent(type="text", text=error_msg)]

    try:
        # Send Command+Space to open Spotlight
        cmd_key = 0xffeb  # Command key
        space_key = 0x20  # Space key

        # Press Command+Space
        vnc.send_key_event(cmd_key, True)
        vnc.send_key_event(space_key, True)

        # Release Command+Space
        vnc.send_key_event(space_key, False)
        vnc.send_key_event(cmd_key, False)

        # Small delay to let Spotlight open
        time.sleep(0.5)

        # Type the application name
        vnc.send_text(identifier)

        # Small delay to let Spotlight find the app
        time.sleep(0.5)

        # Press Enter to launch
        enter_key = 0xff0d
        vnc.send_key_event(enter_key, True)
        vnc.send_key_event(enter_key, False)

        end_time = time.time()
        processing_time = round(end_time - start_time, 3)

        return [types.TextContent(
            type="text",
            text=f"Launched application: {identifier}\nProcessing time: {processing_time}s"
        )]

    finally:
        # Close VNC connection
        vnc.close()


def handle_remote_macos_mouse_drag_n_drop(arguments: dict[str, Any]) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Perform a mouse drag operation from start point and drop to end point on a remote MacOs machine."""
    # Log this action
    log_action("remote_macos_mouse_drag_n_drop", arguments)
    
    # Use environment variables
    host = MACOS_HOST
    port = MACOS_PORT
    password = MACOS_PASSWORD
    username = MACOS_USERNAME
    encryption = VNC_ENCRYPTION

    # Get required parameters from arguments
    start_x = arguments.get("start_x")
    start_y = arguments.get("start_y")
    end_x = arguments.get("end_x")
    end_y = arguments.get("end_y")
    source_width = int(arguments.get("source_width", 1366))
    source_height = int(arguments.get("source_height", 768))
    button = int(arguments.get("button", 1))
    steps = int(arguments.get("steps", 10))
    delay_ms = int(arguments.get("delay_ms", 10))

    # Validate required parameters
    if any(x is None for x in [start_x, start_y, end_x, end_y]):
        raise ValueError("start_x, start_y, end_x, and end_y coordinates are required")

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
        scaled_start_x = int((start_x / source_width) * target_width)
        scaled_start_y = int((start_y / source_height) * target_height)
        scaled_end_x = int((end_x / source_width) * target_width)
        scaled_end_y = int((end_y / source_height) * target_height)

        # Ensure coordinates are within the screen bounds
        scaled_start_x = max(0, min(scaled_start_x, target_width - 1))
        scaled_start_y = max(0, min(scaled_start_y, target_height - 1))
        scaled_end_x = max(0, min(scaled_end_x, target_width - 1))
        scaled_end_y = max(0, min(scaled_end_y, target_height - 1))

        # Calculate step sizes
        dx = (scaled_end_x - scaled_start_x) / steps
        dy = (scaled_end_y - scaled_start_y) / steps

        # Move to start position
        if not vnc.send_pointer_event(scaled_start_x, scaled_start_y, 0):
            return [types.TextContent(type="text", text="Failed to move to start position")]

        # Press button
        button_mask = 1 << (button - 1)
        if not vnc.send_pointer_event(scaled_start_x, scaled_start_y, button_mask):
            return [types.TextContent(type="text", text="Failed to press mouse button")]

        # Perform drag
        for step in range(1, steps + 1):
            current_x = int(scaled_start_x + dx * step)
            current_y = int(scaled_start_y + dy * step)
            if not vnc.send_pointer_event(current_x, current_y, button_mask):
                return [types.TextContent(type="text", text=f"Failed during drag at step {step}")]
            time.sleep(delay_ms / 1000.0)  # Convert ms to seconds

        # Release button at final position
        if not vnc.send_pointer_event(scaled_end_x, scaled_end_y, 0):
            return [types.TextContent(type="text", text="Failed to release mouse button")]

        # Prepare the response with useful details
        scale_factors = {
            "x": target_width / source_width,
            "y": target_height / source_height
        }

        return [types.TextContent(
            type="text",
            text=f"""Mouse drag (button {button}) completed:
From source ({start_x}, {start_y}) to ({end_x}, {end_y})
From target ({scaled_start_x}, {scaled_start_y}) to ({scaled_end_x}, {scaled_end_y})
Source dimensions: {source_width}x{source_height}
Target dimensions: {target_width}x{target_height}
Scale factors: {scale_factors['x']:.4f}x, {scale_factors['y']:.4f}y
Steps: {steps}
Delay: {delay_ms}ms"""
        )]

    finally:
        # Close VNC connection
        vnc.close()


def handle_remote_macos_get_screen_update(arguments: dict[str, Any], livekit_client=None) -> list[types.TextContent]:
    """Returns the consolidated list of action logs and screen updates from LiveKit client."""
    max_entries = int(arguments.get("max_entries", 10))
    
    if livekit_client is None:
        return [types.TextContent(
            type="text",
            text="Error: LiveKit client is not available. Make sure LiveKit is properly configured."
        )]
    
    # Get message history from LiveKit client
    message_history = livekit_client.get_message_history()
    
    # Get recent audit log entries
    recent_audit_log = ACTION_AUDIT_LOG.copy()
    
    # Merge the audit log with screen update messages
    consolidated_list = []
    
    # Add all audit log entries
    for entry in recent_audit_log:
        consolidated_list.append({
            "type": "action",
            "timestamp": entry["timestamp"],
            "iso_time": entry["iso_time"],
            "action": entry["action"],
            "arguments": entry["arguments"]
        })
    
    # Add all LiveKit message history
    for message in message_history:
        consolidated_list.append({
            "type": "screen_update",
            "timestamp": message["timestamp"],
            "direction": message["direction"],
            "participant": message["participant"],
            "message": message["message"]
        })
    
    # Sort the consolidated list by timestamp
    consolidated_list.sort(key=lambda x: x["timestamp"])
    
    # Limit to the most recent entries
    recent_list = consolidated_list[-max_entries:] if consolidated_list else []
    
    if not recent_list:
        return [types.TextContent(
            type="text",
            text="No history available. Keep calling this tool to wait for updates."
        )]
    
    # Check if there's been a screen update since the last action
    should_wait = False
    if ACTION_AUDIT_LOG and message_history:
        last_action_time = LAST_ACTION_TIMESTAMP
        last_message_time = max(m["timestamp"] for m in message_history) if message_history else 0
        
        # If the last action is more recent than the last screen update, suggest waiting
        if last_action_time > last_message_time:
            should_wait = True
    
    # Format the consolidated list for display
    formatted_list = json.dumps(recent_list, indent=2)
    
    wait_message = "\n\nIMPORTANT: The last action has not yet resulted in a screen update. Please wait 1 second and try again." if should_wait else ""
    
    return [types.TextContent(
        type="text",
        text=f"Consolidated action and screen update history (last {len(recent_list)} of {len(consolidated_list)} entries):\n{formatted_list}{wait_message}"
    )]