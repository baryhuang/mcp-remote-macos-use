import io
import logging
import os
import time
import hashlib
import datetime
import aiohttp
import base64
import json
from PIL import Image, ImageGrab
import numpy as np
import anthropic

# Configure logging
logger = logging.getLogger("screen-capture")

def capture_screen() -> bytes:
    """Capture a screenshot of the macOS desktop using PIL"""
    # Capture the entire screen
    screenshot = ImageGrab.grab()
    
    # Resize to standard dimensions
    resized_img = screenshot.resize((1366, 768), Image.LANCZOS)
    
    # Convert to bytes
    buffer = io.BytesIO()
    resized_img.save(buffer, format='PNG')
    return buffer.getvalue()


def detect_screen_change(prev_screen: bytes, current_screen: bytes, threshold: float = 0.01) -> bool:
    """
    Detect if the screen has changed significantly
    
    Args:
        prev_screen: Previous screenshot as bytes
        current_screen: Current screenshot as bytes
        threshold: Percentage difference threshold (0.01 = 1% change)
        
    Returns:
        bool: True if screen has changed significantly
    """
    if prev_screen is None:
        return True
    
    try:
        # Convert image bytes to numpy arrays
        prev_img = Image.open(io.BytesIO(prev_screen))
        curr_img = Image.open(io.BytesIO(current_screen))
        
        # Convert to grayscale to simplify comparison
        prev_gray = prev_img.convert('L')
        curr_gray = curr_img.convert('L')
        
        # Convert to numpy arrays
        prev_array = np.array(prev_gray)
        curr_array = np.array(curr_gray)
        
        # Calculate absolute difference
        diff = np.abs(prev_array.astype(np.int16) - curr_array.astype(np.int16))
        
        # Calculate percentage of pixels that changed significantly
        changed_pixels = np.sum(diff > 10)  # Threshold of 10 for noise reduction
        total_pixels = prev_array.size
        change_ratio = changed_pixels / total_pixels
        
        logger.debug(f"Screen change detection: {change_ratio:.4f} ratio of pixels changed")
        
        # Return True if change exceeds threshold
        return change_ratio > threshold
    except Exception as e:
        logger.error(f"Error in screen change detection: {e}")
        return True  # Default to True on error


