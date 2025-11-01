#!/usr/bin/env python3
"""
PDF Spread Viewer MCP Server
Converts PDF double-page spreads into single images with borders
"""

import sys
import json
import base64
import math
from io import BytesIO
from pathlib import Path

try:
    from pdf2image import convert_from_path
    from PIL import Image
    import fitz
    from kontrasto import wcag_2
    from kontrasto.contrast import get_dominant_color
    from kontrasto.convert import to_hex
except ImportError as e:
    print(f"Error: Required packages not installed: {e}", file=sys.stderr)
    print("Install with: pip install pdf2image Pillow PyMuPDF kontrasto", file=sys.stderr)
    sys.exit(1)


def _color_int_to_rgb(color_value) -> tuple[int, int, int]:
    """Convert PyMuPDF span color integers to RGB tuples."""
    if hasattr(color_value, "to_rgb_tuple"):
        color_value = color_value.to_rgb_tuple()
    elif hasattr(color_value, "rgb"):
        rgb_attr = color_value.rgb
        color_value = rgb_attr() if callable(rgb_attr) else rgb_attr

    if isinstance(color_value, (tuple, list)):
        components = []
        for channel in list(color_value)[:3]:
            if isinstance(channel, float) and 0.0 <= channel <= 1.0:
                components.append(int(round(channel * 255)))
            else:
                try:
                    components.append(int(channel))
                except (TypeError, ValueError):
                    components.append(0)
        while len(components) < 3:
            components.append(0)
        return tuple(max(0, min(255, c)) for c in components[:3])

    try:
        color_int = int(color_value)
    except (TypeError, ValueError):
        color_int = 0

    if color_int < 0:
        color_int = 0

    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    return (r, g, b)


def analyze_page_contrast(pdf_path: str, left_page: int, right_page: int, quality: int = 50):
    """
    Analyze contrast for individual text regions extracted directly from the PDF.

    Args:
        pdf_path: Path to PDF file
        left_page, right_page: Page numbers (1-based)
        quality: Image quality for rendering (50 = ~100 DPI, 100 = ~200 DPI)

    Returns:
        dict: Analysis results with per-region dominant background color and contrast ratios
    """
    if left_page > right_page:
        raise ValueError("left_page cannot be greater than right_page")

    base_dpi = 200
    dpi = int(base_dpi * (quality / 100))
    dpi = max(dpi, 72)
    scale = dpi / 72.0

    results = {"pages": []}

    with fitz.open(pdf_path) as document:
        num_pages = document.page_count
        if left_page < 1 or right_page > num_pages:
            raise IndexError(f"Page range {left_page}-{right_page} is outside document (1-{num_pages})")

        for page_number in range(left_page, right_page + 1):
            page = document[page_number - 1]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            page_image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
            page_dict = page.get_text("dict")

            regions = []
            region_counter = 0

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text_content = span.get("text", "")
                        if not text_content.strip():
                            continue

                        bbox = span.get("bbox")
                        if not bbox or len(bbox) != 4:
                            continue

                        x0, y0, x1, y1 = bbox
                        width = x1 - x0
                        height = y1 - y0
                        if width <= 0 or height <= 0:
                            continue

                        padding_points = max(1.5, min(6.0, 0.15 * height))
                        padded_bbox = (
                            x0 - padding_points,
                            y0 - padding_points,
                            x1 + padding_points,
                            y1 + padding_points
                        )

                        left = max(int(math.floor(padded_bbox[0] * scale)), 0)
                        top = max(int(math.floor(padded_bbox[1] * scale)), 0)
                        right = min(int(math.ceil(padded_bbox[2] * scale)), page_image.width)
                        bottom = min(int(math.ceil(padded_bbox[3] * scale)), page_image.height)

                        if right - left < 2 or bottom - top < 2:
                            continue

                        region_image = page_image.crop((left, top, right, bottom))
                        dominant_rgb = _color_int_to_rgb(get_dominant_color(region_image))
                        region_image.close()
                        dominant_hex = to_hex(dominant_rgb)

                        text_rgb = _color_int_to_rgb(span.get("color"))
                        text_hex = to_hex(text_rgb)

                        contrast_ratio = wcag_2.wcag2_contrast(text_hex, dominant_hex)

                        wcag_compliance = {
                            "aa_normal_text": contrast_ratio >= 4.5,
                            "aa_large_text": contrast_ratio >= 3.0,
                            "aaa_normal_text": contrast_ratio >= 7.0,
                            "aaa_large_text": contrast_ratio >= 4.5
                        }

                        region_counter += 1
                        regions.append({
                            "region_index": region_counter,
                            "text": text_content.strip(),
                            "bbox_pdf_points": {
                                "x0": round(x0, 2),
                                "y0": round(y0, 2),
                                "x1": round(x1, 2),
                                "y1": round(y1, 2)
                            },
                            "bbox_pixels": {
                                "left": left,
                                "top": top,
                                "right": right,
                                "bottom": bottom
                            },
                            "text_color": {
                                "hex": text_hex,
                                "rgb": list(text_rgb)
                            },
                            "background_color": {
                                "hex": dominant_hex,
                                "rgb": list(dominant_rgb)
                            },
                            "contrast_ratio": round(contrast_ratio, 2),
                            "wcag_compliance": wcag_compliance
                        })

            results["pages"].append({
                "page_number": page_number,
                "image_dimensions": {
                    "width": page_image.width,
                    "height": page_image.height,
                    "dpi": dpi
                },
                "regions_analyzed": len(regions),
                "regions": regions
            })

            page_image.close()

    return results


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


