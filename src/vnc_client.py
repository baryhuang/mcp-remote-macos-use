import os
import logging
import socket
import time
import io
from PIL import Image
import pyDes
from typing import Optional, Tuple, List, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('vnc_client')
logger.setLevel(logging.DEBUG)


async def capture_vnc_screen(host: str, port: int, password: str, username: Optional[str] = None,
                             encryption: str = "prefer_on") -> Tuple[bool, Optional[bytes], Optional[str], Optional[Tuple[int, int]]]:
    """Capture a screenshot from a remote MacOs machine.

    Args:
        host: remote MacOs machine hostname or IP address
        port: remote MacOs machine port
        password: remote MacOs machine password
        username: remote MacOs machine username (optional)
        encryption: Encryption preference (default: "prefer_on")

    Returns:
        Tuple containing:
        - success: True if the operation was successful
        - screen_data: PNG image data if successful, None otherwise
        - error_message: Error message if unsuccessful, None otherwise
        - dimensions: Tuple of (width, height) if successful, None otherwise
    """
    logger.debug(f"Connecting to remote MacOs machine at {host}:{port} with encryption: {encryption}")

    # Initialize VNC client
    vnc = VNCClient(host=host, port=port, password=password, username=username, encryption=encryption)

    try:
        # Connect to remote MacOs machine
        success, error_message = vnc.connect()
        if not success:
            detailed_error = f"Failed to connect to remote MacOs machine at {host}:{port}. {error_message}\n"
            detailed_error += "This VNC client only supports Apple Authentication (protocol 30). "
            detailed_error += "Please ensure the remote MacOs machine supports this protocol. "
            detailed_error += "For macOS, enable Screen Sharing in System Preferences > Sharing."
            return False, None, detailed_error, None

        # Capture screen
        screen_data = vnc.capture_screen()

        if not screen_data:
            return False, None, f"Failed to capture screenshot from remote MacOs machine at {host}:{port}", None

        # Save original dimensions for reference
        original_dims = (vnc.width, vnc.height)

        # Scale the image to FWXGA resolution (1366x768)
        target_width, target_height = 1366, 768

        try:
            # Convert bytes to PIL Image
            image_data = io.BytesIO(screen_data)
            img = Image.open(image_data)

            # Resize the image to the target resolution
            scaled_img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

            # Convert back to bytes
            output_buffer = io.BytesIO()
            scaled_img.save(output_buffer, format='PNG')
            output_buffer.seek(0)
            scaled_screen_data = output_buffer.getvalue()

            logger.info(f"Scaled image from {original_dims[0]}x{original_dims[1]} to {target_width}x{target_height}")

            # Return success with scaled screen data and target dimensions
            return True, scaled_screen_data, None, (target_width, target_height)

        except Exception as e:
            logger.warning(f"Failed to scale image: {str(e)}. Returning original image.")
            # Return the original image if scaling fails
            return True, screen_data, None, original_dims

    finally:
        # Close VNC connection
        vnc.close()


def encrypt_MACOS_PASSWORD(password: str, challenge: bytes) -> bytes:
    """Encrypt VNC password for authentication.

    Args:
        password: VNC password
        challenge: Challenge bytes from server

    Returns:
        bytes: Encrypted response
    """
    # Convert password to key (truncate to 8 chars or pad with zeros)
    key = password.ljust(8, '\x00')[:8].encode('ascii')

    # VNC uses a reversed bit order for each byte in the key
    reversed_key = bytes([((k >> 0) & 1) << 7 |
                         ((k >> 1) & 1) << 6 |
                         ((k >> 2) & 1) << 5 |
                         ((k >> 3) & 1) << 4 |
                         ((k >> 4) & 1) << 3 |
                         ((k >> 5) & 1) << 2 |
                         ((k >> 6) & 1) << 1 |
                         ((k >> 7) & 1) << 0 for k in key])

    # Create a pyDes instance for encryption
    k = pyDes.des(reversed_key, pyDes.ECB, pad=None)

    # Encrypt the challenge with the key
    result = bytearray()
    for i in range(0, len(challenge), 8):
        block = challenge[i:i+8]
        cipher_block = k.encrypt(block)
        result.extend(cipher_block)

    return bytes(result)

