#!/usr/bin/env python3
import json
import os
import sys
import requests
import hashlib
import shutil
import time
import threading
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class CodeFileHandler(FileSystemEventHandler):
    """Handle file system events for code files"""
    
    def __init__(self, ai_assistant):
        self.ai = ai_assistant
        self.last_update = time.time()
        
    def on_modified(self, event):
        if event.is_directory:
            return
            
        filepath = Path(event.src_path)
        
        # Only process code files
        if filepath.suffix.lower() in self.ai.code_extensions:
            # Debounce rapid changes (wait 1 second)
            current_time = time.time()
            if current_time - self.last_update < 1:
                return
                
            self.last_update = current_time
            
            # Update index for this file
            print(f"File changed: {filepath.name} - updating index...")
            self.ai.update_single_file(filepath)
    
    def on_created(self, event):
        if event.is_directory:
            return
            
        filepath = Path(event.src_path)
        if filepath.suffix.lower() in self.ai.code_extensions:
            print(f"New file created: {filepath.name} - updating index...")
            self.ai.update_single_file(filepath)
    
    def on_deleted(self, event):
        if event.is_directory:
            return
            
        filepath = Path(event.src_path)
        if filepath.suffix.lower() in self.ai.code_extensions:
            print(f"File deleted: {filepath.name} - updating index...")
            self.ai.remove_from_index(filepath)

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
        
        # Auto-check for file changes on each query
        self.check_for_changes()
        
    def get_file_hash(self, filepath):
        """Get MD5 hash of file content"""
        try:
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return None
    
    def suggest_filename(self, question, code):
        """Suggest appropriate filename based on question and code content"""
        question_lower = question.lower()
        
        # React/JS components
        if 'react' in question_lower or 'component' in question_lower:
            if 'user' in question_lower:
                return 'UserComponent.jsx'
            elif 'login' in question_lower:
                return 'LoginComponent.jsx'
            else:
                return 'Component.jsx'
        
        # Python files
        if 'fastapi' in question_lower or 'endpoint' in question_lower or 'route' in question_lower:
            if 'user' in question_lower:
                return 'users.py'
            elif 'auth' in question_lower:
                return 'auth.py'
            else:
                return 'routes.py'
        
        # Models
        if 'model' in question_lower:
            return 'models.py'
        
        # Database
        if 'database' in question_lower:
            return 'database.py'
        
        # CSS
        if 'css' in question_lower or 'style' in question_lower:
            return 'styles.css'
        
        # HTML
        if 'html' in question_lower:
            return 'index.html'
        
        # Default based on code content
        if 'import React' in code or 'jsx' in code.lower():
            return 'Component.jsx'
        elif 'from fastapi' in code or '@app.' in code:
            return 'main.py'
        elif 'def ' in code and 'class ' in code:
            return 'module.py'
        
        return None  # Let user specify
    
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
    
    def update_single_file(self, filepath):
        """Update index for a single file"""
        try:
            # Load existing index
            index = {}
            if self.index_file.exists():
                with open(self.index_file, 'r') as f:
                    index = json.load(f)
            
            # Load existing hashes
            hashes = {}
            if self.hashes_file.exists():
                with open(self.hashes_file, 'r') as f:
                    hashes = json.load(f)
            
            rel_path = str(filepath.relative_to('.'))
            
            if filepath.exists():
                # Update file info
                file_hash = self.get_file_hash(filepath)
                if file_hash:
                    hashes[rel_path] = file_hash
                    
                    # Read and index file
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    lines = content.split('\n')
                    index[rel_path] = {
                        'size': len(content),
                        'lines': len(lines),
                        'extension': filepath.suffix,
                        'imports': self.extract_imports(content, filepath.suffix),
                        'functions': self.extract_functions(content, filepath.suffix),
                        'last_modified': datetime.fromtimestamp(filepath.stat().st_mtime).isoformat(),
                        'preview': '\n'.join(lines[:5])
                    }
            else:
                # File was deleted
                if rel_path in index:
                    del index[rel_path]
                if rel_path in hashes:
                    del hashes[rel_path]
            
            # Save updated index and hashes
            with open(self.index_file, 'w') as f:
                json.dump(index, f, indent=2)
            with open(self.hashes_file, 'w') as f:
                json.dump(hashes, f, indent=2)
                
        except Exception as e:
            print(f"Error updating file index: {e}")
    
    def remove_from_index(self, filepath):
        """Remove file from index"""
        try:
            rel_path = str(filepath.relative_to('.'))
            
            # Load and update index
            if self.index_file.exists():
                with open(self.index_file, 'r') as f:
                    index = json.load(f)
                if rel_path in index:
                    del index[rel_path]
                with open(self.index_file, 'w') as f:
                    json.dump(index, f, indent=2)
            
            # Load and update hashes
            if self.hashes_file.exists():
                with open(self.hashes_file, 'r') as f:
                    hashes = json.load(f)
                if rel_path in hashes:
                    del hashes[rel_path]
                with open(self.hashes_file, 'w') as f:
                    json.dump(hashes, f, indent=2)
                    
        except Exception as e:
            print(f"Error removing from index: {e}")
    
    def check_for_changes(self):
        """Quick check if any files have changed since last run"""
        if not self.hashes_file.exists():
            print("🔧 No index found - creating initial index...")
            self.scan_codebase()
            return
            
        try:
            with open(self.hashes_file, 'r') as f:
                old_hashes = json.load(f)
        except:
            print("🔧 Invalid index - recreating...")
            self.scan_codebase()
            return
            
        changes_found = False
        
        # Check existing files for changes
        for root, dirs, files in os.walk('.'):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv', 'env']]
            
            for file in files:
                filepath = Path(root) / file
                if filepath.suffix.lower() in self.code_extensions:
                    rel_path = str(filepath.relative_to('.'))
                    current_hash = self.get_file_hash(filepath)
                    
                    if rel_path not in old_hashes or old_hashes[rel_path] != current_hash:
                        changes_found = True
                        break
            
            if changes_found:
                break
        
        # Check for deleted files
        if not changes_found:
            for old_file in old_hashes:
                if not Path(old_file).exists():
                    changes_found = True
                    break
        
        if changes_found:
            print("📝 Files changed - updating index...")
            self.scan_codebase()
        else:
            print("✅ Files up to date")
    
    def write_file(self, filepath, content, backup=True):
        """Write content to file with optional backup"""
        if backup and Path(filepath).exists():
            # Create backup
            backup_path = f"{filepath}.backup"
            import shutil
            shutil.copy2(filepath, backup_path)
            print(f"Created backup: {backup_path}")
        
        # Write new content
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Updated: {filepath}")
        
        # Update index
        self.scan_codebase()
        
    def extract_code_from_response(self, response_text):
        """Extract code blocks from LLM response"""
        import re
        
        # Find code blocks with ```python or just ```
        code_blocks = re.findall(r'```(?:python|javascript|jsx)?\s*\n(.*?)```', response_text, re.DOTALL)
        
        if code_blocks:
            # Return the first (usually most complete) code block
            return code_blocks[0].strip()
        
        return None
        
    def query(self, question, write_to_file=None):
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
        
        # Enhanced prompt for file writing
        file_instruction = ""
        question_lower = question.lower()
        
        if write_to_file:
            file_instruction = f"\n\nIMPORTANT: Provide complete, working code for {write_to_file}. Include all necessary imports and ensure the code is production-ready."
        elif any(word in question_lower for word in ['create', 'write', 'generate', 'build']):
            file_instruction = f"\n\nSUGGESTION: If you provide code, offer to write it to a file for the user."
        
        # Enhanced prompt with explicit code formatting instructions
        prompt = f"""You are a coding assistant with full knowledge of this FastAPI project.

{context}{conversation_context}

IMPORTANT: When providing code solutions:
1. Always wrap code in proper markdown code blocks with language specification
2. Use ```python for Python code, ```javascript for JS, ```jsx for React
3. Provide complete, executable code - not step-by-step instructions
4. Include all necessary imports at the top of code blocks

CRITICAL REQUIREMENTS:
1. Generate only valid, syntactically correct Python code
2. Include all necessary imports at the top
3. Use proper patterns and dependency injection
4. Test your code mentally before responding
5. No placeholder syntax like "database-dependent-bcrypt"

Example response format:
```python
# Your complete Python code here
import necessary_modules

def your_function():
    return "working code"
```

Question: {question}{file_instruction}"""
        
        # Send to LLM with streaming
        try:
            print("\n" + "="*50)
            response = requests.post(self.ollama_url, json={
                "model": "deepseek-coder:6.7b-instruct", # "deepseek-r1:7b",  # "codellama:7b-instruct-q4_0"
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "num_predict": 2000
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
                
                # Auto-detect code and offer to write file
                if not write_to_file and any(word in question.lower() for word in ['create', 'write', 'generate', 'build']):
                    code = self.extract_code_from_response(full_response)
                    if code:
                        # Suggest filename based on question
                        suggested_file = self.suggest_filename(question, code)
                        if suggested_file:
                            confirm = input(f"\nWould you like me to write this code to {suggested_file}? (y/n): ")
                            if confirm.lower() == 'y':
                                self.write_file(suggested_file, code)
                        else:
                            filename = input("\nEnter filename to save this code (or press Enter to skip): ")
                            if filename.strip():
                                self.write_file(filename, code)
                
                # Auto-write to file if requested
                if write_to_file:
                    code = self.extract_code_from_response(full_response)
                    if code:
                        confirm = input(f"\nWrite this code to {write_to_file}? (y/n): ")
                        if confirm.lower() == 'y':
                            self.write_file(write_to_file, code)
                        else:
                            print("Code not written to file.")
                    else:
                        print("No code block found in response.")
            else:
                print(f"Error: {response.status_code}")
                
        except Exception as e:
            print(f"Streaming error: {e}")
            print("Retrying without streaming...")
            # Fallback to non-streaming
            try:
                response = requests.post(self.ollama_url, json={
                    "model": "deepseek-coder:6.7b-instruct", #  "deepseek-r1:7b",  # Changed from "codellama:7b-instruct-q4_0"
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": 2000
                    }
                })
                if response.status_code == 200:
                    result = response.json()
                    full_response = result['response']
                    print("\n" + "="*50)
                    print(full_response)
                    print("="*50)
                    
                    # Save conversation
                    self.save_conversation(question, full_response)
                    
                    # Auto-write to file if requested
                    if write_to_file:
                        code = self.extract_code_from_response(full_response)
                        if code:
                            confirm = input(f"\nWrite this code to {write_to_file}? (y/n): ")
                            if confirm.lower() == 'y':
                                self.write_file(write_to_file, code)
                            else:
                                print("Code not written to file.")
                        else:
                            print("No code block found in response.")
                else:
                    print(f"Error: {response.status_code} - {response.text}")
            except Exception as fallback_error:
                print(f"Complete connection failure: {fallback_error}")

if __name__ == "__main__":
    ai = AIAssistant()
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "setup":
            ai.setup()
        elif command == "write":
            if len(sys.argv) < 4:
                print("Usage: python3 ai_assistant.py write 'question' filename")
                print("Example: python3 ai_assistant.py write 'Create a delete user endpoint' main.py")
            else:
                question = sys.argv[2]
                filename = sys.argv[3]
                ai.query(question, write_to_file=filename)
        else:
            # Regular query
            ai.query(" ".join(sys.argv[1:]))
    else:
        print("Usage: python3 ai_assistant.py 'your question'")
        print("       python3 ai_assistant.py setup")
        print("       python3 ai_assistant.py write 'question' filename")