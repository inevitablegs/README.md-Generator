import google.generativeai as genai
from github import Github
import os
import re
import json
from dotenv import load_dotenv
from django.core.cache import cache
from django.core.exceptions import ValidationError
from markdown import markdown
from html.parser import HTMLParser

load_dotenv()

# Initialize Gemini
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-flash')

class HTMLFilter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
    
    def handle_data(self, d):
        self.text.append(d)
    
    def get_data(self):
        return ''.join(self.text)

def extract_repo_info(url):
    """Extract owner and repo name from URL"""
    parts = url.strip('/').split('/')
    if len(parts) < 2:
        raise ValueError("Invalid GitHub URL")
    return parts[-2], parts[-1]

def validate_markdown(content):
    """Validate that the content is proper markdown"""
    try:
        # Convert to HTML to validate
        html = markdown(content)
        # Strip HTML tags to check for actual content
        f = HTMLFilter()
        f.feed(html)
        clean_text = f.get_data().strip()
        if not clean_text or len(clean_text) < 50:
            raise ValueError("Generated content is too short or invalid")
        return content
    except Exception as e:
        raise ValidationError(f"Markdown validation failed: {str(e)}")

def get_repo_data(owner, repo_name):
    g = Github(os.getenv('GITHUB_TOKEN'))
    repo = g.get_repo(f"{owner}/{repo_name}")

    data = {
        'description': repo.description or 'No description provided',
        'languages': repo.get_languages(),
        'topics': repo.get_topics(),
        'license': None,
        'stars': repo.stargazers_count,
        'forks': repo.forks_count,
        'watchers': repo.watchers_count,
        'default_branch': repo.default_branch,
    }

    try:
        license_info = repo.get_license()
        if license_info:
            data['license'] = license_info.license.key if license_info.license else None
    except Exception:
        pass

    try:
        readme = repo.get_readme()
        data['existing_readme'] = readme.decoded_content.decode('utf-8')
    except:
        data['existing_readme'] = ""

    # ✅ Fetch files
    important_files = {}
    try:
        tree = repo.get_git_tree(sha=repo.default_branch, recursive=True).tree
        for item in tree:
            if item.type == 'blob' and item.path.endswith(('.py', '.js', '.html', '.md', '.txt', '.json')):
                try:
                    file_content = repo.get_contents(item.path)
                    text = file_content.decoded_content.decode('utf-8', errors='ignore')
                    important_files[item.path] = text[:1000]  # limit to 1000 chars per file
                except:
                    continue
    except:
        pass

    ingestion_summary = get_repo_ingestion_summary(repo)
    data['ingestion_summary'] = ingestion_summary
    return data


def generate_readme_content(repo_data, user_prompt=""):
    """Generate README content using Gemini with actual file context"""

    license_info = repo_data.get('license', None)
    license_section = f"License: {license_info}" if license_info else "No license specified"

    prompt = f"""
You are an AI developer assistant. Generate a professional, detailed README.md file for a GitHub project using the following information:

Repository Name: {repo_data.get('name', '')}
Description: {repo_data.get('description', '')}
Languages: {', '.join(repo_data.get('languages', {}).keys())}
Topics: {', '.join(repo_data.get('topics', []))}
{license_section}
Stars: {repo_data.get('stars')}
Forks: {repo_data.get('forks')}

Current README.md (if exists):
{repo_data.get('existing_readme', '')}

# Project Files & Code (only summaries shown):
"""

    # Include file summaries
    for path, content in repo_data.get('important_files', {}).items():
        prompt += f"\n### {path}\n```text\n{content}\n```"

    if user_prompt:
        prompt += f"\n# Additional User Instructions:\n{user_prompt}"

    prompt += """
# Expected README Sections:
1. Project Title with emoji
2. Short badge section (e.g., stars, license)
3. Introduction/Description
4. Features (bullet list)
5. Installation steps
6. Usage examples (code)
7. Configuration options (if applicable)
8. Contributing
9. License info

Write valid markdown only. No commentary.
"""

    response = model.generate_content(
        prompt,
        safety_settings={
            'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
            'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
            'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
            'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
        },
        generation_config={
            'temperature': 0.7,
            'top_p': 0.9,
            'max_output_tokens': 2000,
        }
    )

    if not response.text:
        raise ValueError("Gemini did not return any content")

    return validate_markdown(response.text)


def generate_readme(repo_url, user_prompt=""):
    """Main function to generate README with caching"""
    cache_key = f"readme_{repo_url}_{user_prompt}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        owner, repo_name = extract_repo_info(repo_url)
        repo_data = get_repo_data(owner, repo_name)
        repo_data['name'] = repo_name
        readme_content = generate_readme_content(repo_data, user_prompt)
        cache.set(cache_key, readme_content, timeout=86400)
        return readme_content
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg and "license" in error_msg:
            try:
                repo_data['license'] = None
                readme_content = generate_readme_content(repo_data, user_prompt)
                cache.set(cache_key, readme_content, timeout=86400)
                return readme_content
            except Exception as fallback_error:
                raise Exception(f"Fallback failed: {str(fallback_error)}")
        else:
            raise Exception(f"Failed to generate README: {error_msg}")


