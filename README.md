# PDF Spread Viewer MCP Server

A simple MCP (Model Context Protocol) server that converts PDF double-page spreads into single images with black borders, perfect for reviewing book layouts.

## Features

- Convert two consecutive PDF pages into one side-by-side image
- Add black borders to simulate book binding/gutter
- High-quality output (200 DPI)
- Simple stdio-based MCP server (no web server needed)
- Returns images directly in MCP responses

## Installation

### Prerequisites

Make sure you have Python 3.7+ and `poppler` installed:

```bash
# macOS
brew install poppler

# Ubuntu/Debian
sudo apt-get install poppler-utils

# Windows
# Download from: https://github.com/oschwartz10612/poppler-windows/releases
```

### Install Python Dependencies

```bash
cd ~/projects/pdf-spread-viewer
pip install -r requirements.txt
```

Or manually:
```bash
pip install pdf2image Pillow
```

## Usage

### As MCP Server in Cursor

Add to your Cursor MCP configuration:

```json
{
  "mcpServers": {
    "pdf-spread-viewer": {
      "command": "python3",
      "args": ["/Users/rmi/projects/pdf-spread-viewer/server.py"]
    }
  }
}
```

Then restart Cursor and use the `get_spread` tool:

```
Show me pages 14-15 of embers_final.pdf as a double-page spread
```

### Standalone Script

You can also use it as a standalone script:

```bash
python3 server.py
```

Then send JSON-RPC requests via stdin:

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_spread", "arguments": {"pdf_path": "~/projects/books/dragon-fly/embers_final.pdf", "left_page": 14, "right_page": 15}}}
```

## Tool Parameters

### `get_spread`

Converts two PDF pages into a single side-by-side image.

**Parameters:**
- `pdf_path` (string, required): Path to PDF file (supports `~` for home directory)
- `left_page` (integer, required): Left page number (1-based)
- `right_page` (integer, required): Right page number (1-based)
- `border_width` (integer, optional): Border width in pixels (default: 2)

**Returns:**
- PNG image showing both pages side-by-side with black borders

## Example Output

The tool creates images that look like this:
```
┌──────────────────────────────────────────────┐
│  ┌──────────┐ │ ┌──────────┐                │
│  │ Page 14  │ │ │ Page 15  │                │
│  │  (text)  │ │ │  (image) │                │
│  └──────────┘ │ └──────────┘                │
└──────────────────────────────────────────────┘
     Left page      Right page
```

The black border in the center simulates the book's gutter/binding.

## License

MIT License - feel free to use and modify!

## Contributing

This is an open-source project. PRs welcome!

Repository: https://github.com/yourusername/pdf-spread-viewer (update with actual URL)

## Troubleshooting

**Error: "pdf2image not found"**
```bash
pip install pdf2image Pillow
```

**Error: "poppler not found"**
```bash
brew install poppler  # macOS
```

**Error: "PDF file not found"**
- Use absolute paths or `~` for home directory
- Check file exists with `ls -la path/to/file.pdf`

