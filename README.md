# nb-lsp

An LSP server for [nb](https://xwmx.github.io/nb/), the command-line note-taking, bookmarking, and knowledge base application.

## Features

### Wiki-style Links `[[...]]`

- **Completion**: Trigger with `[[` to complete note titles, IDs, filenames, and notebook references
- **Go to Definition**: Jump to linked notes
- **Diagnostics**: Detect broken links

Supported link formats (all valid nb selectors):
- `[[My Note Title]]` — by title (preferred)
- `[[123]]` — by ID
- `[[filename.md]]` — by filename
- `[[notebook:Title]]` — cross-notebook reference
- `[[folder/Title]]` — folder path

### Tags `#...`

- **Completion**: Trigger with `#` to complete existing tags
- Supports nested tags like `#project/design/ui`

## Installation

```bash
# Clone the repository
git clone https://github.com/benswift/nb-lsp.git
cd nb-lsp

# Install with uv
uv sync

# Or install with pip
pip install -e .
```

## Usage

### Running the Server

```bash
nb-lsp
```

The server communicates over stdio using the Language Server Protocol.

### Editor Configuration

#### Neovim (with nvim-lspconfig)

```lua
local lspconfig = require('lspconfig')
local configs = require('lspconfig.configs')

if not configs.nb_lsp then
  configs.nb_lsp = {
    default_config = {
      cmd = { 'nb-lsp' },
      filetypes = { 'markdown' },
      root_dir = function(fname)
        return lspconfig.util.find_git_ancestor(fname) or vim.fn.getcwd()
      end,
    },
  }
end

lspconfig.nb_lsp.setup{}
```

#### VS Code

Create a `.vscode/settings.json`:

```json
{
  "languageserver": {
    "nb-lsp": {
      "command": "nb-lsp",
      "filetypes": ["markdown"]
    }
  }
}
```

#### Helix

Add to `~/.config/helix/languages.toml`:

```toml
[language-server.nb-lsp]
command = "nb-lsp"

[[language]]
name = "markdown"
language-servers = ["marksman", "nb-lsp"]
```

This configures Helix to use both [Marksman](https://github.com/artempyanykh/marksman) (for general markdown features) and nb-lsp (for nb-specific features) on all markdown files.

Since nb stores notes as plain markdown files (typically in `~/.nb/`), the LSP will work automatically when you open any note with `nb edit` or directly in Helix. The nb-lsp features (wiki-link completion, tag completion, go-to-definition) activate when you're editing files within an nb notebook directory.

If you only want nb-lsp for files in your nb directory, you can create a `.helix/languages.toml` in your nb home folder (`~/.nb/` by default, or `$NB_DIR` if set):

```toml
[language-server.nb-lsp]
command = "nb-lsp"

[[language]]
name = "markdown"
language-servers = ["nb-lsp", "marksman"]
```

This gives nb-lsp priority for completion results in your notebooks while keeping your global markdown config unchanged.

## Development

### Setup

```bash
uv sync
```

### Running Tests

```bash
uv run pytest
```

### Project Structure

```
nb-lsp/
├── src/nb_lsp/
│   ├── __init__.py
│   ├── server.py      # LSP server and handlers
│   ├── nb.py          # nb CLI wrapper
│   └── selectors.py   # Wiki link parsing
├── tests/
│   ├── test_server.py
│   ├── test_nb.py
│   └── test_selectors.py
└── pyproject.toml
```

## Requirements

- Python 3.11+
- [nb](https://xwmx.github.io/nb/) installed and available in PATH
- pygls

## License

MIT
