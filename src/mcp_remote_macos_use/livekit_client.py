import logging
import os
from typing import Optional, Callable, Dict, Any, List, Deque
import asyncio
import json
import time
from collections import deque
from livekit.rtc import Room, RemoteParticipant, DataPacketKind
import tempfile
import shutil

logger = logging.getLogger('livekit_client')

# Message types for data channel communication
DATA_CHANNEL_TOPIC = "macos-remote-control"
SCREEN_STREAM_TOPIC = "screen-stream"
MESSAGE_TYPE_HANDSHAKE_REQUEST = "handshake_request"
MESSAGE_TYPE_HANDSHAKE_RESPONSE = "handshake_response"
MESSAGE_TYPE_COMMAND = "command"
MESSAGE_TYPE_RESULT = "result"
MESSAGE_TYPE_SCREEN_UPDATE = "screen_update"

# Maximum number of messages to store in history
MAX_MESSAGE_HISTORY = 100  # 5 fps * 10 seconds
DEFAULT_SCREEN_DIR = os.path.expanduser("~/screen_captures")

class LiveKitClient:
    def __init__(self, screen_capture_dir=None):
        self.room: Optional[Room] = None
        self._message_handlers: Dict[str, Callable] = {}
        self._stream_handlers: Dict[str, Callable] = {}
        self._is_connected: bool = False
        self._remote_participant: Optional[RemoteParticipant] = None
        # Message history circular buffer
        self._message_history: Deque[Dict[str, Any]] = deque(maxlen=MAX_MESSAGE_HISTORY)
        # Active stream tasks
        self._active_stream_tasks = []
        # Directory to save screen captures
        self.screen_capture_dir = screen_capture_dir or DEFAULT_SCREEN_DIR
        os.makedirs(self.screen_capture_dir, exist_ok=True)
        
        # LiveKit configuration - only URL needed for client
        self.url = os.getenv('LIVEKIT_URL')
        
        if not self.url:
            logger.warning("LiveKit URL environment variable not configured")
            return
            
        logger.info("LiveKit client configuration loaded")

    def register_message_handler(self, message_type: str, handler: Callable):
        """Register a handler for a specific message type"""
        self._message_handlers[message_type] = handler
        logger.info(f"Registered handler for message type: {message_type}")

    def register_stream_handler(self, topic: str, handler: Callable):
        """Register a handler for a specific stream topic"""
        self._stream_handlers[topic] = handler
        logger.info(f"Registered handler for stream topic: {topic}")

    def get_message_history(self) -> List[Dict[str, Any]]:
        """Get the message history as a list"""
        return list(self._message_history)

    def get_screen_captures(self) -> List[Dict[str, Any]]:
        """Get only screen capture messages from the history"""
        return [entry for entry in self._message_history if entry.get("is_screen_capture", False)]

    def clear_message_history(self):
        """Clear the message history"""
        self._message_history.clear()
        logger.info("Message history cleared")

    def _store_message(self, message: Dict[str, Any], direction: str = "received", participant_identity: str = None):
        """Store a message in the history with metadata"""
        history_entry = {
            "timestamp": time.time(),
            "direction": direction,  # "received" or "sent"
            "participant": participant_identity,
            "message": message
        }
        
        # For screen updates, add direct screen info for easier UI access
        if message.get("type") == MESSAGE_TYPE_SCREEN_UPDATE and "content" in message:
            # Add special flags to make it easier to find screen captures in history
            history_entry["is_screen_capture"] = True
            if "file_path" in message["content"]:
                history_entry["screen_path"] = message["content"]["file_path"]
                logger.info(f"Added screen capture to message history: {message['content']['file_path']}")
        
        self._message_history.append(history_entry)
        logger.debug(f"Stored message in history: {direction} from {participant_identity}")
        
        # Log total message count and screen capture count periodically
        if len(self._message_history) % 10 == 0:
            screen_captures = sum(1 for entry in self._message_history if entry.get("is_screen_capture", False))
            logger.info(f"Message history: {len(self._message_history)} total messages, {screen_captures} screen captures")

    async def handle_data_message(self, payload: bytes, participant: RemoteParticipant, kind: Any, topic: str = None):
        """Handle incoming data messages"""
        if topic != DATA_CHANNEL_TOPIC:
            return
        
        # Log raw payload for debugging
        logger.info(f"Raw payload from {participant.identity} (len={len(payload) if payload else 'N/A'})")
            
        try:
            # Parse JSON data
            data = json.loads(payload.decode('utf-8'))
            logger.info(f"Received data from {participant.identity}: {data}")
            
            # Store the message in history
            self._store_message(data, "received", participant.identity)
            
            message_type = data.get("type")
            message_content = data.get("content", {})
            
            # Handle different message types
            if message_type == MESSAGE_TYPE_HANDSHAKE_REQUEST:
                # Store reference to remote participant for future communication
                self._remote_participant = participant
                
                # Respond to handshake request using an async task
                response = {
                    "type": MESSAGE_TYPE_HANDSHAKE_RESPONSE,
                    "content": {
                        "status": "connected",
                        "server_time": time.time(),
                        "message": "MCP Server connected"
                    }
                }
                asyncio.create_task(self.send_data(response, participant.identity))
                logger.info(f"Handshake response queued for {participant.identity}")
                
            elif message_type == MESSAGE_TYPE_RESULT:
                # Process result from a command
                logger.info(f"Received result: {message_content}")
                
                # Call appropriate handler if registered
                if message_type in self._message_handlers:
                    await self._message_handlers[message_type](message_content, participant)
            
            # Call type-specific handler if registered
            if message_type in self._message_handlers:
                await self._message_handlers[message_type](data, participant)
                
        except json.JSONDecodeError:
            logger.error(f"Received invalid JSON data: {payload.decode('utf-8', errors='replace')}")
        except Exception as e:
            logger.error(f"Error handling data message: {str(e)}")

    async def _default_screen_stream_handler(self, reader, participant_identity, info):
        """Default handler for screen capture streams"""
        try:
            logger.info(f"Handling screen capture from {participant_identity}: {info.name}")
            
            # Create a timestamp-based filename
            timestamp = int(time.time() * 1000)
            
            # Get the file extension from the original name or default to jpg
            original_name = info.name
            file_extension = os.path.splitext(original_name)[1] if original_name else ".png" 
            if not file_extension:
                # Default to PNG if no extension found (matches what capture_screen returns)
                file_extension = ".png"
                
            # Create filename with appropriate extension
            filename = f"screen_{timestamp}{file_extension}"
            output_path = os.path.join(self.screen_capture_dir, filename)
            
            # Create a temporary file to receive the data
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_path = temp_file.name
                
                # Read the stream in chunks and write to temp file
                async for chunk in reader:
                    temp_file.write(chunk)
            
            # Move the temp file to the final location
            shutil.move(temp_path, output_path)
            logger.info(f"Saved screen capture to {output_path}")
            
            # Get stream ID safely
            stream_id = None
            if hasattr(info, 'id'):
                stream_id = info.id
            elif hasattr(info, 'stream_id'):
                stream_id = info.stream_id
            elif hasattr(reader, 'stream_id'):
                stream_id = reader.stream_id
            
            # Trigger any registered message handlers for screen update
            metadata = {
                "type": MESSAGE_TYPE_SCREEN_UPDATE,
                "content": {
                    "timestamp": time.time(),
                    "file_path": output_path,
                    "stream_id": stream_id,
                    "name": info.name,
                    "mime_type": getattr(info, "mime_type", "image/png")
                }
            }
            
            # Store the screen capture in message history
            self._store_message(metadata, "received", participant_identity)
            
            # Call the screen update handler if registered
            if MESSAGE_TYPE_SCREEN_UPDATE in self._message_handlers:
                participant = None
                # Try to find the participant by identity
                if self.room and participant_identity:
                    for p in self.room.participants.values():
                        if p.identity == participant_identity:
                            participant = p
                            break
                
                await self._message_handlers[MESSAGE_TYPE_SCREEN_UPDATE](metadata, participant)
            
            return output_path
        except Exception as e:
            logger.error(f"Error handling screen capture: {e}")
            # Log all available attributes for debugging
            try:
                logger.error(f"Available info attributes: {dir(info)}")
                if hasattr(reader, 'info'):
                    logger.error(f"Available reader.info attributes: {dir(reader.info)}")
                logger.error(f"Available reader attributes: {dir(reader)}")
            except Exception as debug_err:
                logger.error(f"Error while debugging: {debug_err}")
            return None

    async def _handle_byte_stream(self, reader, participant_identity):
        """Internal handler for byte streams"""
        try:
            info = reader.info
            topic = info.topic
            
            # Log stream information for debugging
            stream_id = None
            if hasattr(info, 'id'):
                stream_id = info.id
            elif hasattr(info, 'stream_id'):
                stream_id = info.stream_id
            elif hasattr(reader, 'stream_id'):
                stream_id = reader.stream_id
                
            stream_id_str = stream_id if stream_id else "unknown"
            logger.info(f"Receiving byte stream: {info.name} from {participant_identity}")
            logger.info(f"  Topic: {topic}, Stream ID: {stream_id_str}")
            
            # If stream is a screen capture
            if topic == SCREEN_STREAM_TOPIC:
                # Use default handler if no custom handler registered
                if SCREEN_STREAM_TOPIC not in self._stream_handlers:
                    await self._default_screen_stream_handler(reader, participant_identity, info)
                else:
                    await self._stream_handlers[SCREEN_STREAM_TOPIC](reader, participant_identity, info)
            # If we have a registered handler for this topic, call it
            elif topic in self._stream_handlers:
                await self._stream_handlers[topic](reader, participant_identity, info)
            else:
                # Default handling - just read the stream completely
                data = await reader.read_all()
                logger.info(f"Received stream data: {len(data)} bytes, but no handler registered for topic: {topic}")
                
        except Exception as e:
            logger.error(f"Error handling byte stream: {e}")
            # Log more details for debugging
            try:
                if 'reader' in locals() and reader:
                    logger.error(f"Reader attributes: {dir(reader)}")
                    if hasattr(reader, 'info'):
                        logger.error(f"Reader.info attributes: {dir(reader.info)}")
                if 'info' in locals() and info:
                    logger.error(f"Info attributes: {dir(info)}")
            except Exception as debug_err:
                logger.error(f"Error during debug logging: {debug_err}")

    async def start(self, room_name: str, token: str) -> bool:
        """Start LiveKit connection"""
        if not all([self.url, room_name, token]):
            logger.error("Missing required connection parameters")
            return False

        try:
            self.room = Room()
            
            @self.room.on("participant_connected")
            def on_participant_connected(participant: RemoteParticipant):
                logger.info(f"Participant connected: {participant.identity} ({participant.sid})")
                
                # Send handshake request to the newly connected participant
                asyncio.create_task(self.send_handshake_request(participant.identity))

            @self.room.on("participant_disconnected")
            def on_participant_disconnected(participant: RemoteParticipant):
                logger.info(f"Participant disconnected: {participant.identity} ({participant.sid})")
                if self._remote_participant and participant.identity == self._remote_participant.identity:
                    self._remote_participant = None

            @self.room.on("data_received")
            def on_data_received(data, *args, **kwargs):
                # Log raw data received event for debugging
                logger.info(f"RAW DATA RECEIVED: {data}")
                
                try:
                    # Handle DataPacket object directly
                    payload = None
                    participant = None
                    kind = None
                    topic = None
                    
                    # Check if we received a DataPacket object
                    if hasattr(data, 'data') and hasattr(data, 'participant') and hasattr(data, 'topic'):
                        # This appears to be the new format with DataPacket
                        payload = data.data
                        participant = data.participant
                        kind = getattr(data, 'kind', None)
                        topic = data.topic
                        logger.info(f"Extracted from DataPacket: participant={participant.identity if participant else 'None'}, topic={topic}")
                    else:
                        # Try to extract from other formats
                        payload = data
                        
                        # Try to extract participant and other details from args or kwargs
                        if args and len(args) >= 1 and hasattr(args[0], 'identity'):
                            participant = args[0]
                        elif 'participant' in kwargs:
                            participant = kwargs['participant']
                        
                        if args and len(args) >= 2:
                            kind = args[1]
                        elif 'kind' in kwargs:
                            kind = kwargs['kind']
                        
                        if args and len(args) >= 3:
                            topic = args[2]
                        elif 'topic' in kwargs:
                            topic = kwargs['topic']
                        
                        # If we have a participant identity but no participant object
                        if not participant and 'participant_identity' in kwargs:
                            # Try to find the participant by identity
                            identity = kwargs['participant_identity']
                            for p in self.room.participants.values():
                                if p.identity == identity:
                                    participant = p
                                    break
                        
                        # Extract topic from complex data structure if needed
                        if hasattr(data, 'user'):
                            if hasattr(data.user, 'topic'):
                                topic = data.user.topic
                            
                            # Extract payload if needed
                            if hasattr(data.user, 'data'):
                                if hasattr(data.user.data, 'data'):
                                    payload = data.user.data.data
                    
                    # Process the data if we have enough information
                    if payload and participant and topic == DATA_CHANNEL_TOPIC:
                        # Process the binary data
                        if isinstance(payload, bytes):
                            try:
                                # Decode JSON data
                                message_str = payload.decode('utf-8')
                                message_data = json.loads(message_str)
                                logger.info(f"Decoded message from {participant.identity}: {message_data}")
                                
                                # Store the message in history
                                self._store_message(message_data, "received", participant.identity)
                                
                                # Store the remote participant for future communication
                                self._remote_participant = participant
                                
                                # Process different message types
                                message_type = message_data.get('type')
                                message_content = message_data.get('content', {})
                                
                                if message_type == MESSAGE_TYPE_HANDSHAKE_REQUEST:
                                    logger.info(f"Received handshake request from {participant.identity}")
                                    self._remote_participant = participant
                                    
                                    # Respond to handshake request using an async task
                                    response = {
                                        "type": MESSAGE_TYPE_HANDSHAKE_RESPONSE,
                                        "content": {
                                            "status": "connected",
                                            "server_time": time.time(),
                                            "message": "MCP Server connected"
                                        }
                                    }
                                    asyncio.create_task(self.send_data(response, participant.identity))
                                    logger.info(f"Handshake response queued for {participant.identity}")
                                
                                elif message_type == MESSAGE_TYPE_HANDSHAKE_RESPONSE:
                                    logger.info(f"Handshake completed with {participant.identity}")
                                
                                elif message_type == MESSAGE_TYPE_RESULT:
                                    logger.info(f"Received command result: {message_content}")
                                    
                                    # Call appropriate handler if registered
                                    if message_type in self._message_handlers:
                                        asyncio.create_task(self._message_handlers[message_type](message_content, participant))
                                
                                # Call type-specific handler if registered
                                if message_type in self._message_handlers:
                                    asyncio.create_task(self._message_handlers[message_type](message_data, participant))
                                    
                            except json.JSONDecodeError:
                                logger.error(f"Invalid JSON data: {payload.decode('utf-8', errors='replace')}")
                            except UnicodeDecodeError:
                                logger.error(f"Cannot decode binary data as UTF-8, raw length: {len(payload)}")
                        else:
                            logger.warning(f"Payload is not bytes: {type(payload)}")
                    elif not participant:
                        logger.error(f"No participant found in data: {data}")
                    elif not payload:
                        logger.error(f"No payload found in data: {data}")
                    elif topic != DATA_CHANNEL_TOPIC:
                        logger.debug(f"Ignoring message on topic {topic} from {participant.identity if participant else 'unknown'}")
                except Exception as e:
                    logger.error(f"Error processing data_received event: {str(e)}")

            # Register byte stream handler wrapper
            def on_byte_stream(reader, participant_identity):
                task = asyncio.create_task(self._handle_byte_stream(reader, participant_identity))
                self._active_stream_tasks.append(task)
                task.add_done_callback(lambda t: self._active_stream_tasks.remove(t) if t in self._active_stream_tasks else None)
            
            # Register stream handler for screen captures
            self.room.register_byte_stream_handler(SCREEN_STREAM_TOPIC, on_byte_stream)
            logger.info(f"Registered byte stream handler for topic: {SCREEN_STREAM_TOPIC}")

            # Connect to the room
            await self.room.connect(self.url, token)
            self._is_connected = True
            logger.info(f"Connected to LiveKit room: {room_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to start LiveKit: {str(e)}")
            return False

    async def send_handshake_request(self, participant_identity: str):
        """Send a handshake request to a participant"""
        handshake_data = {
            "type": MESSAGE_TYPE_HANDSHAKE_REQUEST,
            "content": {
                "client_version": "1.0.0",
                "client_id": "mcp-server",
                "capabilities": ["command_execution"]
            }
        }
        
        await self.send_data(handshake_data, participant_identity)
        logger.info(f"Sent handshake request to {participant_identity}")

    async def send_command(self, command: str, command_id: str = None) -> bool:
        """Send a command to the remote macOS agent"""
        if not self._is_connected or not self._remote_participant:
            logger.error("Cannot send command: not connected or no remote participant")
            return False
            
        command_data = {
            "type": MESSAGE_TYPE_COMMAND,
            "content": {
                "command": command,
                "id": command_id or f"cmd-{int(time.time())}"
            }
        }
        
        return await self.send_data(command_data, self._remote_participant.identity)

    async def send_data(self, data: Dict[str, Any], participant_identity: str = None) -> bool:
        """Send data to a specific participant or broadcast to all"""
        if not self.room or not self._is_connected:
            logger.error("Cannot send data: not connected")
            return False

        try:
            # Store the message in history before sending
            self._store_message(data, "sent", participant_identity)
            
            # Encode data as JSON string, then to bytes
            payload = json.dumps(data).encode('utf-8')
            
            options = {}
            
            # Set the topic for the data channel
            options["topic"] = DATA_CHANNEL_TOPIC
            
            # If participant specified, send only to them
            if participant_identity:
                options["destination_identities"] = [participant_identity]
                
            await self.room.local_participant.publish_data(payload, **options)
            logger.debug(f"Sent data: {data}")
            return True
        except Exception as e:
            logger.error(f"Failed to send data: {str(e)}")
            return False

    async def stop(self):
        """Stop LiveKit connection"""
        if self.room:
            try:
                # Cancel any active stream tasks
                for task in self._active_stream_tasks:
                    if not task.done():
                        task.cancel()
                
                # Wait for all tasks to complete
                if self._active_stream_tasks:
                    await asyncio.gather(*self._active_stream_tasks, return_exceptions=True)
                
                # Disconnect from room
                await self.room.disconnect()
                self._is_connected = False
                self._remote_participant = None
                logger.info("Disconnected from LiveKit room")
            except Exception as e:
                logger.error(f"Error disconnecting from LiveKit: {str(e)}")
                
    @property
    def is_connected(self) -> bool:
        """Check if connected to LiveKit room"""
        return self._is_connected
        
    @property
    def has_remote_participant(self) -> bool:
        """Check if there's a remote participant connected"""
        return self._remote_participant is not None 