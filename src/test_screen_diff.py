#!/usr/bin/env python3
import asyncio
import json
import sys
import os
import logging
from macos_client import screen_capture

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test-screen-diff")

def print_structured_response(result):
    """Pretty print the structured response data"""
    if not result or not result.get("success", False):
        print(f"Error: {result.get('error', 'Unknown error occurred')}")
        return
    
    print("\n===== RESPONSE STRUCTURE =====")
    print(f"Success: {result.get('success')}")
    
    # Display content structure
    content = result.get('content', [])
    print(f"\nContent (type: {type(content).__name__}):")
    if isinstance(content, list):
        for i, block in enumerate(content):
            print(f"  Block {i+1} (type: {block.get('type', 'unknown')})")
            if block.get('type') == 'text':
                print(f"    Text: {block.get('text', '')[:100]}...")
            elif block.get('type') == 'tool_use':
                print(f"    Tool: {block.get('name')}")
                print(f"    Input: {json.dumps(block.get('input', {}), indent=2)[:150]}...")
    else:
        print(f"  {str(content)[:150]}...")
    
    # Display structured differences
    structured_data = result.get('structured_differences')
    if structured_data:
        changes = structured_data.get('changes', [])
        summary = structured_data.get('summary', 'No summary available')
        
        print("\n===== SCREEN DIFFERENCE REPORT =====")
        print(f"Summary: {summary}")
        print(f"Found {len(changes)} changed areas:\n")
        
        for i, change in enumerate(changes, 1):
            coords = change.get("coordinates", {})
            print(f"Change {i}:")
            print(f"  Description: {change.get('description', 'No description')}")
            print(f"  Coordinates: x1={coords.get('x1')}, y1={coords.get('y1')}, x2={coords.get('x2')}, y2={coords.get('y2')}")
            print(f"  Significance: {change.get('significance', 'unknown')}")
            print()
        
        # Save the structured result to a JSON file
        output_file = "screen_diff_result.json"
        with open(output_file, "w") as f:
            json.dump(structured_data, f, indent=2)
        print(f"Full structured result saved to {output_file}")
    else:
        print("\nNo structured difference data found in the response.")
        print("Raw response data saved for debugging.")
        
        # Save the entire raw response for debugging
        raw_file = "raw_response.json"
        with open(raw_file, "w") as f:
            # Make sure we can serialize the raw response
            raw_response = result.get('raw_response', {})
            json.dump(raw_response, f, indent=2)
        print(f"Raw response saved to {raw_file}")

async def main():
    """Test the screen difference detection with function calling"""
    
    if len(sys.argv) < 3:
        print("Usage: python test_screen_diff.py image1.png image2.png")
        sys.exit(1)
    
    image1_path = sys.argv[1]
    image2_path = sys.argv[2]
    
    # Check if files exist
    if not os.path.exists(image1_path) or not os.path.exists(image2_path):
        print(f"Error: One or both of the specified image files doesn't exist")
        sys.exit(1)
    
    logger.info(f"Comparing images: {image1_path} and {image2_path}")
    
    # Read the image files
    with open(image1_path, 'rb') as f1, open(image2_path, 'rb') as f2:
        img1 = f1.read()
        img2 = f2.read()
    
    # Call the function calling version
    logger.info("Using function calling for structured coordinates")
    result = await screen_capture.find_screen_differences_with_function_calling(img1, img2)
    
    # Print the structured response in a useful way
    print_structured_response(result)

if __name__ == "__main__":
    asyncio.run(main()) 