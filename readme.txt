# 🌟 Gnosis: Advanced Multi-Agent AI Assistant

## Intelligent. Adaptive. Specialized.

Gnosis is a cutting-edge AI assistant featuring **10 specialized agent personas**, **intelligent user profiling**, **cross-agent collaboration**, and **resilient offline-first architecture**. Built for researchers, developers, and curious minds who demand more than generic AI responses.

### 🎯 What Makes Gnosis Different

- **10 Specialized AI Agents** - Each with unique expertise and knowledge bases
- **Smart Agent Suggestions** - Automatically recommends the best agent for your task
- **Persistent Memory System** - Agents remember past conversations and adapt
- **Gentle User Learning** - Builds your profile subtly without being intrusive
- **Cross-Agent Collaboration** - Multiple agents working together on complex tasks
- **Offline-First Design** - Intelligent responses even without internet connectivity
- **Voice Integration** - Natural speech input and text-to-speech output
- **Advanced Learning Paths** - Personalized tutoring with progress tracking

## 🚀 Quick Start

### Prerequisites
- **Python 3.9+** - Check with `python --version`
- **Internet connection** (optional) - Works offline with intelligent fallbacks

### Installation

1. **Clone or download** this repository
2. **Create virtual environment** (recommended):
   ```bash
   python -m venv venv
   # Activate (Mac/Linux):
   source venv/bin/activate
   # Activate (Windows):
   venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Audio setup** (for voice features):
   ```bash
   # Mac/Linux:
   brew install portaudio && pip install pyaudio
   # Windows:
   pip install pipwin && pipwin install pyaudio
   ```

### Launch Gnosis
```bash
./venv/bin/python webagent.py
```

The terminal and GUI launchers automatically use the project's `venv` when it
exists, so `/tts` loads the same `pyttsx3` installation as the rest of Gnosis.

🎉 **You're ready!** Gnosis will greet you with a random fun prompt and suggest the best agent for your needs.

## 🎭 Meet Your Specialized Agents

| Agent | Expertise | When to Use |
|-------|-----------|-------------|
| **🔬 Research Synthesizer** | Cross-references sources, synthesizes viewpoints | Complex research, academic analysis |
| **🧠 Philosophy Bridge** | Ancient wisdom meets modern challenges | Life questions, ethical dilemmas |
| **🌌 Space Consciousness** | Cosmic perspective on human experience | Existential topics, consciousness studies |
| **⚖️ Ethics Advisor** | Multi-framework ethical analysis | Moral decisions, AI ethics |
| **💡 Creative Connector** | Unexpected connections between fields | Innovation, problem-solving |
| **🎓 Master Tutor** | Personalized learning paths | Education, skill development |
| **🔍 Fact Checker** | Verifies claims, identifies misinformation | Truth verification, source checking |
| **😄 Digital Comedian** | Witty observations, appropriate humor | Lightening mood, creative thinking |
| **🛠️ Code Debugger** | Analyzes bugs, suggests fixes | Programming issues, debugging |
| **💚 Digital Counselor** | Emotional support, wellness guidance | Stress management, self-reflection |

## 🎮 Command Reference

### Core Commands
| Command | Function |
|---------|----------|
| `/job [agent]` | Switch to specialized agent (e.g., `/job research`) |
| `/collab [agent1] [agent2]` | Multi-agent collaboration |
| `/profile` | View your adaptive user profile |
| `/voice` | Enable natural speech input |
| `/tts` | Enable text-to-speech responses |

### Learning & Knowledge
| Command | Function |
|---------|----------|
| `/tutor [topic]` | Create personalized learning path |
| `/showpath [topic]` | Display learning progress |
| `/archives [query]` | Search knowledge base |
| `/historian` | Organize knowledge base |

### Special Features
| Command | Function |
|---------|----------|
| `/tarot` | Tree of Life tarot reading with AI interpretation |
| `/news` | Latest headlines with analysis |
| `/reason` | Advanced reasoning mode |
| `/deepthink` | Evidence-led web research with a structured analytical brief |
| `/password [N]` | Generate N secure passwords |

### Self-Improve & Autonomous Features
| Command | Function |
|---------|----------|
| `/selfimprove` | Propose, fix, test, and apply one small repo improvement (never auto-commits) |
| `/selfimprove preview` (or `--dry-run`) | Same, but only previews the verified diff - never touches the live repo |
| `/learning` | Self-improve's recent success rate, failure patterns, and lessons learned |
| `/generate` | Design and sandbox-test a new tool for a recurring capability gap (always a proposal, never auto-registered) |
| `/report` | Observability: task completion, search quality, tool usage, self-improve/tool-generation performance |

Every step above runs inside an isolated `git worktree` sandbox, not the live checkout - see
`docs/selfimprove.md` for the full pipeline and safe-usage notes, and `docs/architecture.md`/
`docs/tools.md`/`docs/skills.md` (generated by `python3 scripts/generate_docs.py`) for what
actually exists right now. The only environment variable in play is `SEARXNG_URL`
(default `https://search.lozdev.com`), used by web search generally.

## 🧠 Intelligent Features

### 🎯 Smart Agent Suggestions
Gnosis analyzes your questions and automatically suggests the most suitable agent:
- Coding problems? → Code Debugger
- Ethical dilemmas? → Ethics Advisor  
- Learning new concepts? → Master Tutor
- Research projects? → Research Synthesizer

