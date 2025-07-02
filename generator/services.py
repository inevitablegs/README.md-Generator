import os
import re
import google.generativeai as genai
from github import Github
from dotenv import load_dotenv
from django.core.cache import cache
from django.core.exceptions import ValidationError
from markdown import markdown
from html.parser import HTMLParser

load_dotenv()

genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-flash')

# --- Helper class to validate markdown content ---
class HTMLFilter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, d):
        self.text.append(d)

    def get_data(self):
        return ''.join(self.text)

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

# --- Extract owner/repo from URL ---
def extract_repo_info(url):
    parts = url.strip('/').split('/')
    if len(parts) < 2:
        raise ValueError("Invalid GitHub URL")
    return parts[-2], parts[-1]



# --- Fetch all useful repo metadata + README ---
def get_repo_data(owner, repo_name):
    g = Github(os.getenv('GITHUB_TOKEN'))
    repo = g.get_repo(f"{owner}/{repo_name}")

    data = {
        'description': repo.description or 'No description provided.',
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

# generator/services.py (updated)

def get_repo_ingestion_summary(repo, max_files=25):
    """Improved repository analysis focusing on key files"""
    important_files = []
    
    try:
        contents = repo.get_contents("")
        while contents:
            file_content = contents.pop(0)
            if file_content.type == "dir":
                contents.extend(repo.get_contents(file_content.path))
            else:
                # Focus on key files only
                key_files = [
                    'requirements.txt', 'package.json', 'Dockerfile',
                    'setup.py', 'Makefile', 'README.md', '.env.example',
                    'docker-compose.yml', 'config.json'
                ]
                
                if file_content.name in key_files or file_content.name.endswith(('.py', '.js', '.md')):
                    try:
                        content = file_content.decoded_content.decode('utf-8', errors='ignore')
                        important_files.append({
                            'path': file_content.path,
                            'content': content[:1000]  # Limit content size
                        })
                    except:
                        continue
                    
                if len(important_files) >= max_files:
                    break
                    
    except Exception as e:
        important_files.append({'error': str(e)})
        
    return important_files

def generate_readme_content(repo_data, user_prompt=""):
    """Improved prompt for professional README generation"""
    prompt = f"""
You are an expert technical writer creating professional GitHub README.md files. 
Generate a comprehensive, well-structured README for this project:

**Repository Information:**
- Name: {repo_data.get('name')}
- Description: {repo_data.get('description') or 'No description provided'}
- Primary Language: {next(iter(repo_data.get('languages', {}).keys()), 'Not specified')}
- Stars: {repo_data.get('stars', 0)}
- Forks: {repo_data.get('forks', 0)}
- License: {repo_data.get('license', 'Not specified')}

**Key Files Analysis:**
{'\n'.join([f"- {f['path']}" for f in repo_data.get('ingestion_summary', []) if isinstance(f, dict)])}

**User Instructions:**
{user_prompt if user_prompt else "None provided"}

**README Requirements:**
1. **Project Title** - Clear, descriptive name with relevant emoji
2. **Description** - Detailed project overview (3-5 paragraphs)
3. **Features** - Bullet points of key features (5-8 items)
4. **Installation** - Clear setup instructions with code blocks
5. **Usage** - How to use the project with examples
6. **Configuration** - Environment variables or settings needed
7. **Technologies** - Table of technologies used with brief descriptions
8. **API Reference** - If applicable (section with endpoints)
9. **Screenshots** - Placeholder section if applicable
10. **Contributing** - Brief guidelines for contributors
11. **License** - Clear license information

**Formatting Rules:**
- Use GitHub-flavored Markdown
- Include appropriate emojis for section headers
- Use proper code blocks with syntax highlighting
- Keep line length under 100 characters
- Use tables for technology stacks
- Include placeholder comments for visual elements

**Important:**
- Do not include folder structure
- Maintain professional tone
- Ensure technical accuracy
- Include all essential sections
"""
    
    # Rest of the function remains the same...



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
            'max_output_tokens': 2048,
        }
    )

    if not response.text:
        raise ValueError("Gemini did not return any content")

    return validate_markdown(response.text)

# --- Main entry point used by views.py ---
def generate_readme(repo_url, user_prompt=""):
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
        raise Exception(f"Failed to generate README: {str(e)}")