def get_repo_ingestion_summary(repo):
    """
    Ingest all files from repo and build a structured summary for Gemini.
    """
    file_summary = []
    folder_structure = set()

    try:
        tree = repo.get_git_tree(sha=repo.default_branch, recursive=True).tree
        for item in tree:
            if item.type == 'blob':
                folder = '/'.join(item.path.split('/')[:-1])
                if folder:
                    folder_structure.add(folder)

                # Fetch content
                if item.path.lower().endswith(('.py', '.js', '.ts', '.json', '.html', '.css', '.md', '.txt', 'dockerfile', 'makefile', 'requirements.txt', 'setup.py')):
                    try:
                        content = repo.get_contents(item.path)
                        code = content.decoded_content.decode('utf-8', errors='ignore')
                        snippet = code[:1500]  # truncate large files
                        file_summary.append(f"\n---\n📄 **{item.path}**\n```{item.path.split('.')[-1] if '.' in item.path else ''}\n{snippet}\n```\n")
                    except:
                        continue
    except Exception as e:
        file_summary.append(f"\n⚠️ Error loading files: {str(e)}")

    folder_tree_text = '\n'.join(sorted(folder_structure))
    code_summaries = '\n'.join(file_summary)

    return f"""
📁 **Project Folder Structure**
    📦 **Code & File Summaries**
{code_summaries}
"""


# --- generator/services.py (with full ingestion) ---
import google.generativeai as genai
from github import Github
import os
from dotenv import load_dotenv
from django.core.cache import cache
from django.core.exceptions import ValidationError
from markdown import markdown
from html.parser import HTMLParser

load_dotenv()

genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-flash')

class HTMLFilter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []

    def handle_data(self, d):
        self.text.append(d)

    def get_data(self):
        return ''.join(self.text)

def extract_repo_info(url):
    parts = url.strip('/').split('/')
    if len(parts) < 2:
        raise ValueError("Invalid GitHub URL")
    return parts[-2], parts[-1]

def validate_markdown(content):
    try:
        html = markdown(content)
        f = HTMLFilter()
        f.feed(html)
        clean_text = f.get_data().strip()
        if not clean_text or len(clean_text) < 50:
            raise ValueError("Generated content is too short or invalid")
        return content
    except Exception as e:
        raise ValidationError(f"Markdown validation failed: {str(e)}")

def get_repo_ingestion_summary(repo):
    file_summary = []
    folder_structure = set()

    try:
        tree = repo.get_git_tree(sha=repo.default_branch, recursive=True).tree
        for item in tree:
            if item.type == 'blob':
                folder = '/'.join(item.path.split('/')[:-1])
                if folder:
                    folder_structure.add(folder)

                if item.path.lower().endswith((
                    '.py', '.js', '.ts', '.json', '.html', '.css', '.md',
                    '.txt', 'dockerfile', 'makefile', 'requirements.txt', 'setup.py')):
                    try:
                        content = repo.get_contents(item.path)
                        code = content.decoded_content.decode('utf-8', errors='ignore')
                        snippet = code[:1500]
                        file_summary.append(f"\n---\n📄 **{item.path}**\n```\n{snippet}\n```\n")
                    except:
                        continue
    except Exception as e:
        file_summary.append(f"\n⚠️ Error loading files: {str(e)}")

    folder_tree_text = '\n'.join(sorted(folder_structure))
    code_summaries = '\n'.join(file_summary)

    return f"""
📁 **Project Folder Structure**
```
{folder_tree_text or 'Root only'}
```

📦 **Code & File Summaries**
{code_summaries}
"""

def get_repo_data(owner, repo_name):
    g = Github(os.getenv('GITHUB_TOKEN'))
    repo = g.get_repo(f"{owner}/{repo_name}")

    data = {
        'description': repo.description or 'No description provided',
        'languages': repo.get_languages(),
        'topics': repo.get_topics(),
        'license': None,
        'stars': repo.stargazers_count,
        'forks': repo.forks_count,
        'watchers': repo.watchers_count,
        'default_branch': repo.default_branch,
    }

    try:
        license_info = repo.get_license()
        if license_info:
            data['license'] = license_info.license.key if license_info.license else None
    except Exception:
        pass

    try:
        readme = repo.get_readme()
        data['existing_readme'] = readme.decoded_content.decode('utf-8')
    except:
        data['existing_readme'] = ""

    data['ingestion_summary'] = get_repo_ingestion_summary(repo)
    return data

def generate_readme_content(repo_data, user_prompt=""):
    license_info = repo_data.get('license', None)
    license_section = f"License: {license_info}" if license_info else "No license specified"

    prompt = f"""
You are a professional AI technical writer. Using the following FULL context from the GitHub repository, generate a comprehensive README.md.

---
🔹 Repository Name: {repo_data.get('name')}
🔹 Description: {repo_data.get('description')}
🔹 Languages: {', '.join(repo_data.get('languages', {}).keys())}
🔹 Topics: {', '.join(repo_data.get('topics', []))}
🔹 Stars: {repo_data.get('stars')}
🔹 Forks: {repo_data.get('forks')}
🔹 {license_section}

---
🗃️ FILE INGESTED DATA:
{repo_data['ingestion_summary']}

---
🎯 Instructions:
- Write a complete `README.md` with Title, Badges, About, Features, Folder structure, Installation, Usage, Configuration, Examples, Contributing, License.
- Do not hallucinate anything. Use only what’s in the repo.
- Write in valid markdown only.

{f"📌 Extra Prompt from User:\n{user_prompt}" if user_prompt else ""}
"""

    response = model.generate_content(
        prompt,
        safety_settings={
            'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
            'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
            'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
            'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
        },
        generation_config={
            'temperature': 0.7,
            'top_p': 0.9,
            'max_output_tokens': 2000,
        }
    )

    if not response.text:
        raise ValueError("Gemini did not return any content")

    return validate_markdown(response.text)
