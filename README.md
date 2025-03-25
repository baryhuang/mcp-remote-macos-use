# MCP Server - Remote MacOs Use
**The first open-source MCP server that enables AI to fully control remote macOS systems.**

**A direct alternative to OpenAI Operator, optimized specifically for autonomous AI agents with complete desktop capabilities, requiring no additional software installation.**

[![Docker Pulls](https://img.shields.io/docker/pulls/buryhuang/mcp-remote-macos-use)](https://hub.docker.com/r/buryhuang/mcp-remote-macos-use)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Showcase Demo**
https://www.youtube.com/watch?v=--QHz2jcvcs
<img width="1259" alt="image" src="https://github.com/user-attachments/assets/bfe6e354-3d59-4d08-855b-2eecdaaeb46f" />


## Features

* **No Extra API Costs**: Free screen processing with your existing Claude Pro plan
* **Minimal Setup**: Just enable Screen Sharing on the target Mac – no additional software needed
* **Universal Compatibility**: Works with all macOS versions, current and future
  
## Why We Built This

### Native macOS Experience Without Compromise
The macOS native ecosystem remains unmatched in user experience today and will continue to be the gold standard for years to come. This is where human capabilities truly thrive, and now your AI can operate in this environment with the same fluency.

### Open Architecture By Design
* **Universal LLM Compatibility**: Work with any MCP Client of your choice
* **Model Flexibility**: Seamlessly integrate with OpenAI, Anthropic, or any other LLM provider
* **Future-Proof Integration**: Designed to evolve with the MCP ecosystem

### Effortless Deployment
* **Zero Setup on Target Machines**: No background applications or agents needed on macOS
* **Screen Sharing is All You Need**: Control any Mac with Screen Sharing enabled
* **Eliminate Backend Complexity**: Unlike other solutions that require running Python applications or background services

### Streamlined Bootstrap Process
* **Leverage Claude Desktop's Polished UI**: No need for developer-style Python interfaces
* **Intuitive User Experience**: Interact with your AI-controlled Mac through a familiar, user-friendly interface
* **Instant Productivity**: Start working immediately without configuration hassles
 
## Architecture
<img width="912" alt="remote_macos_use_system_architecture" src="https://github.com/user-attachments/assets/75ece060-90e2-4ad3-bb52-2c69427001dd" />


## Installation
- [Enable Screen Sharing on MacOs](https://support.apple.com/guide/remote-desktop/set-up-a-computer-running-vnc-software-apdbed09830/mac) **If you rent a mac from macstadium.com, you can skip this step**
- [Connect to your remote MacOs](https://support.apple.com/guide/mac-help/share-the-screen-of-another-mac-mh14066/mac)
- [Install Docker Desktop for local Mac](https://docs.docker.com/desktop/setup/install/mac-install/)
- [Add this MCP server to Claude Desktop](https://modelcontextprotocol.io/quickstart/user)
You can configure Claude Desktop to use the Docker image by adding the following to your Claude configuration:
```json
{
  "mcpServers": {
    "remote-macos-use": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "buryhuang/mcp-remote-macos-use:latest"
      ]
    }
  }
}
```


## Developer Instruction
### Clone the repo
```bash
# Clone the repository
git clone https://github.com/yourusername/mcp-remote-macos-use.git
cd mcp-remote-macos-use
```

### Building the Docker Image

```bash
# Build the Docker image
docker build -t mcp-remote-macos-use .
```

## Usage with Claude Desktop

### Docker Usage

You can configure Claude Desktop to use the Docker image by adding the following to your Claude configuration:

```json
{
  "mcpServers": {
    "remote-macos-use": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "-e",
        "MACOS_USERNAME=your_macos_username",
        "-e",
        "MACOS_PASSWORD=your_macos_password",
        "-e",
        "MACOS_HOST=your_macos_hostname_or_ip",
        "--rm",
        "buryhuang/mcp-remote-macos-use:latest"
      ]
    }
  }
}
```

## Cross-Platform Publishing

To publish the Docker image for multiple platforms, you can use the `docker buildx` command. Follow these steps:

1. **Create a new builder instance** (if you haven't already):
   ```bash
   docker buildx create --use
   ```

2. **Build and push the image for multiple platforms**:
   ```bash
   docker buildx build --platform linux/amd64,linux/arm64 -t buryhuang/mcp-remote-macos-use:latest --push .
   ```

3. **Verify the image is available for the specified platforms**:
   ```bash
   docker buildx imagetools inspect buryhuang/mcp-remote-macos-use:latest
   ```

## Usage

The server provides Remote MacOs functionality through MCP tools.

### Tools Specifications

The server provides four main tools for remote MacOS control:

#### remote_macos_get_screen
Get a screenshot of the remote desktop. Example:
```json
{
  "host": "remote-macos-hostname-or-ip",
  "port": 5900,
  "password": "remote-macos-password",
  "username": "remote-macos-username",
  "encryption": "prefer_on"
}
```

#### remote_macos_send_keys
Send keyboard input. Example:
```json
{
  "host": "remote-macos-hostname-or-ip",
  "password": "remote-macos-password",
  "text": "Hello world!",
  "special_key": "enter",
  "key_combination": "cmd+c"
}
```

#### remote_macos_send_mouse
Send mouse input. Example:
```json
{
  "host": "remote-macos-hostname-or-ip",
  "password": "remote-macos-password",
  "x": 500,
  "y": 300,
  "button": 1,
  "action": "click"
}
```

#### remote_macos_scale_coordinates
Scale coordinates between different screen sizes. Example:
```json
{
  "host": "remote-macos-hostname-or-ip",
  "password": "remote-macos-password",
  "source_width": 1366,
  "source_height": 768,
  "x": 500,
  "y": 300
}
```

All tools support Apple Authentication (protocol 30) and require at minimum a host and password.

## Limitations

- **Authentication Support**: 
  - Only Apple Authentication (protocol 30) is supported

## Security Note

https://support.apple.com/guide/remote-desktop/encrypt-network-data-apdfe8e386b/mac
https://cafbit.com/post/apple_remote_desktop_quirks/

We only support protocol 30, which uses the Diffie-Hellman key agreement protocol with a 512-bit prime. This protocol is used by macOS 11 to macOS 12 when communicating with OS X 10.11 or earlier clients.

Here's the information converted to a markdown table:

| macOS version running Remote Desktop | macOS client version | Authentication | Control and Observe | Copy items or install package | All other tasks | Protocol Version |
|--------------------------------------|----------------------|----------------|---------------------|-------------------------------|----------------|----------------|
| macOS 13 | macOS 13 | 2048-bit RSA host keys | 2048-bit RSA host keys | 2048-bit RSA host keys to authenticate, then 128-bit AES | 2048-bit RSA host keys | 36 |
| macOS 13 | macOS 10.12 | Secure Remote Password (SRP) protocol for local only. Diffie-Hellman (DH) if bound to LDAP or macOS server is version 10.11 or earlier | SRP or DH,128-bit AES | SRP or DH to authenticate, then 128-bit AES | 2048-bit RSA host keys | 35 |
| macOS 11 to macOS 12 | macOS 10.12 to macOS 13 | Secure Remote Password (SRP) protocol for local only, Diffie-Hellman if bound to LDAP | SRP or DH 1024-bit, 128-bit AES | 2048-bit RSA host keys macOS 13 to macOS 10.13 | 2048-bit RSA host keys macOS 10.13 or later |  33 |
| macOS 11 to macOS 12 | OS X 10.11 or earlier | DH 1024-bit | DH 1024-bit, 128-bit AES | Diffie-Hellman Key agreement protocol with a 512-bit prime | Diffie-Hellman Key agreement protocol with a 512-bit prime |  30 |


Always use secure, authenticated connections when accessing remote remote MacOs machines. This tool should only be used with servers you trust and have permission to access.

## License

See the LICENSE file for details. 
