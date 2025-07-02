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

# --- Summarize repo content with folder + file previews ---
def get_repo_ingestion_summary(repo, max_files=25):
    file_summary = []
    folder_structure = set()
    processed_files = 0

    try:
        tree = repo.get_git_tree(sha=repo.default_branch, recursive=True).tree
        for item in tree:
            if processed_files >= max_files:
                break

            if item.type == 'blob':
                folder = '/'.join(item.path.split('/')[:-1])
                if folder:
                    folder_structure.add(folder)

                # Process readable source code and config files
                valid_extensions = (
                    '.py', '.js', '.ts', '.json', '.html', '.css', '.md', '.txt',
                    '.yml', '.yaml', 'Dockerfile', 'Makefile', 'requirements.txt', 'setup.py'
                )

                if item.path.lower().endswith(valid_extensions) or item.path.lower() in valid_extensions:
                    try:
                        content = repo.get_contents(item.path)
                        code = content.decoded_content.decode('utf-8', errors='ignore')
                        snippet = code[:1500]  # Truncate large files
                        file_summary.append(f"\n---\n📄 **{item.path}**\n```{item.path.split('.')[-1] if '.' in item.path else ''}\n{snippet}\n```\n")
                        processed_files += 1
                    except:
                        continue
    except Exception as e:
        file_summary.append(f"\n⚠️ Error loading files: {str(e)}")

    folder_tree_text = '\n'.join(sorted(folder_structure)) or "Root only"
    code_summaries = '\n'.join(file_summary)

    return f"""
📁 **Folder Structure**
{folder_tree_text}
📦 **File Previews**
{code_summaries}
"""

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

# --- Generate the prompt and send to Gemini ---
def generate_readme_content(repo_data, user_prompt=""):
    license_info = repo_data.get('license', None)
    license_section = f"License: {license_info}" if license_info else "No license specified"

    prompt = f"""
You are an expert technical README.md writer. Generate a clean and informative `README.md` file for the GitHub repository described below.
Also give a brief summary of the project files and folder structure.
And keep it professional, concise, and easy to read. And well-structured and well formatted.

---
🔹 Repository Name: {repo_data.get('name')}
🔹 Description: {repo_data.get('description')}
🔹 Languages: {', '.join(repo_data.get('languages', {}).keys())}
🔹 Stars: {repo_data.get('stars')}
🔹 Forks: {repo_data.get('forks')}

---
🗂️ Project Files & Folder Structure:
{repo_data['ingestion_summary']}

---
📌 Instructions:
Generate a professional, easy-to-read `README.md` with the following sections **only**:

1. 🧩 **Project Title** — with emoji
2. 📖 **Description**
3. ✅ **Key Features** — concise bullet points
4. 🗂️ **Folder Structure** — structured and formatted block showing the main structure
5. ⚙️ **How to Build the Project** — clear structured and formatted commands to set up dependencies or environment
6. ▶️ **How to Run & Use** — how to launch the application, URLs if needed
7. 🛠️ **Technologies Used** — bullet points with a short description for each technology or framework used

🎯 Describe each technology briefly. Example:
- **Django** — Web framework for Python.
- **Bootstrap** — CSS framework for styling the UI.
- **Google Gemini API** — Used for generating AI content like README.md.

⚠️ Do **not** include:
- Badges
- License
- Contributing guidelines
- GitHub links or topics

Respond with valid markdown only. Do not add explanations or commentary outside the `README.md` content.

{f"🔧 Extra instructions from user:\n{user_prompt}" if user_prompt else ""}
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