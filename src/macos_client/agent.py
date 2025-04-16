import logging
import os
import uuid
from dotenv import load_dotenv
import json
import asyncio
import time
import atexit
import sys
import datetime

from livekit import api
from livekit.api import VideoGrants
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
)

# Import from local modules
import screen_capture
import screen_monitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("data-channel-agent")

# Load environment variables from .env file
load_dotenv()

# Required environment variables
required_env_vars = [
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "LIVEKIT_URL",
]

# Check that all required environment variables are set
missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    logger.error("Please set these variables in your .env file or environment")
    sys.exit(1)

# Topic used for data channel messages
DATA_CHANNEL_TOPIC = "macos-remote-control"
SCREEN_STREAM_TOPIC = "screen-stream"

# Message types for handshaking and communication
MESSAGE_TYPE_HANDSHAKE_REQUEST = "handshake_request"
MESSAGE_TYPE_HANDSHAKE_RESPONSE = "handshake_response"
MESSAGE_TYPE_COMMAND = "command"
MESSAGE_TYPE_RESULT = "result"
MESSAGE_TYPE_SCREEN_UPDATE = "screen_update"

# Path to store token information
TOKEN_DIR = os.path.expanduser("~/mcp_tokens")
CURRENT_TOKEN_FILE = os.path.join(TOKEN_DIR, "current_session.json")

# Global variable to store current room and token information
current_token_info = None

def generate_and_save_tokens(room_name: str) -> dict:
    """Generate tokens for both the agent and server, then save them to disk"""
    logger.info(f"Generating tokens for room: {room_name}")
    
    # Ensure token directory exists
    os.makedirs(TOKEN_DIR, exist_ok=True)
    
    # Generate tokens
    agent_token = api.AccessToken(
        api_key=os.getenv("LIVEKIT_API_KEY"),
        api_secret=os.getenv("LIVEKIT_API_SECRET")
    ).with_identity("macos-agent") \
     .with_name("MacOS Agent") \
     .with_grants(api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True
     )).to_jwt()
    
    server_token = api.AccessToken(
        api_key=os.getenv("LIVEKIT_API_KEY"),
        api_secret=os.getenv("LIVEKIT_API_SECRET")
    ).with_identity("mcp-server") \
     .with_name("MCP Server") \
     .with_grants(api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True
     )).to_jwt()
    
    # Create token information object
    token_info = {
        "room_name": room_name,
        "server_url": os.getenv("LIVEKIT_URL"),
        "agent_token": agent_token,
        "server_token": server_token,
        "generated_at": int(time.time()),
        "expires_at": int(time.time() + 3600)  # 1 hour expiry
    }
    
    # Save token information to file
    try:
        with open(CURRENT_TOKEN_FILE, "w") as f:
            json.dump(token_info, f, indent=2)
        
        logger.info(f"Tokens saved to {CURRENT_TOKEN_FILE}")
        
        # Set permissions to ensure file is readable
        os.chmod(CURRENT_TOKEN_FILE, 0o644)
        
        return token_info
    except Exception as e:
        logger.error(f"Failed to save tokens: {e}")
        raise


async def cleanup_room(room_name: str):
    """Clean up and delete the room"""
    try:
        api_client = api.LiveKitAPI(
            os.getenv("LIVEKIT_URL"),
            os.getenv("LIVEKIT_API_KEY"),
            os.getenv("LIVEKIT_API_SECRET"),
        )
        await api_client.room.delete_room(api.DeleteRoomRequest(
            room=room_name,
        ))
        logger.info(f"Successfully deleted room {room_name}")
        
        # Clean up token file
        if os.path.exists(CURRENT_TOKEN_FILE):
            os.remove(CURRENT_TOKEN_FILE)
            logger.info(f"Removed token file {CURRENT_TOKEN_FILE}")
    except Exception as e:
        logger.warning(f"Failed to delete room {room_name}: {e}")


# Generate tokens at application startup
def initialize_tokens():
    global current_token_info
    
    logger.info("Initializing tokens for macOS remote agent...")
    
    # Generate a unique room name
    room_name = f"macos-remote-{uuid.uuid4()}"
    logger.info(f"Using room name: {room_name}")
    
    # Generate tokens
    current_token_info = generate_and_save_tokens(room_name)
    
    # Register cleanup for program exit
    atexit.register(lambda: asyncio.run(cleanup_room(room_name)))
    
    logger.info(f"Token initialization complete. Room {room_name} is ready for connections.")
    logger.info(f"Tokens will expire at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_token_info['expires_at']))}")
    
    return current_token_info