class PixelFormat:
    """VNC pixel format specification."""

    def __init__(self, raw_data: bytes):
        """Parse pixel format from raw data.

        Args:
            raw_data: Raw pixel format data (16 bytes)
        """
        self.bits_per_pixel = raw_data[0]
        self.depth = raw_data[1]
        self.big_endian = raw_data[2] != 0
        self.true_color = raw_data[3] != 0
        self.red_max = int.from_bytes(raw_data[4:6], byteorder='big')
        self.green_max = int.from_bytes(raw_data[6:8], byteorder='big')
        self.blue_max = int.from_bytes(raw_data[8:10], byteorder='big')
        self.red_shift = raw_data[10]
        self.green_shift = raw_data[11]
        self.blue_shift = raw_data[12]
        # Padding bytes 13-15 ignored

    def __str__(self) -> str:
        """Return string representation of pixel format."""
        return (f"PixelFormat(bpp={self.bits_per_pixel}, depth={self.depth}, "
                f"big_endian={self.big_endian}, true_color={self.true_color}, "
                f"rgba_max=({self.red_max},{self.green_max},{self.blue_max}), "
                f"rgba_shift=({self.red_shift},{self.green_shift},{self.blue_shift}))")

class Encoding:
    """VNC encoding types."""
    RAW = 0
    COPY_RECT = 1
    RRE = 2
    HEXTILE = 5
    ZLIB = 6
    TIGHT = 7
    ZRLE = 16
    CURSOR = -239
    DESKTOP_SIZE = -223