def save_debug_image(image_data: bytes, debug_dir: str, prefix: str = "screen") -> str:
    """Save an image to the debug directory with timestamp"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    debug_path = os.path.join(debug_dir, f"{prefix}_{timestamp}.png")
    
    # Ensure the debug directory exists
    os.makedirs(debug_dir, exist_ok=True)
    
    with open(debug_path, "wb") as f:
        f.write(image_data)
    
    return debug_path


def cleanup_old_images(debug_dir: str, max_images: int = 100):
    """Clean up old debug images, keeping only the most recent ones"""
    try:
        image_files = []
        # Get all png files in the debug directory
        for file in os.listdir(debug_dir):
            if file.endswith(".png"):
                file_path = os.path.join(debug_dir, file)
                image_files.append((file_path, os.path.getmtime(file_path)))
        
        # Sort by modification time (oldest first)
        image_files.sort(key=lambda x: x[1])
        
        # If we have more than max_images, remove the oldest ones
        if len(image_files) > max_images:
            files_to_remove = image_files[:(len(image_files) - max_images)]
            for file_path, _ in files_to_remove:
                os.remove(file_path)
                logger.debug(f"Removed old debug image: {os.path.basename(file_path)}")
            
            logger.info(f"Cleaned up {len(files_to_remove)} old debug images, keeping {max_images} most recent")
    except Exception as e:
        logger.error(f"Error cleaning up old debug images: {e}")


def get_image_hash(image_data: bytes) -> str:
    """Calculate MD5 hash of image data"""
    return hashlib.md5(image_data).hexdigest() if image_data else "None"


def encode_image_base64(image_data: bytes) -> str:
    """
    Encode image data as base64 string for transmission
    
    Args:
        image_data: Image data as bytes
        
    Returns:
        str: Base64 encoded string representation of the image
    """
    if not image_data:
        return None
    return base64.b64encode(image_data).decode('utf-8')


async def find_screen_differences_with_claude(prev_screen: bytes, current_screen: bytes, api_key: str = None, model: str = "claude-3-7-sonnet-20250219") -> dict:
    """
    Send two screen images to Claude API to get accurate coordinates of the differences
    
    Args:
        prev_screen: Previous screenshot as bytes
        current_screen: Current screenshot as bytes
        api_key: Anthropic API key (will use environment variable if not provided)
        model: Claude model to use (defaults to Claude 3.7 Sonnet)
        
    Returns:
        dict: Coordinates and descriptions of differences found
    """
    if prev_screen is None or current_screen is None:
        logger.warning("Cannot compare screens: one or both images are missing")
        return {"success": False, "error": "Missing images"}
    
    # Get API key from environment if not provided
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("No Anthropic API key found")
        return {"success": False, "error": "No API key"}
    
    try:
        # Convert images to base64
        prev_img_b64 = base64.b64encode(prev_screen).decode('utf-8')
        curr_img_b64 = base64.b64encode(current_screen).decode('utf-8')
        
        # Create Anthropic client
        client = anthropic.AsyncAnthropic(api_key=api_key)
        
        # Create the message request
        message = await client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": prev_img_b64
                            }
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": curr_img_b64
                            }
                        },
                        {
                            "type": "text",
                            "text": """
                            Compare these two screenshots and identify the areas where they differ.
                            
                            Please describe:
                            1. What specific elements have changed between the two screenshots
                            2. Where these changes are located (approximate coordinates or regions)
                            3. How significant each change is (minor or major difference)
                            
                            Be specific about what UI elements changed, what text content changed, or what visual elements appeared/disappeared.
                            """
                        }
                    ]
                }
            ]
        )
        
        # Log successful response
        logger.info(f"Claude API response received with content")
        
        # Return the response with success flag
        result = message.model_dump()
        result["success"] = True
        return result
    except Exception as e:
        logger.error(f"Error using Claude for image comparison: {e}")
        return {"success": False, "error": str(e)}

async def find_screen_differences_with_function_calling(prev_screen: bytes, current_screen: bytes, api_key: str = None, model: str = "claude-3-7-sonnet-20250219") -> dict:
    """
    Send two screen images to Claude API using function calling to get structured coordinates data
    of the differences between screens
    
    Args:
        prev_screen: Previous screenshot as bytes
        current_screen: Current screenshot as bytes
        api_key: Anthropic API key (will use environment variable if not provided)
        model: Claude model to use (defaults to Claude 3.7 Sonnet)
        
    Returns:
        dict: Structured coordinates and descriptions of differences found
    """
    if prev_screen is None or current_screen is None:
        logger.warning("Cannot compare screens: one or both images are missing")
        return {"success": False, "error": "Missing images"}
    
    # Get API key from environment if not provided
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("No Anthropic API key found")
        return {"success": False, "error": "No API key"}
    
    try:
        # Convert images to base64
        prev_img_b64 = base64.b64encode(prev_screen).decode('utf-8')
        curr_img_b64 = base64.b64encode(current_screen).decode('utf-8')
        
        # Create Anthropic client
        client = anthropic.AsyncAnthropic(api_key=api_key)
        
        # Define the tool schema for structured screen difference output
        screen_diff_tool = {
            "name": "identify_screen_differences",
            "description": "Identify and report differences between two screenshots with precise coordinates",
            "input_schema": {
                "type": "object",
                "properties": {
                    "previous_screen_description": {
                        "type": "string",
                        "description": "Detailed description of what's shown in the previous screenshot"
                    },
                    "current_screen_description": {
                        "type": "string",
                        "description": "Detailed description of what's shown in the current screenshot"
                    },
                    "changes": {
                        "type": "array",
                        "description": "List of all visual changes detected between the screenshots",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {
                                    "type": "string",
                                    "description": "Description of what changed (text content, UI element, etc.)"
                                },
                                "coordinates": {
                                    "type": "object",
                                    "description": "Coordinates of the change area (in pixels)",
                                    "properties": {
                                        "x1": {"type": "integer", "description": "Top-left x coordinate"},
                                        "y1": {"type": "integer", "description": "Top-left y coordinate"},
                                        "x2": {"type": "integer", "description": "Bottom-right x coordinate"},
                                        "y2": {"type": "integer", "description": "Bottom-right y coordinate"}
                                    },
                                    "required": ["x1", "y1", "x2", "y2"]
                                },
                                "significance": {
                                    "type": "string",
                                    "description": "How significant the change is",
                                    "enum": ["minor", "moderate", "major"]
                                }
                            },
                            "required": ["description", "coordinates", "significance"]
                        }
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of the overall changes between the screenshots"
                    }
                },
                "required": ["previous_screen_description", "current_screen_description", "changes", "summary"]
            }
        }
        
        # Create the message request with function calling
        message = await client.messages.create(
            model=model,
            max_tokens=1024,
            tools=[screen_diff_tool],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": prev_img_b64
                            }
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": curr_img_b64
                            }
                        },
                        {
                            "type": "text",
                            "text": """
                            Compare these two screenshots and identify all areas where they differ.
                            Use the provided tool to return the exact coordinates of changes.
                            
                            For each changed area:
                            1. Provide precise coordinates (x1, y1, x2, y2) defining the bounding box
                            2. Describe what specifically changed (text, UI element, color, etc.)
                            3. Rate the significance as minor, moderate, or major
                            
                            Be comprehensive in identifying all changes, no matter how small.
                            """
                        }
                    ]
                }
            ]
        )
        
        # Get a dict representation of the message for easier access
        message_dict = message.model_dump()
        
        # Look for tool use in the response content
        structured_differences = None
        
        # Check if content is present
        if message_dict.get('content') and isinstance(message_dict['content'], list):
            # Anthropic may return tool outputs in the content list
            for content_block in message_dict['content']:
                # Check if this is a tool use block
                if content_block.get('type') == 'tool_use' and content_block.get('name') == 'identify_screen_differences':
                    try:
                        # Extract the tool input
                        structured_differences = content_block.get('input', {})
                        logger.info(f"Received structured screen differences with {len(structured_differences.get('changes', []))} changes")
                    except Exception as extract_error:
                        logger.error(f"Error extracting tool data: {extract_error}")
        
        # If we couldn't find tool data, try to parse it from the text content
        if structured_differences is None:
            # Try to parse JSON from the text content
            try:
                # Extract any text content
                text_content = ""
                if message_dict.get('content') and isinstance(message_dict['content'], list):
                    for block in message_dict['content']:
                        if block.get('type') == 'text':
                            text_content += block.get('text', '')
                
                # Look for JSON in the text content
                import re
                json_match = re.search(r'```json\s*(.*?)\s*```', text_content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                    structured_differences = json.loads(json_str)
                    logger.info(f"Extracted JSON from text content with {len(structured_differences.get('changes', []))} changes")
            except Exception as parse_error:
                logger.error(f"Error parsing JSON from text content: {parse_error}")
        
        # Create result with the structured differences and original message
        result = {
            "success": True,
            "content": message_dict.get('content'),
            "structured_differences": structured_differences,
            # "raw_response": message_dict
        }
        
        return result
    except Exception as e:
        logger.error(f"Error using Claude with function calling for image comparison: {e}")
        return {"success": False, "error": str(e)}

async def test_claude_integration(path1: str, path2: str, api_key: str = None, model: str = "claude-3-7-sonnet-20250219", use_function_calling: bool = False):
    """
    Test function for the Claude API integration
    
    Args:
        path1: Path to first image file
        path2: Path to second image file
        api_key: Optional API key
        model: Claude model to use (defaults to Claude 3.7 Sonnet)
        use_function_calling: Whether to use function calling for structured coordinates output
    """
    # Load the two images
    with open(path1, 'rb') as f1, open(path2, 'rb') as f2:
        img1 = f1.read()
        img2 = f2.read()
    
    # Call the Claude API function
    if use_function_calling:
        result = await find_screen_differences_with_function_calling(img1, img2, api_key, model)
    else:
        result = await find_screen_differences_with_claude(img1, img2, api_key, model)
    
    # Print the result
    print(f"Claude API result: {json.dumps(result, indent=2)}")
    
    return result

# Simple command-line test if run directly
if __name__ == "__main__":
    import sys
    import asyncio
    
    if len(sys.argv) < 3:
        print("Usage: python screen_capture.py image1.png image2.png [api_key] [model] [use_function_calling]")
        sys.exit(1)
    
    api_key = sys.argv[3] if len(sys.argv) > 3 else None
    model = sys.argv[4] if len(sys.argv) > 4 else "claude-3-7-sonnet-20250219"
    use_function_calling = sys.argv[5] == "True" if len(sys.argv) > 5 else False
    
    # Run the test
    asyncio.run(test_claude_integration(sys.argv[1], sys.argv[2], api_key, model, use_function_calling)) 