"""
GUI for WebAgent - Modern chat interface with voice and web search capabilities
"""

import sys
import threading
import asyncio
from datetime import datetime
try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTextEdit, QPushButton, QLabel, QCheckBox, QComboBox, QScrollArea,
        QFrame, QMessageBox, QStatusBar
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QThread
    from PyQt6.QtGui import QFont, QTextCursor, QGuiApplication
except ModuleNotFoundError as e:
    raise SystemExit("PyQt6 is required to run the GUI. Install it with `pip install PyQt6`.") from e

import webagent


class ResponseWorker(QThread):
    """Worker thread for handling AI responses"""
    response_chunk = pyqtSignal(str)  # Emits each chunk as it arrives
    response_ready = pyqtSignal(str)  # Emits complete response
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, user_input):
        super().__init__()
        self.user_input = user_input

    def run(self):
        try:
            ollama_client = webagent.ollama
            if ollama_client is None:
                raise RuntimeError("Ollama client is unavailable. Please install and configure ollama.")

            # Check if web search is enabled
            if webagent.web_search_mode:
                # Use conversational search which integrates web results
                try:
                    response = webagent.perform_conversational_search(self.user_input)
                    self.response_chunk.emit(response)
                    self.response_ready.emit(response)
                    return
                except Exception as e:
                    # Fallback to normal mode if search fails
                    print(f"Search failed, using normal mode: {e}")
            
            # Normal mode (no web search)
            # Add user message to conversation
            webagent.assistant_convo.append({
                "role": "user",
                "content": self.user_input
            })
            
            # Determine model based on mode
            if webagent.unfiltered_mode:
                chosen_model = webagent.MODELS["unfiltered"]
            elif webagent.reasoning_mode:
                chosen_model = webagent.MODELS["search"]
            else:
                chosen_model = webagent.MODELS["main"]
            
            # Stream response and emit chunks
            complete_response = ""
            response_stream = ollama_client.chat(model=chosen_model, messages=webagent.assistant_convo, stream=True)
            
            for chunk in response_stream:
                text_chunk = chunk["message"]["content"]
                complete_response += text_chunk
                self.response_chunk.emit(text_chunk)  # Emit each chunk
            
            # Save complete response to conversation
            webagent.assistant_convo.append({"role": "assistant", "content": complete_response})
            self.response_ready.emit(complete_response)
            
        except Exception as e:
            self.error_occurred.emit(f"Error: {str(e)}")
        finally:
            self.finished.emit()




