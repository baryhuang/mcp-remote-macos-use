import asyncio
import logging
import os
import time
import screen_capture
import json
import tempfile
from PIL import Image
import io

# Configure logging
logger = logging.getLogger("screen-monitor")

# Message type constant
MESSAGE_TYPE_SCREEN_UPDATE = "screen_update"
SCREEN_STREAM_TOPIC = "screen-stream"

# Fixed screen dimensions that match what capture_screen returns
SCREEN_WIDTH = 1366
SCREEN_HEIGHT = 768

class ScreenMonitor:
    def __init__(self, send_data_callback, participant_identity, debug_dir=None, max_debug_images=100):
        """
        Initialize screen monitor
        
        Args:
            send_data_callback: Async function to send data to participant
            participant_identity: Identity of the participant to send data to
            debug_dir: Directory to save debug images to
            max_debug_images: Maximum number of debug images to keep
        """
        self.send_data_callback = send_data_callback
        self.participant_identity = participant_identity
        self.debug_dir = debug_dir or os.path.expanduser("~/screen_debug")
        self.max_debug_images = max_debug_images
        self.task = None
        self.running = False
        self.room = None  # Will be set during start()
        
        # Create debug directory if it doesn't exist
        os.makedirs(self.debug_dir, exist_ok=True)
        # Create temp directory for screen captures
        self.temp_dir = os.path.join(self.debug_dir, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)

    async def start(self, room=None):
        """
        Start the screen monitoring task
        
        Args:
            room: The LiveKit room object for file streaming
        """
        if self.task and not self.task.done():
            logger.warning("Screen monitor already running")
            return
        
        self.room = room
        logger.info(f"Starting screen monitor. Debug images will be saved to {self.debug_dir} (max {self.max_debug_images} images)")
        self.running = True
        self.task = asyncio.create_task(self._monitor_screen())
        return self.task

    async def stop(self):
        """Stop the screen monitoring task"""
        if self.task and not self.task.done():
            self.running = False
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            logger.info("Screen monitor stopped")
        else:
            logger.warning("Screen monitor not running")

    async def _save_image_to_temp_file(self, image, prefix="screen"):
        """Save image to temporary file and return the path"""
        timestamp = int(time.time() * 1000)
        file_path = os.path.join(self.temp_dir, f"{prefix}_{timestamp}.jpg")
        
        try:
            # Check if image is bytes or PIL Image
            if isinstance(image, bytes):
                # Directly write bytes to file
                with open(file_path, "wb") as f:
                    f.write(image)
            else:
                # Assume it's a PIL Image
                image.save(file_path, format="JPEG", quality=75)
            
            return file_path
        except Exception as e:
            logger.error(f"Error saving image to temp file: {e}")
            raise

    async def _monitor_screen(self):
        """Monitor screen for changes and send updates to participant"""
        prev_screen = None
        
        try:
            while self.running:
                # Capture current screen
                current_screen = screen_capture.capture_screen()
                
                # Detect if screen has changed significantly
                if screen_capture.detect_screen_change(prev_screen, current_screen):
                    logger.info("Screen change detected, saving debug image and sending update")
                    
                    # Save current screen for debugging
                    debug_path = screen_capture.save_debug_image(
                        current_screen, 
                        self.debug_dir, 
                        prefix="screen_change"
                    )
                    
                    # Save previous screen too if available
                    prev_debug_path = None
                    if prev_screen:
                        prev_debug_path = screen_capture.save_debug_image(
                            prev_screen, 
                            self.debug_dir, 
                            prefix="screen_previous"
                        )
                        logger.info(f"Saved previous screen to {prev_debug_path}")
                    
                    # Clean up old images after saving new ones
                    screen_capture.cleanup_old_images(self.debug_dir, self.max_debug_images)
                    
                    # Calculate hashes of the images for debugging
                    current_hash = screen_capture.get_image_hash(current_screen)
                    prev_hash = screen_capture.get_image_hash(prev_screen)
                    
                    # Save the current screen to a temporary file for streaming
                    temp_file_path = await self._save_image_to_temp_file(current_screen)
                    
                    try:
                        # Approach 1: Use send_file
                        if self.room and hasattr(self.room.local_participant, 'send_file'):
                            # Send metadata about the screen update
                            metadata = {
                                "type": MESSAGE_TYPE_SCREEN_UPDATE,
                                "content": {
                                    "current_screen_hash": current_hash,
                                    "previous_screen_hash": prev_hash,
                                    "timestamp": time.time(),
                                    "dimensions": {
                                        "width": SCREEN_WIDTH,
                                        "height": SCREEN_HEIGHT
                                    }
                                }
                            }
                            
                            # Send metadata through data channel
                            await self.send_data_callback(metadata, self.participant_identity)
                            
                            # Send the actual image file
                            info = await self.room.local_participant.send_file(
                                file_path=temp_file_path,
                                topic=SCREEN_STREAM_TOPIC,
                                destination_identities=[self.participant_identity] if self.participant_identity else None
                            )
                            logger.info(f"Sent screen capture file with stream ID: {info.stream_id}")
                        
                        # Approach 2 (fallback): Use byte streaming if send_file is not available
                        elif self.room and hasattr(self.room.local_participant, 'stream_bytes'):
                            # Open a byte stream
                            timestamp = int(time.time() * 1000)
                            writer = await self.room.local_participant.stream_bytes(
                                name=f"screen_{timestamp}.jpg",
                                topic=SCREEN_STREAM_TOPIC,
                                destination_identities=[self.participant_identity] if self.participant_identity else None,
                                mime_type="image/png"  # Use image/png since the screen capture is in PNG format
                            )
                            
                            # Send metadata about the screen update
                            metadata = {
                                "type": MESSAGE_TYPE_SCREEN_UPDATE,
                                "content": {
                                    "current_screen_hash": current_hash,
                                    "previous_screen_hash": prev_hash,
                                    "timestamp": time.time(),
                                    "stream_id": writer.stream_id,
                                    "dimensions": {
                                        "width": SCREEN_WIDTH,
                                        "height": SCREEN_HEIGHT
                                    }
                                }
                            }
                            
                            # Send metadata through data channel
                            await self.send_data_callback(metadata, self.participant_identity)
                            
                            # Send the screen capture directly as bytes
                            await writer.write(current_screen)
                            
                            # Close the stream
                            await writer.aclose()
                            logger.info(f"Sent screen capture through byte stream with ID: {writer.stream_id}")
                        
                        # Fallback to old base64 method if file streaming is not available
                        else:
                            logger.warning("File streaming not available, falling back to base64 encoding")
                            # Convert screen image to base64 for transmission
                            image_base64 = screen_capture.encode_image_base64(current_screen)
                            
                            # Create screen update message with image data
                            screen_update = {
                                "type": MESSAGE_TYPE_SCREEN_UPDATE,
                                "content": {
                                    "current_screen_hash": current_hash,
                                    "previous_screen_hash": prev_hash,
                                    "timestamp": time.time(),
                                    "dimensions": {
                                        "width": SCREEN_WIDTH,
                                        "height": SCREEN_HEIGHT
                                    },
                                    "image_data": image_base64,
                                }
                            }
                            
                            # Send screen update to participant
                            await self.send_data_callback(screen_update, self.participant_identity)
                            logger.info(f"Sent full screen image via base64 ({len(image_base64)/1024:.1f} KB)")
                            
                    except Exception as e:
                        logger.error(f"Error sending screen capture: {e}")
                    finally:
                        # Clean up temporary file
                        try:
                            if os.path.exists(temp_file_path):
                                os.remove(temp_file_path)
                        except Exception as e:
                            logger.warning(f"Failed to remove temporary file {temp_file_path}: {e}")
                
                # Store current screen as previous for next iteration
                prev_screen = current_screen
                
                # Wait before next check, we target 2 fps
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.info("Screen monitor task cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in screen monitoring task: {e}")
            raise 