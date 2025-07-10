#!/usr/bin/env python3
import json
import os
import sys
import requests
import hashlib
from pathlib import Path
from datetime import datetime

class AIAssistant:
    def __init__(self):
        self.context_dir = Path(".ai-context")
        self.context_dir.mkdir(exist_ok=True)
        self.ollama_url = "http://localhost:11434/api/generate"
        
        # File paths
        self.index_file = self.context_dir / "codebase_index.json"
        self.hashes_file = self.context_dir / "file_hashes.json"
        self.history_file = self.context_dir / "conversation_history.json"
        
        # Supported file types
        self.code_extensions = {'.py', '.js', '.jsx', '.ts', '.tsx', '.html', '.css', '.json', '.md', '.sql', '.yaml', '.yml', '.dockerfile', '.txt'}
        
    def get_file_hash(self, filepath):
        """Get MD5 hash of file content"""
        try:
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return None
    
    def scan_codebase(self):
        """Scan project files and build index"""
        print("Scanning codebase...")
        
        index = {}
        current_hashes = {}
        
        # Load existing hashes
        old_hashes = {}
        if self.hashes_file.exists():
            with open(self.hashes_file, 'r') as f:
                old_hashes = json.load(f)
        
        # Scan all files
        for root, dirs, files in os.walk('.'):
            # Skip hidden directories and common ignore patterns
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv', 'env']]
            
            for file in files:
                filepath = Path(root) / file
                
                # Only process code files
                if filepath.suffix.lower() in self.code_extensions:
                    rel_path = str(filepath.relative_to('.'))
                    
                    # Get file hash
                    file_hash = self.get_file_hash(filepath)
                    if not file_hash:
                        continue
                        
                    current_hashes[rel_path] = file_hash
                    
                    # Only re-index if file changed
                    if rel_path in old_hashes and old_hashes[rel_path] == file_hash:
                        continue
                    
                    print(f"Indexing: {rel_path}")
                    
                    # Read file content
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                    except:
                        continue
                    
                    # Extract basic info
                    lines = content.split('\n')
                    index[rel_path] = {
                        'size': len(content),
                        'lines': len(lines),
                        'extension': filepath.suffix,
                        'imports': self.extract_imports(content, filepath.suffix),
                        'functions': self.extract_functions(content, filepath.suffix),
                        'last_modified': datetime.fromtimestamp(filepath.stat().st_mtime).isoformat(),
                        'preview': '\n'.join(lines[:5])  # First 5 lines for preview
                    }
        
        # Save index and hashes
        with open(self.index_file, 'w') as f:
            json.dump(index, f, indent=2)
        
        with open(self.hashes_file, 'w') as f:
            json.dump(current_hashes, f, indent=2)
        
        print(f"Indexed {len(index)} files")
        return index
    
    def extract_imports(self, content, extension):
        """Extract import statements"""
        imports = []
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if extension == '.py':
                if line.startswith('import ') or line.startswith('from '):
                    imports.append(line)
            elif extension in ['.js', '.jsx', '.ts', '.tsx']:
                if line.startswith('import ') or line.startswith('const ') and 'require(' in line:
                    imports.append(line)
        
        return imports[:10]  # Limit to first 10 imports
    
    def extract_functions(self, content, extension):
        """Extract function/class definitions"""
        functions = []
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if extension == '.py':
                if line.startswith('def ') or line.startswith('class '):
                    functions.append(line)
            elif extension in ['.js', '.jsx', '.ts', '.tsx']:
                if 'function ' in line or line.startswith('const ') and '=>' in line:
                    functions.append(line)
        
        return functions[:10]  # Limit to first 10 functions
    
    def setup(self):
        """Initialize project context"""
        print("Setting up AI context...")
        self.scan_codebase()
        print("Setup complete!")
        
    def load_context(self, question):
        """Load relevant files based on question"""
        if not self.index_file.exists():
            print("No index found. Run: python3 ai_assistant.py setup")
            return ""
        
        with open(self.index_file, 'r') as f:
            index = json.load(f)
        
        # Smart context based on question type
        question_lower = question.lower()
        
        # Simple questions get minimal context
        if any(word in question_lower for word in ['files', 'what', 'list', 'show']):
            context = f"=== PROJECT SUMMARY ===\nFiles: {', '.join(index.keys())}\n"
            return context
        
    def load_conversation_history(self):
        """Load recent conversation history"""
        if not self.history_file.exists():
            return []
        
        with open(self.history_file, 'r') as f:
            history = json.load(f)
        
        # Return last 3 exchanges
        return history[-6:] if len(history) > 6 else history
    
    def save_conversation(self, question, response):
        """Save question and response to history"""
        history = self.load_conversation_history()
        history.extend([
            {"type": "question", "content": question, "timestamp": datetime.now().isoformat()},
            {"type": "response", "content": response, "timestamp": datetime.now().isoformat()}
        ])
        
        with open(self.history_file, 'w') as f:
            json.dump(history, f, indent=2)
        
        # Detailed questions get full context (but limited)
        context = "=== PROJECT CONTEXT ===\n"
        context += f"Files in project: {len(index)}\n\n"
        
        # Limit to 3 most relevant files to keep prompt small
        file_count = 0
        for filepath, info in list(index.items())[:3]:
            context += f"File: {filepath} ({info['lines']} lines)\n"
            if info['functions']:
                context += f"  Functions: {', '.join(info['functions'][:2])}\n"
            file_count += 1
        
        if len(index) > 3:
            context += f"... and {len(index) - 3} more files\n"
        
        return context
        
    def query(self, question):
        """Send question to CodeLlama with context"""
        print(f"Asking: {question}")
        
        # Load project context
        context = self.load_context(question)
        
        # Load conversation history
        history = self.load_conversation_history()
        
        # Build conversation context
        conversation_context = ""
        if history:
            conversation_context = "\n=== RECENT CONVERSATION ===\n"
            for entry in history:
                conversation_context += f"{entry['type'].upper()}: {entry['content'][:100]}...\n"
        
        # Build prompt
        prompt = f"""You are a coding assistant with full knowledge of this FastAPI project.

{context}{conversation_context}

Question: {question}

Please provide a helpful response based on the project context above. For code requests, show complete, working code."""
        
        # Send to Ollama with streaming
        try:
            print("\n" + "="*50)
            response = requests.post(self.ollama_url, json={
                "model": "codellama:7b-instruct-q4_0",  # Back to CodeLlama
                "prompt": prompt,
                "stream": True,  # Enable streaming
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "num_predict": 200
                }
            }, stream=True)
            
            if response.status_code == 200:
                full_response = ""
                for line in response.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        if 'response' in chunk:
                            print(chunk['response'], end='', flush=True)
                            full_response += chunk['response']
                        if chunk.get('done', False):
                            break
                print("\n" + "="*50)
                
                # Save conversation
                self.save_conversation(question, full_response)
            else:
                print(f"Error: {response.status_code}")
                
        except Exception as e:
            print(f"Connection error: {e}")
            print("\nTrying with CodeLlama as fallback...")
            # Fallback to original model
            try:
                response = requests.post(self.ollama_url, json={
                    "model": "codellama:7b-instruct-q4_0",
                    "prompt": prompt,
                    "stream": False
                })
                if response.status_code == 200:
                    result = response.json()
                    print(result['response'])
            except:
                print("All models failed to respond")

if __name__ == "__main__":
    ai = AIAssistant()
    if len(sys.argv) > 1:
        if sys.argv[1] == "setup":
            ai.setup()
        else:
            ai.query(" ".join(sys.argv[1:]))
    else:
        print("Usage: python3 ai_assistant.py 'your question'")
        print("       python3 ai_assistant.py setup")