def handle_analyze_contrast(params: dict) -> dict:
    """Handle analyze_contrast tool call - analyzes per-text-region contrast with kontrasto"""
    pdf_path = params.get("pdf_path")
    left_page = params.get("left_page")
    right_page = params.get("right_page")
    quality = params.get("quality", 50)

    if not pdf_path or left_page is None or right_page is None:
        return {"error": "Missing required parameters: pdf_path, left_page, right_page"}

    try:
        # Validate PDF exists
        pdf_file = Path(pdf_path).expanduser()
        if not pdf_file.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Analyze contrast
        results = analyze_page_contrast(str(pdf_file), left_page, right_page, quality)

        # Format summary text
        summary_parts = []
        for page_data in results["pages"]:
            page_num = page_data["page_number"]
            regions = page_data["regions"]

            if not regions:
                summary_parts.append(f"Page {page_num}: No text regions detected.")
                continue

            summary_parts.append(f"Page {page_num}: analyzed {len(regions)} text regions.")

            for region in regions[:5]:
                snippet = " ".join(region["text"].split())
                if len(snippet) > 80:
                    snippet = snippet[:77] + "..."
                summary_parts.append(
                    f'  Region {region["region_index"]}: "{snippet}" '
                    f'contrast {region["contrast_ratio"]}:1 '
                    f'({region["text_color"]["hex"]} text vs {region["background_color"]["hex"]})'
                )

            if len(regions) > 5:
                summary_parts.append(f"  … {len(regions) - 5} more regions on page {page_num}")

        summary_text = "\n".join(summary_parts)

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Contrast Analysis (Pages {left_page}-{right_page}):\n\n{summary_text}"
                },
                {
                    "type": "text",
                    "text": f"\nDetailed results:\n{json.dumps(results, indent=2)}"
                }
            ]
        }
    except Exception as e:
        return {"error": str(e)}


