#!/usr/bin/env python3
"""
PDF Spread Viewer MCP Server
Converts PDF double-page spreads into single images with borders
"""

import sys
import json
import base64
from io import BytesIO
from pathlib import Path

try:
    from pdf2image import convert_from_path
    from PIL import Image, ImageDraw
except ImportError:
    print("Error: Required packages not installed", file=sys.stderr)
    print("Install with: pip install pdf2image Pillow", file=sys.stderr)
    sys.exit(1)


def create_spread_image(pdf_path: str, left_page: int, right_page: int, border_width: int = 2, quality: int = 50) -> bytes:
    """
    Convert two PDF pages into a single side-by-side image with a black border.
    
    Args:
        pdf_path: Path to the PDF file
        left_page: Left page number (1-based)
        right_page: Right page number (1-based)
        border_width: Width of the black border/separator in pixels
        quality: Image quality/size (50 = half size, 100 = full size, default: 50)
    
    Returns:
        PNG image data as bytes
    """
    # Calculate DPI based on quality parameter (50 = half size, 100 = full size)
    base_dpi = 200
    dpi = int(base_dpi * (quality / 100))
    
    # Ensure minimum DPI for pdf2image compatibility
    dpi = max(dpi, 50)
    
    # Convert PDF pages to images
    pages = convert_from_path(
        pdf_path,
        first_page=left_page,
        last_page=right_page,
        dpi=dpi
    )
    
    if len(pages) < 2:
        raise ValueError(f"Could not extract both pages {left_page} and {right_page}")
    
    left_img = pages[0]
    right_img = pages[1]
    
    # Calculate dimensions for combined image with border
    left_width, left_height = left_img.size
    right_width, right_height = right_img.size
    
    max_height = max(left_height, right_height)
    total_width = left_width + border_width + right_width
    
    # Add outer border (2px on each side)
    outer_border = border_width
    canvas_width = total_width + (outer_border * 2)
    canvas_height = max_height + (outer_border * 2)
    
    # Create canvas with black background
    combined = Image.new('RGB', (canvas_width, canvas_height), color='black')
    
    # Paste left page
    combined.paste(left_img, (outer_border, outer_border))
    
    # Paste right page (after left page + center border)
    combined.paste(right_img, (outer_border + left_width + border_width, outer_border))
    
    # Convert to PNG bytes
    output = BytesIO()
    combined.save(output, format='PNG')
    return output.getvalue()


def _process_spread_params(params: dict):
    """Internal function to validate and process spread parameters"""
    pdf_path = params.get("pdf_path")
    left_page = params.get("left_page")
    right_page = params.get("right_page")
    border_width = params.get("border_width", 2)
    quality = params.get("quality", 50)

    if not pdf_path or left_page is None or right_page is None:
        raise ValueError("Missing required parameters: pdf_path, left_page, right_page")

    # Validate PDF exists
    pdf_file = Path(pdf_path).expanduser()
    if not pdf_file.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    # Create spread image
    image_data = create_spread_image(str(pdf_file), left_page, right_page, border_width, quality)

    return image_data, left_page, right_page


def handle_view_spread(params: dict) -> dict:
    """Handle view_spread tool call - displays spread in IDE"""
    try:
        image_data, left_page, right_page = _process_spread_params(params)

        # Encode as base64 for MCP response
        image_base64 = base64.b64encode(image_data).decode('utf-8')

        return {
            "content": [
                {
                    "type": "image",
                    "data": image_base64,
                    "mimeType": "image/png"
                },
                {
                    "type": "text",
                    "text": f"Double-page spread: pages {left_page}-{right_page}"
                }
            ]
        }
    except Exception as e:
        return {"error": str(e)}


def handle_save_spread(params: dict) -> dict:
    """Handle save_spread tool call - saves spread to specified path"""
    output_path = params.get("output_path")

    if not output_path:
        return {"error": "Missing required parameter: output_path"}

    try:
        image_data, left_page, right_page = _process_spread_params(params)

        # Save to specified path
        output_file = Path(output_path).expanduser()
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(image_data)

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Saved spread (pages {left_page}-{right_page}) to: {output_file}"
                }
            ]
        }
    except Exception as e:
        return {"error": str(e)}


def handle_initialize(params: dict) -> dict:
    """Handle MCP initialize request"""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {}
        },
        "serverInfo": {
            "name": "pdf-spread-viewer",
            "version": "1.0.0"
        }
    }


def handle_list_tools(params: dict) -> dict:
    """Handle MCP tools/list request"""
    return {
        "tools": [
            {
                "name": "view_spread",
                "description": "View two consecutive PDF pages as a single side-by-side image with black borders",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file (can use ~ for home directory)"
                        },
                        "left_page": {
                            "type": "integer",
                            "description": "Left page number (1-based index)"
                        },
                        "right_page": {
                            "type": "integer",
                            "description": "Right page number (1-based index)"
                        },
                        "border_width": {
                            "type": "integer",
                            "description": "Width of black border in pixels (default: 2)",
                            "default": 2
                        },
                        "quality": {
                            "type": "integer",
                            "description": "Image quality/size (50 = half size, 100 = full size, default: 50)",
                            "default": 50
                        }
                    },
                    "required": ["pdf_path", "left_page", "right_page"]
                }
            },
            {
                "name": "save_spread",
                "description": "Save two consecutive PDF pages as a single side-by-side image with black borders to a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file (can use ~ for home directory)"
                        },
                        "left_page": {
                            "type": "integer",
                            "description": "Left page number (1-based index)"
                        },
                        "right_page": {
                            "type": "integer",
                            "description": "Right page number (1-based index)"
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Path where to save the output PNG file"
                        },
                        "border_width": {
                            "type": "integer",
                            "description": "Width of black border in pixels (default: 2)",
                            "default": 2
                        },
                        "quality": {
                            "type": "integer",
                            "description": "Image quality/size (50 = half size, 100 = full size, default: 50)",
                            "default": 50
                        }
                    },
                    "required": ["pdf_path", "left_page", "right_page", "output_path"]
                }
            }
        ]
    }


def handle_call_tool(params: dict) -> dict:
    """Handle MCP tools/call request"""
    tool_name = params.get("name")
    tool_params = params.get("arguments", {})

    if tool_name == "view_spread":
        return handle_view_spread(tool_params)
    elif tool_name == "save_spread":
        return handle_save_spread(tool_params)
    # Keep backward compatibility with old name
    elif tool_name == "get_spread":
        return handle_view_spread(tool_params)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


def main():
    """Main MCP server loop using stdio transport"""
    for line in sys.stdin:
        try:
            request = json.loads(line)
            method = request.get("method")
            params = request.get("params", {})
            request_id = request.get("id")
            
            # Handle different MCP methods
            if method == "initialize":
                result = handle_initialize(params)
            elif method == "tools/list":
                result = handle_list_tools(params)
            elif method == "tools/call":
                result = handle_call_tool(params)
            else:
                result = {"error": f"Unknown method: {method}"}
            
            # Send response
            if request_id is not None:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }
                print(json.dumps(response), flush=True)
            else:
                # For notifications (no id), don't send a response
                pass
            
        except json.JSONDecodeError:
            error_response = {
                "jsonrpc": "2.0",
                "id": request_id if request_id is not None else 0,
                "error": {"code": -32700, "message": "Parse error"}
            }
            print(json.dumps(error_response), flush=True)
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": request_id if request_id is not None else 0,
                "error": {"code": -32603, "message": str(e)}
            }
            print(json.dumps(error_response), flush=True)


if __name__ == "__main__":
    main()