async def entrypoint(ctx: JobContext):
    global current_token_info
    
    # Check if we already have valid tokens
    if not current_token_info:
        logger.error("No valid tokens available. This shouldn't happen as tokens should be initialized at startup.")
        # As a fallback, generate them now, but this isn't ideal
        current_token_info = initialize_tokens()
    
    room_name = current_token_info["room_name"]
    
    # Register cleanup for job shutdown
    ctx.add_shutdown_callback(lambda: cleanup_room(room_name))

    # # Create system message for our agent
    # system_message = (
    #     "You are a remote macOS assistant that can execute commands on a remote Mac. "
    #     "You will receive commands through the data channel and send results back."
    # )
    
    # logger.info(f"Using system message: {system_message}")
    
    # # Create the initial context with the system message
    # initial_ctx = llm.ChatContext().append(
    #     role="system",
    #     text=system_message,
    # )

    logger.info(f"Connecting to room {room_name}")
    
    # Connect to the LiveKit room - we don't need to set room.name as it's set via the token
    await ctx.connect(
        auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL
    )

    # Wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"Connected with participant {participant.identity}")

    # Initialize the participants messaging system
    transcript = []
    
    # Text encoder/decoder for data channel
    encoder = lambda data: json.dumps(data).encode('utf-8')
    decoder = lambda payload: json.loads(payload.decode('utf-8'))
    
    # Define async function to process data
    async def process_data(payload, participant_identity, topic=None):
        if topic == DATA_CHANNEL_TOPIC:
            try:
                data = decoder(payload)
                logger.info(f"Received data from {participant_identity}: {data}")
                
                message_type = data.get("type")
                message_content = data.get("content", {})
                
                # Handle different message types
                if message_type == MESSAGE_TYPE_HANDSHAKE_REQUEST:
                    # Respond to handshake request
                    response = {
                        "type": MESSAGE_TYPE_HANDSHAKE_RESPONSE,
                        "content": {
                            "status": "connected",
                            "server_time": time.time(),
                            "message": "Connection established"
                        }
                    }
                    await send_data_to_participant(response, participant_identity)
                    logger.info(f"Handshake completed with {participant_identity}")
                
                elif message_type == MESSAGE_TYPE_COMMAND:
                    # Process command and send back results
                    command = message_content.get("command")
                    if command:
                        # Store the command in transcript
                        transcript.append({"role": "user", "content": command})
                        
                        # Simulate command execution (in real implementation, this would execute AppleScript)
                        result = f"Executed command: {command}"
                        
                        # Store the result in transcript
                        transcript.append({"role": "assistant", "content": result})
                        
                        # Send result back to participant
                        response = {
                            "type": MESSAGE_TYPE_RESULT,
                            "content": {
                                "result": result,
                                "status": "success"
                            }
                        }
                        await send_data_to_participant(response, participant_identity)
            
            except Exception as e:
                logger.error(f"Error processing data: {e}")
                # Send error response
                error_response = {
                    "type": "error",
                    "content": {"message": f"Error processing request: {str(e)}"}
                }
                await send_data_to_participant(error_response, participant_identity)
    
    # Handle data received from the client with non-async callback that creates an async task
    @ctx.room.on("data_received")
    def on_data_received(payload, participant_identity=None, topic=None):
        # Create an asyncio task to handle the async processing
        asyncio.create_task(process_data(payload, participant_identity, topic))
    
    # Helper function to send data to a participant
    async def send_data_to_participant(data, participant_identity=None):
        payload = encoder(data)
        if participant_identity:
            # Send to a specific participant
            await ctx.room.local_participant.publish_data(
                payload, 
                reliable=True,
                destination_identities=[participant_identity],
                topic=DATA_CHANNEL_TOPIC
            )
        else:
            # Broadcast to all participants
            await ctx.room.local_participant.publish_data(
                payload,
                topic=DATA_CHANNEL_TOPIC
            )
    
    # Send initial connection message to the participant
    welcome_data = {
        "type": MESSAGE_TYPE_HANDSHAKE_REQUEST,
        "content": {
            "client_version": "1.0.0",
            "client_id": "macos-agent",
            "capabilities": ["command_execution", "screen_monitoring"],
            "server_time": time.time()
        }
    }
    await send_data_to_participant(welcome_data, participant.identity)
    logger.info(f"Sent handshake request to {participant.identity}")
    
    # Store active byte stream tasks to prevent garbage collection
    active_stream_tasks = []
    
    # Handle screen capture byte streams
    async def handle_screen_stream(reader, participant_identity):
        info = reader.info
        try:
            logger.info(f"Receiving screen capture stream: {info.name} from {participant_identity}")
            logger.info(f"  Topic: {info.topic}, ID: {info.id}, Size: {info.size if hasattr(info, 'size') else 'unknown'}")
            
            # Option 1: Get the entire file after the stream completes
            result = await reader.read_all()
            
            # Process the received screen capture if needed
            if result:
                logger.info(f"Received complete screen capture: {len(result)} bytes")
        except Exception as e:
            logger.error(f"Error handling screen stream: {e}")
    
    # Register byte stream handler non-async wrapper
    def on_byte_stream(reader, participant_identity):
        # Create an asyncio task to handle the byte stream
        task = asyncio.create_task(handle_screen_stream(reader, participant_identity))
        active_stream_tasks.append(task)
        task.add_done_callback(lambda t: active_stream_tasks.remove(t))
    
    # Register the byte stream handler for screen captures
    ctx.room.register_byte_stream_handler(SCREEN_STREAM_TOPIC, on_byte_stream)
    logger.info(f"Registered byte stream handler for topic: {SCREEN_STREAM_TOPIC}")
    
    # Start screen monitoring
    debug_dir = os.path.expanduser("~/screen_debug")
    monitor = screen_monitor.ScreenMonitor(send_data_to_participant, participant.identity, debug_dir)
    monitor_task = await monitor.start(ctx.room)
    logger.info("Screen monitoring started")
    
    # Add cleanup to stop the screen monitor when the job ends
    ctx.add_shutdown_callback(lambda: asyncio.create_task(monitor.stop()))


# Define a prewarm function for the agent
async def prewarm(ctx):
    """Prewarm function for the agent - initializes tokens and prepares the agent"""
    global current_token_info
    
    # Initialize tokens if needed
    if not current_token_info:
        current_token_info = initialize_tokens()
    
    logger.info("Agent prewarmed and ready to accept connections")
    return True


if __name__ == "__main__":
    # Ensure tokens are properly initialized
    if not current_token_info:
        logger.warning("Tokens were not properly initialized during module import, initializing now...")
        initialize_tokens()
    else:
        logger.info("Using tokens initialized during module import")
        
    logger.info("Starting LiveKit agent worker...")
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,  # Use the prewarm function instead of None
        ),
    )
    logger.info("LiveKit agent worker started")
