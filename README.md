# Template for Claude Code

A template repository for buildingusing Claude Code, optimized for Claude Code on the web.

## What is This?

This template provides a development environment and guidelines for building with Claude Code. It includes:

- **Development guidelines** in `claude.md` for best practices

## Quick Start

### Using This Template

1. **Create a new repository from this template**
   - Click "Use this template" on GitHub
   - Or: Clone and start building

2. **Open in a dev container**
   - GitHub Codespaces: Click "Code" → "Create codespace"
   - VS Code: "Reopen in Container"
   - Claude Code on web: Will automatically use the devcontainer

### Development Guide (`claude.md`)

Comprehensive guide covering:
- Val.town essentials (auth, storage, runtime)
- Development methodology (TDD, commits, documentation)
- Technology choices (no React, mobile-responsive)
- Testing strategy
- Project structure recommendations

## Development Philosophy

This template enforces specific best practices:

### ✅ Red-Green-Refactor (TDD)

1. Write failing test → commit
2. Implement feature → commit
3. Refactor → commit

### ✅ Commit Early and Often

- Separate commits for tests and implementation
- Show your work through git history
- Meaningful commit messages

### ✅ Keep Documentation Updated

- README stays current
- API docs reflect actual endpoints
- Architecture notes match reality

### ❌ No React

Val.town vals should be lightweight. Use:
- Vanilla JS/TS
- Web standards
- HTML templates
- Lightweight libraries (htmx, Alpine.js) if needed

### ✅ Mobile-Responsive

Every interface must work on mobile devices.

- **[claude.md](./claude.md)** - Complete development guide

---

**Remember**: Test first. Commit often. No React. Document everything.