### 🔄 Adaptive User Profiling
Your AI assistant learns about you gradually and respectfully:
- **Interests Detection**: Identifies recurring topics
- **Communication Style**: Adapts to your preferences
- **Expertise Recognition**: Notices your areas of knowledge
- **Learning Patterns**: Understands how you like to learn
- **Privacy-First**: Only 10% chance updates, gentle learning approach

### 🤝 Cross-Agent Collaboration
Multiple agents can work together on complex tasks:
```
/collab research ethics creative
```
Combines Research Synthesizer's analysis + Ethics Advisor's moral framework + Creative Connector's innovation

### 🌐 Resilient Search System
- **Offline-First**: Works without internet connection
- **Intelligent Fallbacks**: Contextual responses when search fails
- **Domain Expertise**: Specialized responses for technical topics
- **Network Resilient**: Graceful handling of connectivity issues

### 🧞‍♂️ Personalized Learning Paths
Create custom learning journeys with the Master Tutor:
1. **Assessment**: Evaluates your current knowledge
2. **Path Creation**: Builds step-by-step learning plan
3. **Progress Tracking**: Monitors your advancement
4. **Adaptive Difficulty**: Adjusts based on your pace

### 🔮 Enhanced Tarot System
Tree of Life readings with specialized AI interpretation:
- **10 Sephiroth Positions**: Deep mystical analysis
- **Path Connections**: Major Arcana insights
- **Voice Integration**: Mystical voice for readings
- **Personal Context**: Incorporates your profile for relevance

### 📚 Knowledge Base Management
The Historian agent organizes your accumulated knowledge:
- **Smart Categorization**: Groups similar topics automatically
- **Duplicate Removal**: Cleans redundant information
- **Searchable Archives**: Find past conversations easily
- **Topic Suggestions**: Intelligent search recommendations

## 🎬 Example Interactions

### Automatic Agent Suggestions
```
You: "I'm having trouble with this Python function that keeps throwing errors"
Gnosis: 💡 This looks like a job for the Code Debugger! Switch with `/job debugger`?

You: /job debugger
Debugger: ✨ Switched to Code Debugger agent. 
Let me analyze your code systematically and help identify the issue...
```

### Cross-Agent Collaboration
```
You: /collab research ethics
Gnosis: Multi-agent collaboration activated!
🔬 Research Synthesizer will analyze evidence
⚖️ Ethics Advisor will examine moral implications  
Working together to provide comprehensive analysis...
```

### Adaptive Learning
```
You: "Tell me about machine learning"
Gnosis: I notice you've been exploring AI topics lately. 
Would you like me to create a personalized learning path? [/tutor machine learning]
Based on your communication style, I'll focus on practical applications...
```

## 🔧 Troubleshooting

### Common Issues

**🎤 Audio Problems**
- Check microphone permissions
- Reinstall PyAudio: `brew install portaudio && pip install pyaudio` (Mac/Linux)
- For Windows: `pip install pipwin && pipwin install pyaudio`
- Missing `mpg123` (used for MP3 sound effects on Linux only — macOS uses the built-in `afplay`): `apt install mpg123` (Linux)
- `SpeechRecognition` fails with `ModuleNotFoundError: No module named 'aifc'` on Python 3.13+: run `pip install standard-aifc audioop-lts`
- `sr.Microphone()` fails with `No module named 'pyaudio'`: `brew install portaudio && pip install pyaudio` (Mac/Linux)
- `sr.Microphone()` fails with `No module named 'distutils'` on Python 3.12+: run `pip install setuptools`

**🌐 Network Issues**
- Gnosis works offline! Intelligent fallbacks provide contextual responses
- For search features: Check internet connection
- Reinstall search dependencies: `pip install requests beautifulsoup4`

**🔊 Text-to-Speech Issues**
- Enable TTS mode: `/tts`
- Check system audio settings
- Try different voice settings in the configuration

**🤖 Agent Memory Issues**
- Agent memory is stored in `agent_memory/` folder
- Clear memory by deleting `[agent]_memory.json` files if needed
- User profile stored in `user_details.log` - edit manually if needed

## 🚀 Advanced Features

### 💾 Memory System
- **Agent Memory**: Each agent remembers past conversations
- **Context Awareness**: Agents reference relevant previous discussions
- **Learning Integration**: Knowledge builds over time

### 🎯 Smart Context
- **User Profiling**: Gradual learning about your preferences
- **Communication Adaptation**: Matches your preferred response style
- **Interest Tracking**: Identifies recurring topics and expertise areas

### 🛡️ Privacy & Control
- **Gentle Learning**: Only 10% of interactions update your profile
- **Local Storage**: All data stored locally on your machine
- **Full Control**: Edit `user_details.log` to modify your profile anytime

## 🌟 What's Next

The Gnosis project continues to evolve with exciting planned features:

- **🤖 Multi-Modal AI**: Vision and document analysis capabilities
- **🔗 Plugin System**: Community-developed agent extensions  
- **📊 Analytics Dashboard**: Insight into your learning patterns
- **🌍 Cloud Sync**: Optional profile synchronization across devices
- **🎮 Interactive Learning**: Gamified educational experiences

---

## 📚 About This Project

**Gnosis** represents the next evolution of AI assistants - from generic chatbots to specialized, intelligent companions that adapt and learn alongside you.

**Developer**: Enhanced by the AI development community  
**License**: Open source - contribute on GitHub  
**Last Updated**: December 19, 2025

*"Knowledge is power, but Gnosis is wisdom."*

Ready to explore the depths of AI-assisted learning and discovery? Launch Gnosis and begin your journey toward enhanced knowledge and understanding.

```bash
python webagent.py
```

🌟 **Welcome to the future of personalized AI assistance.**