class WebAgentGUI(QMainWindow):
    """Main GUI window for WebAgent"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🤖 WebAgent - AI Assistant")
        self.setGeometry(100, 100, 1000, 700)
        self.setStyleSheet(self.get_stylesheet())
        
        self.response_worker = None
        self.search_worker = None
        self.current_response = ""
        self.assistant_message_started = False
        
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)
        
        # Header - simple and clean
        header_layout = QHBoxLayout()
        title_label = QLabel("💬 WebAgent")
        title_font = QFont("Arial", 16, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #333;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        # Compact mode toggles
        self.voice_check = QCheckBox("🎤 Voice")
        self.voice_check.toggled.connect(self.toggle_voice_mode)
        if not webagent.has_speech_recognition:
            self.voice_check.setEnabled(False)
            self.voice_check.setToolTip("Speech recognition is unavailable when SpeechRecognition is not installed.")
        header_layout.addWidget(self.voice_check)

        self.web_search_check = QCheckBox("🔍 Web")
        self.web_search_check.toggled.connect(self.toggle_web_search)
        if not webagent.has_duckduckgo:
            self.web_search_check.setToolTip("DuckDuckGo is not installed; web search will use offline fallback behavior.")
        header_layout.addWidget(self.web_search_check)
        
        self.reasoning_check = QCheckBox("🧠 Deep")
        self.reasoning_check.toggled.connect(self.toggle_reasoning_mode)
        header_layout.addWidget(self.reasoning_check)

        self.unfiltered_check = QCheckBox("🕵️‍♂️ Unfiltered")
        self.unfiltered_check.toggled.connect(self.toggle_unfiltered_mode)
        header_layout.addWidget(self.unfiltered_check)

        self.coding_check = QCheckBox("💻 Code")
        self.coding_check.toggled.connect(self.toggle_coding_mode)
        header_layout.addWidget(self.coding_check)

        self.tts_check = QCheckBox("🔊 TTS")
        self.tts_check.toggled.connect(self.toggle_tts_mode)
        if not webagent.has_pyttsx3:
            self.tts_check.setEnabled(False)
            self.tts_check.setToolTip("TTS is unavailable when pyttsx3 is not installed.")
        header_layout.addWidget(self.tts_check)
        
        clear_button = QPushButton("🗑️")
        clear_button.setMaximumWidth(40)
        clear_button.setToolTip("Clear chat")
        clear_button.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        clear_button.clicked.connect(self.clear_chat)
        header_layout.addWidget(clear_button)
        
        main_layout.addLayout(header_layout)

        agent_layout = QHBoxLayout()
        agent_layout.setSpacing(8)
        agent_label = QLabel("Agent:")
        agent_layout.addWidget(agent_label)

        self.agent_combo = QComboBox()
        self.agent_combo.addItem("default")
        for agent_key in webagent.AVAILABLE_AGENTS:
            self.agent_combo.addItem(agent_key)
        agent_layout.addWidget(self.agent_combo)

        set_agent_button = QPushButton("Set")
        set_agent_button.setMaximumWidth(60)
        set_agent_button.clicked.connect(self.set_agent)
        agent_layout.addWidget(set_agent_button)

        self.current_agent_label = QLabel("Current: default")
        self.current_agent_label.setStyleSheet("color: #555; font-size: 12px;")
        agent_layout.addWidget(self.current_agent_label)
        agent_layout.addStretch()

        main_layout.addLayout(agent_layout)
        
        # Chat display area - conversational style
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 15px;
                font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        main_layout.addWidget(self.chat_display)
        
        # Input area - compact and clean
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)
        
        self.input_text = QTextEdit()
        self.input_text.setMaximumHeight(50)
        self.input_text.setPlaceholderText("Type your message... (Ctrl+Enter to send)")
        self.input_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f8f8;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 10px;
                font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #0084ff;
                background-color: white;
            }
        """)
        self.input_text.installEventFilter(self)
        input_layout.addWidget(self.input_text)
        
        send_button = QPushButton("Send")
        send_button.setMaximumWidth(80)
        send_button.setMinimumHeight(50)
        send_button.setStyleSheet("""
            QPushButton {
                background-color: #0084ff;
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #0073e6;
            }
            QPushButton:pressed {
                background-color: #005cc3;
            }
        """)
        send_button.clicked.connect(self.send_message)
        input_layout.addWidget(send_button)
        
        main_layout.addLayout(input_layout)
        
        # Hint label
        hint_label = QLabel("💡 Ctrl+Enter to send")
        hint_label.setStyleSheet("color: #999; font-size: 11px;")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(hint_label)
        
    def eventFilter(self, source, event):
        if source is self.input_text and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self.send_message()
                return True
        return super().eventFilter(source, event)
    
    def send_message(self):
        """Send user message and get AI response"""
        user_input = self.input_text.toPlainText().strip()
        
        if not user_input:
            QMessageBox.warning(self, "Empty Input", "Please enter a message.")
            return
        
        # Display user message
        self.display_message(user_input, is_user=True)
        self.input_text.clear()
        
        # Disable input while processing
        self.input_text.setEnabled(False)
        
        # Initialize streaming response placeholder
        self.current_response = ""
        self.assistant_message_started = False
        self.response_start_time = datetime.now()
        
        # Start response worker
        self.response_worker = ResponseWorker(user_input)
        self.response_worker.response_chunk.connect(self.on_response_chunk)
        self.response_worker.response_ready.connect(self.on_response_ready)
        self.response_worker.error_occurred.connect(self.on_error)
        self.response_worker.finished.connect(self.on_response_finished)
        self.response_worker.start()
    
    def on_response_chunk(self, chunk):
        """Handle streaming response chunks"""
        self.current_response += chunk

        if not self.assistant_message_started:
            timestamp = self.response_start_time.strftime("%H:%M")
            cursor = self.chat_display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertHtml(
                f'<div style="margin: 10px 0;"><span style="color: #666; font-weight: bold;">Assistant</span> '
                f'<span style="color: #999; font-size: 11px;">{timestamp}</span><br/>'
                f'<span style="color: #333;">'
            )
            self.assistant_message_started = True

        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(chunk)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()
    
    def on_response_ready(self, response):
        """Handle complete AI response"""
        # Close the div tag for the assistant message
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml('</span></div>')
        self.chat_display.setTextCursor(cursor)
        
        # Response already displayed via streaming, just reset state
        self.current_response = ""
    
    def on_response_finished(self):
        """Handle response completion"""
        self.input_text.setEnabled(True)
        self.input_text.setFocus()
    
    def on_error(self, error_msg):
        """Handle errors"""
        QMessageBox.critical(self, "Error", error_msg)
        self.input_text.setEnabled(True)

    def set_agent(self):
        selected = self.agent_combo.currentText()
        result = webagent.job_command(selected if selected != "default" else "default")
        self.current_agent_label.setText(f"Current: {selected}")
        self.display_message(result, is_user=False)
        if webagent.current_agent:
            self.agent_combo.setCurrentText(webagent.current_agent)
        else:
            self.agent_combo.setCurrentText("default")

    def toggle_unfiltered_mode(self, checked):
        if checked:
            self.reasoning_check.setChecked(False)
            self.coding_check.setChecked(False)
        webagent.unfiltered_mode = checked

    def toggle_coding_mode(self, checked):
        if checked:
            self.reasoning_check.setChecked(False)
            self.unfiltered_check.setChecked(False)
        webagent.coding_mode = checked

    def display_message(self, text, is_user=True):
        """Display a message in the chat with conversational styling"""
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        timestamp = datetime.now().strftime("%H:%M")
        
        if is_user:
            formatted_text = f'<div style="margin: 10px 0; text-align: right;"><span style="color: #0084ff; font-weight: bold;">You</span> <span style="color: #999; font-size: 11px;">{timestamp}</span><br/><span style="color: #333;">{text}</span></div>'
        else:
            formatted_text = f'<div style="margin: 10px 0;"><span style="color: #666; font-weight: bold;">Assistant</span> <span style="color: #999; font-size: 11px;">{timestamp}</span><br/><span style="color: #333;">{text}</span></div>'
        
        cursor.insertHtml(formatted_text)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()
    
    def clear_chat(self):
        """Clear chat history"""
        reply = QMessageBox.question(
            self,
            "Clear Chat",
            "Are you sure you want to clear the chat history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.chat_display.clear()
            webagent.assistant_convo = [webagent.sys_msgs.assistant_msg]
    
    def toggle_voice_mode(self, checked):
        """Toggle voice input mode"""
        webagent.voice_mode = checked
        if checked and self.tts_check.isChecked():
            self.tts_check.setChecked(False)

    def toggle_tts_mode(self, checked):
        """Toggle text-to-speech mode"""
        webagent.tts_mode = checked
        if checked and self.voice_check.isChecked():
            self.voice_check.setChecked(False)

    def toggle_web_search(self, checked):
        """Toggle web search mode"""
        webagent.web_search_mode = checked

    def toggle_reasoning_mode(self, checked):
        """Toggle reasoning mode"""
        if checked:
            self.unfiltered_check.setChecked(False)
            self.coding_check.setChecked(False)
        webagent.reasoning_mode = checked
    
    def get_stylesheet(self):
        """Return custom stylesheet for the application"""
        return """
            QMainWindow {
                background-color: #ffffff;
            }
            QLabel {
                color: #333;
                font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
            }
            QTextEdit {
                font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
                border-radius: 5px;
            }
            QComboBox {
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 5px;
                background-color: white;
            }
            QCheckBox {
                color: #333;
                font-size: 11px;
            }
            QStatusBar {
                background-color: #f0f0f0;
                color: #333;
            }
        """


def main():
    """Main entry point"""
    if not QGuiApplication.screens():
        raise SystemExit("No display detected. The GUI requires a graphical desktop environment to run.")

    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle('Fusion')
    
    window = WebAgentGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