class VNCClient:
    """VNC client implementation to connect to remote MacOs machines and capture screenshots."""

    def __init__(self, host: str, port: int = 5900, password: Optional[str] = None, username: Optional[str] = None,
                 encryption: str = "prefer_on"):
        """Initialize VNC client with connection parameters.

        Args:
            host: remote MacOs machine hostname or IP address
            port: remote MacOs machine port (default: 5900)
            password: remote MacOs machine password (optional)
            username: remote MacOs machine username (optional, only used with certain authentication methods)
            encryption: Encryption preference, one of "prefer_on", "prefer_off", "server" (default: "prefer_on")
        """
        self.host = host
        self.port = port
        self.password = password
        self.username = username
        self.encryption = encryption
        self.socket = None
        self.width = 0
        self.height = 0
        self.pixel_format = None
        self.name = ""
        self.protocol_version = ""
        self._last_frame = None  # Store last frame for incremental updates
        self._socket_buffer_size = 8192  # Increased buffer size for better performance
        logger.debug(f"Initialized VNC client for {host}:{port} with encryption={encryption}")
        if username:
            logger.debug(f"Username authentication enabled for: {username}")

    def connect(self) -> Tuple[bool, Optional[str]]:
        """Connect to the remote MacOs machine and perform the RFB handshake.

        Returns:
            Tuple[bool, Optional[str]]: (success, error_message) where success is True if connection
                                        was successful and error_message contains the reason for
                                        failure if success is False
        """
        try:
            logger.info(f"Attempting connection to remote MacOs machine at {self.host}:{self.port}")
            logger.debug(f"Connection parameters: encryption={self.encryption}, username={'set' if self.username else 'not set'}, password={'set' if self.password else 'not set'}")

            # Create socket and connect
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)  # 10 second timeout
            logger.debug(f"Created socket with 10 second timeout")

            try:
                self.socket.connect((self.host, self.port))
                logger.info(f"Successfully established TCP connection to {self.host}:{self.port}")
            except ConnectionRefusedError:
                error_msg = f"Connection refused by {self.host}:{self.port}. Ensure remote MacOs machine is running and port is correct."
                logger.error(error_msg)
                return False, error_msg
            except socket.timeout:
                error_msg = f"Connection timed out while trying to connect to {self.host}:{self.port}"
                logger.error(error_msg)
                return False, error_msg
            except socket.gaierror as e:
                error_msg = f"DNS resolution failed for host {self.host}: {str(e)}"
                logger.error(error_msg)
                return False, error_msg

            # Receive RFB protocol version
            try:
                version = self.socket.recv(12).decode('ascii')
                self.protocol_version = version.strip()
                logger.info(f"Server protocol version: {self.protocol_version}")

                if not version.startswith("RFB "):
                    error_msg = f"Invalid protocol version string received: {version}"
                    logger.error(error_msg)
                    return False, error_msg

                # Parse version numbers for debugging
                try:
                    major, minor = version[4:].strip().split(".")
                    logger.debug(f"Server RFB version: major={major}, minor={minor}")
                except ValueError:
                    logger.warning(f"Could not parse version numbers from: {version}")
            except socket.timeout:
                error_msg = "Timeout while waiting for protocol version"
                logger.error(error_msg)
                return False, error_msg

            # Send our protocol version
            our_version = b"RFB 003.008\n"
            logger.debug(f"Sending our protocol version: {our_version.decode('ascii').strip()}")
            self.socket.sendall(our_version)

            # In RFB 3.8+, server sends number of security types followed by list of types
            try:
                security_types_count = self.socket.recv(1)[0]
                logger.info(f"Server offers {security_types_count} security types")

                if security_types_count == 0:
                    # Read error message
                    error_length = int.from_bytes(self.socket.recv(4), byteorder='big')
                    error_message = self.socket.recv(error_length).decode('ascii')
                    error_msg = f"Server rejected connection with error: {error_message}"
                    logger.error(error_msg)
                    return False, error_msg

                # Receive available security types
                security_types = self.socket.recv(security_types_count)
                logger.debug(f"Available security types: {[st for st in security_types]}")

                # Log security type descriptions
                security_type_names = {
                    0: "Invalid",
                    1: "None",
                    2: "VNC Authentication",
                    5: "RA2",
                    6: "RA2ne",
                    16: "Tight",
                    18: "TLS",
                    19: "VeNCrypt",
                    20: "GTK-VNC SASL",
                    21: "MD5 hash authentication",
                    22: "Colin Dean xvp",
                    30: "Apple Authentication"
                }

                for st in security_types:
                    name = security_type_names.get(st, f"Unknown type {st}")
                    logger.debug(f"Server supports security type {st}: {name}")
            except socket.timeout:
                error_msg = "Timeout while waiting for security types"
                logger.error(error_msg)
                return False, error_msg

            # Choose a security type we can handle based on encryption preference
            chosen_type = None

            # Check if security type 30 (Apple Authentication) is available
            if 30 in security_types and self.password:
                logger.info("Found Apple Authentication (type 30) - selecting")
                chosen_type = 30
            else:
                error_msg = "Apple Authentication (type 30) not available from server"
                logger.error(error_msg)
                logger.debug("Server security types: " + ", ".join(str(st) for st in security_types))
                logger.debug("We only support Apple Authentication (30)")
                return False, error_msg

            # Send chosen security type
            logger.info(f"Selecting security type: {chosen_type}")
            self.socket.sendall(bytes([chosen_type]))

            # Handle authentication based on chosen type
            if chosen_type == 30:
                logger.debug(f"Starting Apple authentication (type {chosen_type})")
                if not self.password:
                    error_msg = "Password required but not provided"
                    logger.error(error_msg)
                    return False, error_msg

                # Receive Diffie-Hellman parameters from server
                logger.debug("Reading Diffie-Hellman parameters from server")
                try:
                    # Read generator (2 bytes)
                    generator_data = self.socket.recv(2)
                    if len(generator_data) != 2:
                        error_msg = f"Invalid generator data received: {generator_data.hex()}"
                        logger.error(error_msg)
                        return False, error_msg
                    generator = int.from_bytes(generator_data, byteorder='big')
                    logger.debug(f"Generator: {generator}")

                    # Read key length (2 bytes)
                    key_length_data = self.socket.recv(2)
                    if len(key_length_data) != 2:
                        error_msg = f"Invalid key length data received: {key_length_data.hex()}"
                        logger.error(error_msg)
                        return False, error_msg
                    key_length = int.from_bytes(key_length_data, byteorder='big')
                    logger.debug(f"Key length: {key_length}")

                    # Read prime modulus (key_length bytes)
                    prime_data = self.socket.recv(key_length)
                    if len(prime_data) != key_length:
                        error_msg = f"Invalid prime data received, expected {key_length} bytes, got {len(prime_data)}"
                        logger.error(error_msg)
                        return False, error_msg
                    logger.debug(f"Prime modulus received ({len(prime_data)} bytes)")

                    # Read server's public key (key_length bytes)
                    server_public_key = self.socket.recv(key_length)
                    if len(server_public_key) != key_length:
                        error_msg = f"Invalid server public key received, expected {key_length} bytes, got {len(server_public_key)}"
                        logger.error(error_msg)
                        return False, error_msg
                    logger.debug(f"Server public key received ({len(server_public_key)} bytes)")

                    # Import required libraries for Diffie-Hellman key exchange
                    try:
                        from cryptography.hazmat.primitives.asymmetric import dh
                        from cryptography.hazmat.primitives import hashes
                        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                        import os

                        # Convert parameters to integers for DH
                        p_int = int.from_bytes(prime_data, byteorder='big')
                        g_int = generator

                        # Create parameter numbers
                        parameter_numbers = dh.DHParameterNumbers(p_int, g_int)
                        parameters = parameter_numbers.parameters()

                        # Generate our private key
                        private_key = parameters.generate_private_key()

                        # Get our public key in bytes
                        public_key_bytes = private_key.public_key().public_numbers().y.to_bytes(key_length, byteorder='big')

                        # Convert server's public key to integer
                        server_public_int = int.from_bytes(server_public_key, byteorder='big')
                        server_public_numbers = dh.DHPublicNumbers(server_public_int, parameter_numbers)
                        server_public_key_obj = server_public_numbers.public_key()

                        # Generate shared key
                        shared_key = private_key.exchange(server_public_key_obj)

                        # Generate MD5 hash of shared key for AES
                        md5 = hashes.Hash(hashes.MD5())
                        md5.update(shared_key)
                        aes_key = md5.finalize()

                        # Create credentials array (128 bytes)
                        creds = bytearray(128)

                        # Fill with random data
                        for i in range(128):
                            creds[i] = ord(os.urandom(1))

                        # Add username and password to credentials array
                        username_bytes = self.username.encode('utf-8') if self.username else b''
                        password_bytes = self.password.encode('utf-8')

                        # Username in first 64 bytes
                        username_len = min(len(username_bytes), 63)  # Leave room for null byte
                        creds[0:username_len] = username_bytes[0:username_len]
                        creds[username_len] = 0  # Null terminator

                        # Password in second 64 bytes
                        password_len = min(len(password_bytes), 63)  # Leave room for null byte
                        creds[64:64+password_len] = password_bytes[0:password_len]
                        creds[64+password_len] = 0  # Null terminator

                        # Encrypt credentials with AES-128-ECB
                        cipher = Cipher(algorithms.AES(aes_key), modes.ECB())
                        encryptor = cipher.encryptor()
                        encrypted_creds = encryptor.update(creds) + encryptor.finalize()

                        # Send encrypted credentials followed by our public key
                        logger.debug("Sending encrypted credentials and public key")
                        self.socket.sendall(encrypted_creds + public_key_bytes)

                    except ImportError as e:
                        error_msg = f"Missing required libraries for DH key exchange: {str(e)}"
                        logger.error(error_msg)
                        logger.debug("Install required packages with: pip install cryptography")
                        return False, error_msg
                    except Exception as e:
                        error_msg = f"Error during Diffie-Hellman key exchange: {str(e)}"
                        logger.error(error_msg)
                        return False, error_msg

                except Exception as e:
                    error_msg = f"Error reading DH parameters: {str(e)}"
                    logger.error(error_msg)
                    return False, error_msg

                # Check authentication result
                try:
                    logger.debug("Waiting for Apple authentication result")
                    auth_result = int.from_bytes(self.socket.recv(4), byteorder='big')

                    # Map known Apple VNC error codes
                    apple_auth_errors = {
                        1: "Authentication failed - invalid password",
                        2: "Authentication failed - password required",
                        3: "Authentication failed - too many attempts",
                        560513588: "Authentication failed - encryption mismatch or invalid credentials",
                        # Add more error codes as discovered
                    }

                    if auth_result != 0:
                        error_msg = apple_auth_errors.get(auth_result, f"Authentication failed with unknown error code: {auth_result}")
                        logger.error(f"Apple authentication failed: {error_msg}")
                        if auth_result == 560513588:
                            error_msg += "\nThis error often indicates:\n"
                            error_msg += "1. Password encryption/encoding mismatch\n"
                            error_msg += "2. Screen Recording permission not granted\n"
                            error_msg += "3. Remote Management/Screen Sharing not enabled"
                            logger.debug("This error often indicates:")
                            logger.debug("1. Password encryption/encoding mismatch")
                            logger.debug("2. Screen Recording permission not granted")
                            logger.debug("3. Remote Management/Screen Sharing not enabled")
                        return False, error_msg

                    logger.info("Apple authentication successful")
                except Exception as e:
                    error_msg = f"Error reading authentication result: {str(e)}"
                    logger.error(error_msg)
                    return False, error_msg
            else:
                error_msg = f"Only Apple Authentication (type 30) is supported"
                logger.error(error_msg)
                return False, error_msg

            # Send client init (shared flag)
            logger.debug("Sending client init with shared flag")
            self.socket.sendall(b'\x01')  # non-zero = shared

            # Receive server init
            logger.debug("Waiting for server init message")
            server_init_header = self.socket.recv(24)
            if len(server_init_header) < 24:
                error_msg = f"Incomplete server init header received: {server_init_header.hex()}"
                logger.error(error_msg)
                return False, error_msg

            # Parse server init
            self.width = int.from_bytes(server_init_header[0:2], byteorder='big')
            self.height = int.from_bytes(server_init_header[2:4], byteorder='big')
            self.pixel_format = PixelFormat(server_init_header[4:20])

            name_length = int.from_bytes(server_init_header[20:24], byteorder='big')
            logger.debug(f"Server reports desktop size: {self.width}x{self.height}")
            logger.debug(f"Server name length: {name_length}")

            if name_length > 0:
                name_data = self.socket.recv(name_length)
                self.name = name_data.decode('utf-8', errors='replace')
                logger.debug(f"Server name: {self.name}")

            logger.info(f"Successfully connected to remote MacOs machine: {self.name}")
            logger.debug(f"Screen dimensions: {self.width}x{self.height}")
            logger.debug(f"Initial pixel format: {self.pixel_format}")

            # Set preferred pixel format (32-bit true color)
            logger.debug("Setting preferred pixel format")
            self._set_pixel_format()

            # Set encodings (prioritize the ones we can actually handle)
            logger.debug("Setting supported encodings")
            self._set_encodings([Encoding.RAW, Encoding.COPY_RECT, Encoding.DESKTOP_SIZE])

            logger.info("VNC connection fully established and configured")
            return True, None

        except Exception as e:
            error_msg = f"Unexpected error during VNC connection: {str(e)}"
            logger.error(error_msg, exc_info=True)
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            return False, error_msg

    def _set_pixel_format(self):
        """Set the pixel format to be used for the connection (32-bit true color)."""
        try:
            message = bytearray([0])  # message type 0 = SetPixelFormat
            message.extend([0, 0, 0])  # padding

            # Pixel format (16 bytes)
            message.extend([
                32,  # bits-per-pixel
                24,  # depth
                1,   # big-endian flag (1 = true)
                1,   # true-color flag (1 = true)
                0, 255,  # red-max (255)
                0, 255,  # green-max (255)
                0, 255,  # blue-max (255)
                16,  # red-shift
                8,   # green-shift
                0,   # blue-shift
                0, 0, 0  # padding
            ])

            self.socket.sendall(message)
            logger.debug("Set pixel format to 32-bit true color")
        except Exception as e:
            logger.error(f"Error setting pixel format: {str(e)}")

    def _set_encodings(self, encodings: List[int]):
        """Set the encodings to be used for the connection.

        Args:
            encodings: List of encoding types
        """
        try:
            message = bytearray([2])  # message type 2 = SetEncodings
            message.extend([0])  # padding

            # Number of encodings
            message.extend(len(encodings).to_bytes(2, byteorder='big'))

            # Encodings
            for encoding in encodings:
                message.extend(encoding.to_bytes(4, byteorder='big', signed=True))

            self.socket.sendall(message)
            logger.debug(f"Set encodings: {encodings}")
        except Exception as e:
            logger.error(f"Error setting encodings: {str(e)}")

    def _decode_raw_rect(self, rect_data: bytes, x: int, y: int, width: int, height: int,
                        img: Image.Image) -> None:
        """Decode a RAW-encoded rectangle and draw it to the image.

        Args:
            rect_data: Raw pixel data
            x: X position of rectangle
            y: Y position of rectangle
            width: Width of rectangle
            height: Height of rectangle
            img: PIL Image to draw to
        """
        try:
            # Create a new image from the raw data
            if self.pixel_format.bits_per_pixel == 32:
                # 32-bit color (RGBA)
                raw_img = Image.frombytes('RGBA', (width, height), rect_data)
                # Convert to RGB if needed
                if raw_img.mode != 'RGB':
                    raw_img = raw_img.convert('RGB')
            elif self.pixel_format.bits_per_pixel == 16:
                # 16-bit color needs special handling
                raw_img = Image.new('RGB', (width, height))
                pixels = raw_img.load()

                for i in range(height):
                    for j in range(width):
                        idx = (i * width + j) * 2
                        pixel = int.from_bytes(rect_data[idx:idx+2],
                                            byteorder='big' if self.pixel_format.big_endian else 'little')

                        r = ((pixel >> self.pixel_format.red_shift) & self.pixel_format.red_max)
                        g = ((pixel >> self.pixel_format.green_shift) & self.pixel_format.green_max)
                        b = ((pixel >> self.pixel_format.blue_shift) & self.pixel_format.blue_max)

                        # Scale values to 0-255 range
                        r = int(r * 255 / self.pixel_format.red_max)
                        g = int(g * 255 / self.pixel_format.green_max)
                        b = int(b * 255 / self.pixel_format.blue_max)

                        pixels[j, i] = (r, g, b)
            else:
                # Fallback for other bit depths (basic conversion)
                raw_img = Image.new('RGB', (width, height), color='black')
                logger.warning(f"Unsupported pixel format: {self.pixel_format.bits_per_pixel}-bit")

            # Paste the decoded image onto the target image
            img.paste(raw_img, (x, y))

        except Exception as e:
            logger.error(f"Error decoding RAW rectangle: {str(e)}")
            # Fill with error color on failure
            raw_img = Image.new('RGB', (width, height), color='red')
            img.paste(raw_img, (x, y))

    def _decode_copy_rect(self, rect_data: bytes, x: int, y: int, width: int, height: int,
                         img: Image.Image) -> None:
        """Decode a COPY_RECT-encoded rectangle and draw it to the image.

        Args:
            rect_data: CopyRect data (src_x, src_y)
            x: X position of destination rectangle
            y: Y position of destination rectangle
            width: Width of rectangle
            height: Height of rectangle
            img: PIL Image to draw to
        """
        try:
            src_x = int.from_bytes(rect_data[0:2], byteorder='big')
            src_y = int.from_bytes(rect_data[2:4], byteorder='big')

            # Copy the region from the image itself
            region = img.crop((src_x, src_y, src_x + width, src_y + height))
            img.paste(region, (x, y))

        except Exception as e:
            logger.error(f"Error decoding COPY_RECT rectangle: {str(e)}")
            # Fill with error color on failure
            raw_img = Image.new('RGB', (width, height), color='blue')
            img.paste(raw_img, (x, y))

    def capture_screen(self) -> Optional[bytes]:
        """Capture a screenshot from the remote MacOs machine with optimizations."""
        try:
            if not self.socket:
                logger.error("Not connected to remote MacOs machine")
                return None

            # Use incremental updates if we have a previous frame
            is_incremental = self._last_frame is not None

            # Create or reuse image
            if is_incremental:
                img = self._last_frame
            else:
                img = Image.new('RGB', (self.width, self.height), color='black')

            # Send FramebufferUpdateRequest message
            msg = bytearray([3])  # message type 3 = FramebufferUpdateRequest
            msg.extend([1 if is_incremental else 0])  # Use incremental updates when possible
            msg.extend(int(0).to_bytes(2, byteorder='big'))  # x-position
            msg.extend(int(0).to_bytes(2, byteorder='big'))  # y-position
            msg.extend(int(self.width).to_bytes(2, byteorder='big'))  # width
            msg.extend(int(self.height).to_bytes(2, byteorder='big'))  # height

            self.socket.sendall(msg)

            # Receive FramebufferUpdate message header with larger buffer
            header = self._recv_exact(4)
            if not header or header[0] != 0:  # 0 = FramebufferUpdate
                logger.error(f"Unexpected message type in response: {header[0] if header else 'None'}")
                return None

            # Read number of rectangles
            num_rects = int.from_bytes(header[2:4], byteorder='big')
            logger.debug(f"Received {num_rects} rectangles")

            # Process each rectangle
            for rect_idx in range(num_rects):
                # Read rectangle header efficiently
                rect_header = self._recv_exact(12)
                if not rect_header:
                    logger.error("Failed to read rectangle header")
                    return None

                x = int.from_bytes(rect_header[0:2], byteorder='big')
                y = int.from_bytes(rect_header[2:4], byteorder='big')
                width = int.from_bytes(rect_header[4:6], byteorder='big')
                height = int.from_bytes(rect_header[6:8], byteorder='big')
                encoding_type = int.from_bytes(rect_header[8:12], byteorder='big', signed=True)

                if encoding_type == Encoding.RAW:
                    # Optimize RAW encoding processing
                    pixel_size = self.pixel_format.bits_per_pixel // 8
                    data_size = width * height * pixel_size

                    # Read pixel data in chunks
                    rect_data = self._recv_exact(data_size)
                    if not rect_data or len(rect_data) != data_size:
                        logger.error(f"Failed to read RAW rectangle data")
                        return None

                    # Decode and draw
                    self._decode_raw_rect(rect_data, x, y, width, height, img)

                elif encoding_type == Encoding.COPY_RECT:
                    # Optimize COPY_RECT processing
                    rect_data = self._recv_exact(4)
                    if not rect_data:
                        logger.error("Failed to read COPY_RECT data")
                        return None
                    self._decode_copy_rect(rect_data, x, y, width, height, img)

                elif encoding_type == Encoding.DESKTOP_SIZE:
                    # Handle desktop size changes
                    logger.debug(f"Desktop size changed to {width}x{height}")
                    self.width = width
                    self.height = height
                    new_img = Image.new('RGB', (self.width, self.height), color='black')
                    new_img.paste(img, (0, 0))
                    img = new_img
                else:
                    logger.warning(f"Unsupported encoding type: {encoding_type}")
                    continue

            # Store the frame for future incremental updates
            self._last_frame = img

            # Convert image to PNG with optimization
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG', optimize=True, quality=95)
            img_byte_arr.seek(0)

            return img_byte_arr.getvalue()

        except Exception as e:
            logger.error(f"Error capturing screen: {str(e)}")
            return None

    def _recv_exact(self, size: int) -> Optional[bytes]:
        """Receive exactly size bytes from the socket efficiently."""
        try:
            data = bytearray()
            while len(data) < size:
                chunk = self.socket.recv(min(self._socket_buffer_size, size - len(data)))
                if not chunk:
                    return None
                data.extend(chunk)
            return bytes(data)
        except Exception as e:
            logger.error(f"Error receiving data: {str(e)}")
            return None

    def close(self):
        """Close the connection to the remote MacOs machine."""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

    def send_key_event(self, key: int, down: bool) -> bool:
        """Send a key event to the remote MacOs machine.

        Args:
            key: X11 keysym value representing the key
            down: True for key press, False for key release

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.socket:
                logger.error("Not connected to remote MacOs machine")
                return False

            # Message type 4 = KeyEvent
            message = bytearray([4])

            # Down flag (1 = pressed, 0 = released)
            message.extend([1 if down else 0])

            # Padding (2 bytes)
            message.extend([0, 0])

            # Key (4 bytes, big endian)
            message.extend(key.to_bytes(4, byteorder='big'))

            logger.debug(f"Sending KeyEvent: key=0x{key:08x}, down={down}")
            self.socket.sendall(message)
            return True

        except Exception as e:
            logger.error(f"Error sending key event: {str(e)}")
            return False

    def send_pointer_event(self, x: int, y: int, button_mask: int) -> bool:
        """Send a pointer (mouse) event to the remote MacOs machine.

        Args:
            x: X position (0 to framebuffer_width-1)
            y: Y position (0 to framebuffer_height-1)
            button_mask: Bit mask of pressed buttons:
                bit 0 = left button (1)
                bit 1 = middle button (2)
                bit 2 = right button (4)
                bit 3 = wheel up (8)
                bit 4 = wheel down (16)
                bit 5 = wheel left (32)
                bit 6 = wheel right (64)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.socket:
                logger.error("Not connected to remote MacOs machine")
                return False

            # Ensure coordinates are within framebuffer bounds
            x = max(0, min(x, self.width - 1))
            y = max(0, min(y, self.height - 1))

            # Message type 5 = PointerEvent
            message = bytearray([5])

            # Button mask (1 byte)
            message.extend([button_mask & 0xFF])

            # X position (2 bytes, big endian)
            message.extend(x.to_bytes(2, byteorder='big'))

            # Y position (2 bytes, big endian)
            message.extend(y.to_bytes(2, byteorder='big'))

            logger.debug(f"Sending PointerEvent: x={x}, y={y}, button_mask={button_mask:08b}")
            self.socket.sendall(message)
            return True

        except Exception as e:
            logger.error(f"Error sending pointer event: {str(e)}")
            return False

    def send_mouse_click(self, x: int, y: int, button: int = 1, double_click: bool = False, delay_ms: int = 100) -> bool:
        """Send a mouse click at the specified position.

        Args:
            x: X position
            y: Y position
            button: Mouse button (1=left, 2=middle, 3=right)
            double_click: Whether to perform a double-click
            delay_ms: Delay between press and release in milliseconds

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.socket:
                logger.error("Not connected to remote MacOs machine")
                return False

            # Calculate button mask
            button_mask = 1 << (button - 1)

            # Move mouse to position first (no buttons pressed)
            if not self.send_pointer_event(x, y, 0):
                return False

            # Single click or first click of double-click
            if not self.send_pointer_event(x, y, button_mask):
                return False

            # Wait for press-release delay
            time.sleep(delay_ms / 1000.0)

            # Release button
            if not self.send_pointer_event(x, y, 0):
                return False

            # If double click, perform second click
            if double_click:
                # Wait between clicks
                time.sleep(delay_ms / 1000.0)

                # Second press
                if not self.send_pointer_event(x, y, button_mask):
                    return False

                # Wait for press-release delay
                time.sleep(delay_ms / 1000.0)

                # Second release
                if not self.send_pointer_event(x, y, 0):
                    return False

            return True

        except Exception as e:
            logger.error(f"Error sending mouse click: {str(e)}")
            return False

    def send_text(self, text: str) -> bool:
        """Send text as a series of key press/release events.

        Args:
            text: The text to send

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.socket:
                logger.error("Not connected to remote MacOs machine")
                return False

            # Standard ASCII to X11 keysym mapping for printable ASCII characters
            # For most characters, the keysym is just the ASCII value
            success = True

            for char in text:
                # Special key mapping for common non-printable characters
                if char == '\n' or char == '\r':  # Return/Enter
                    key = 0xff0d
                elif char == '\t':  # Tab
                    key = 0xff09
                elif char == '\b':  # Backspace
                    key = 0xff08
                elif char == ' ':  # Space
                    key = 0x20
                else:
                    # For printable ASCII and Unicode characters
                    key = ord(char)

                # If it's an uppercase letter, we need to simulate a shift press
                need_shift = char.isupper() or char in '~!@#$%^&*()_+{}|:"<>?'

                if need_shift:
                    # Press shift (left shift keysym = 0xffe1)
                    if not self.send_key_event(0xffe1, True):
                        success = False
                        break

                # Press key
                if not self.send_key_event(key, True):
                    success = False
                    break

                # Release key
                if not self.send_key_event(key, False):
                    success = False
                    break

                if need_shift:
                    # Release shift
                    if not self.send_key_event(0xffe1, False):
                        success = False
                        break

                # Small delay between keys to avoid overwhelming the server
                time.sleep(0.01)

            return success

        except Exception as e:
            logger.error(f"Error sending text: {str(e)}")
            return False

    def send_key_combination(self, keys: List[int]) -> bool:
        """Send a key combination (e.g., Ctrl+Alt+Delete).

        Args:
            keys: List of X11 keysym values to press in sequence

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.socket:
                logger.error("Not connected to remote MacOs machine")
                return False

            # Press all keys in sequence
            for key in keys:
                if not self.send_key_event(key, True):
                    return False

            # Release all keys in reverse order
            for key in reversed(keys):
                if not self.send_key_event(key, False):
                    return False

            return True

        except Exception as e:
            logger.error(f"Error sending key combination: {str(e)}")
            return False
