# WebAgent GUI

Modern graphical interface for the WebAgent AI assistant.

## Quick Start

```bash
# Run the GUI
./run_gui.sh

# Or directly with Python
./venv/bin/python webagent_gui.py
```

## Features

- 💬 **Chat Interface** - Clean, modern chat window with history
- 🎤 **Voice Mode** - Enable voice input (when microphone available)
- 🔊 **Text-to-Speech** - Have responses read aloud
- 🔍 **Web Search** - Enable web searching for answers
- 🧠 **Reasoning Mode** - Advanced reasoning for complex queries
- ⚙️ **Model Selection** - Switch between different AI modes
- ⌨️ **Keyboard Shortcuts** - Press Ctrl+Enter to send messages

## Requirements

- Python 3.12+
- PyQt6 (automatically installed via requirements.txt)
- All dependencies from requirements.txt

## Troubleshooting

If you get "No module named 'PyQt6'", reinstall with:
```bash
./venv/bin/python3.12 -m pip install PyQt6
```

## Interface Guide

**Control Panel**
- Toggle voice input, TTS, web search, and reasoning modes
- Select between Standard, Unfiltered, Reasoning, and Coding models

**Chat Display**
- Shows full conversation history
- User messages in blue, AI responses in gray
- Timestamps for all messages

**Input Area**
- Type your message
- Press Ctrl+Enter or click "Send Message" button
- Clear chat history with the "Clear Chat" button

Enjoy chatting with WebAgent! 🤖
