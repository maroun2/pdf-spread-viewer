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


def create_spread_image(pdf_path: str, left_page: int, right_page: int, border_width: int = 2) -> bytes:
    """
    Convert two PDF pages into a single side-by-side image with a black border.
    
    Args:
        pdf_path: Path to the PDF file
        left_page: Left page number (1-based)
        right_page: Right page number (1-based)
        border_width: Width of the black border/separator in pixels
    
    Returns:
        PNG image data as bytes
    """
    # Convert PDF pages to images (high DPI for quality)
    pages = convert_from_path(
        pdf_path,
        first_page=left_page,
        last_page=right_page,
        dpi=200
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


def handle_get_spread(params: dict) -> dict:
    """Handle get_spread tool call"""
    pdf_path = params.get("pdf_path")
    left_page = params.get("left_page")
    right_page = params.get("right_page")
    border_width = params.get("border_width", 2)
    
    if not pdf_path or left_page is None or right_page is None:
        return {
            "error": "Missing required parameters: pdf_path, left_page, right_page"
        }
    
    try:
        # Validate PDF exists
        pdf_file = Path(pdf_path).expanduser()
        if not pdf_file.exists():
            return {"error": f"PDF file not found: {pdf_path}"}
        
        # Create spread image
        image_data = create_spread_image(str(pdf_file), left_page, right_page, border_width)
        
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
                "name": "get_spread",
                "description": "Convert two consecutive PDF pages into a single side-by-side image with black borders",
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
                        }
                    },
                    "required": ["pdf_path", "left_page", "right_page"]
                }
            }
        ]
    }


def handle_call_tool(params: dict) -> dict:
    """Handle MCP tools/call request"""
    tool_name = params.get("name")
    tool_params = params.get("arguments", {})
    
    if tool_name == "get_spread":
        return handle_get_spread(tool_params)
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
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
            print(json.dumps(response), flush=True)
            
        except json.JSONDecodeError:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"}
            }
            print(json.dumps(error_response), flush=True)
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if 'request' in locals() else None,
                "error": {"code": -32603, "message": str(e)}
            }
            print(json.dumps(error_response), flush=True)


if __name__ == "__main__":
    main()