def handle_get_wcag_report(params: dict) -> dict:
    """Handle get_wcag_report tool call - returns JSON report of all non-compliant WCAG regions grouped by page"""
    pdf_path = params.get("pdf_path")
    start_page = params.get("start_page", 1)
    quality = params.get("quality", 50)

    if not pdf_path:
        return {"error": "Missing required parameter: pdf_path"}

    try:
        # Validate PDF exists
        pdf_file = Path(pdf_path).expanduser()
        if not pdf_file.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Get page count
        with fitz.open(str(pdf_file)) as doc:
            total_pages = doc.page_count

        # Build report of non-compliant regions grouped by page
        report = {
            "pdf_path": str(pdf_file),
            "total_pages": total_pages,
            "start_page": start_page,
            "pages_analyzed": 0,
            "non_compliant_regions_count": 0,
            "pages_with_issues": []
        }

        # Analyze pages in pairs starting from start_page
        for left_page in range(start_page, total_pages + 1, 2):
            right_page = min(left_page + 1, total_pages)
            report["pages_analyzed"] += (right_page - left_page + 1)

            try:
                results = analyze_page_contrast(str(pdf_file), left_page, right_page, quality)

                for page_data in results["pages"]:
                    page_num = page_data["page_number"]
                    non_compliant_regions = []

                    for region in page_data.get("regions", []):
                        wcag = region.get("wcag_compliance", {})

                        # Check if it fails any WCAG standard
                        fails_aa_normal = not wcag.get("aa_normal_text", True)
                        fails_aa_large = not wcag.get("aa_large_text", True)
                        fails_aaa_normal = not wcag.get("aaa_normal_text", True)
                        fails_aaa_large = not wcag.get("aaa_large_text", True)

                        if fails_aa_normal or fails_aa_large or fails_aaa_normal or fails_aaa_large:
                            non_compliant_regions.append({
                                "region_index": region["region_index"],
                                "text": region["text"].strip(),
                                "contrast_ratio": round(region["contrast_ratio"], 2),
                                "text_color": {
                                    "hex": region["text_color"]["hex"],
                                    "rgb": region["text_color"]["rgb"]
                                },
                                "background_color": {
                                    "hex": region["background_color"]["hex"],
                                    "rgb": region["background_color"]["rgb"]
                                },
                                "wcag_failures": {
                                    "aa_normal_text": fails_aa_normal,
                                    "aa_large_text": fails_aa_large,
                                    "aaa_normal_text": fails_aaa_normal,
                                    "aaa_large_text": fails_aaa_large
                                },
                                "bbox_pdf_points": region["bbox_pdf_points"],
                                "bbox_pixels": region["bbox_pixels"]
                            })

                    if non_compliant_regions:
                        report["pages_with_issues"].append({
                            "page_number": page_num,
                            "regions_count": len(non_compliant_regions),
                            "regions": non_compliant_regions
                        })
                        report["non_compliant_regions_count"] += len(non_compliant_regions)

            except Exception as e:
                # Continue with other pages even if one fails
                continue

        # Sort pages by page number
        report["pages_with_issues"].sort(key=lambda x: x["page_number"])

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(report, indent=2)
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
            },
            {
                "name": "analyze_contrast",
                "description": "Analyze overall page contrast using dominant color extraction and WCAG standards",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file (can use ~ for home directory)"
                        },
                        "left_page": {
                            "type": "integer",
                            "description": "First page number to analyze (1-based index)"
                        },
                        "right_page": {
                            "type": "integer",
                            "description": "Last page number to analyze (1-based index)"
                        },
                        "quality": {
                            "type": "integer",
                            "description": "Image quality for analysis (50 = half size, 100 = full size, default: 50)",
                            "default": 50
                        }
                    },
                    "required": ["pdf_path", "left_page", "right_page"]
                }
            },
            {
                "name": "get_wcag_report",
                "description": "Get a JSON report of all non-compliant WCAG contrast regions in the PDF, grouped by page",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file (can use ~ for home directory)"
                        },
                        "start_page": {
                            "type": "integer",
                            "description": "Page number to start analysis from (1-based index, default: 1)",
                            "default": 1
                        },
                        "quality": {
                            "type": "integer",
                            "description": "Image quality for analysis (50 = half size, 100 = full size, default: 50)",
                            "default": 50
                        }
                    },
                    "required": ["pdf_path"]
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
    elif tool_name == "analyze_contrast":
        return handle_analyze_contrast(tool_params)
    elif tool_name == "get_wcag_report":
        return handle_get_wcag_report(tool_params)
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
