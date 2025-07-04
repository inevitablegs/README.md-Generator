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

def generate_readme_content(repo_data, user_prompt="", repo_url=""):
    """Improved prompt for professional README generation"""
    prompt = f"""
You are a professional technical writer specializing in GitHub documentation.

Generate a clean, well-formatted `README.md` file for the following repository:

---

📁 **Repository Metadata**:
- **Name**: {repo_data.get('name')}
- **Description**: {repo_data.get('description') or 'No description provided'}
- **Languages**: {', '.join(repo_data.get('languages', {}).keys())}
- **Stars**: ⭐ {repo_data.get('stars', 0)}
- **Forks**: 🍴 {repo_data.get('forks', 0)}
- **License**: {repo_data.get('license', 'Not specified')}
- **GitHub URL**: {repo_url}

---

🧠 **Project Analysis (Key Files)**:
{chr(10).join([f"- {f['path']}" for f in repo_data.get('ingestion_summary', []) if isinstance(f, dict)])}

---

📝 **User’s Custom Prompt**:
{user_prompt if user_prompt else 'N/A'}

---

📌 **README Must Include**:
1. Project title with emoji
2. Description: 2-4 paragraphs
3. Features (bullet points)
4. Installation instructions (include real repo URL: `git clone {repo_url}`)
5. Usage with code examples
6. Configuration if needed
7. Technologies table
8. Screenshots (placeholder)
9. Contributing guidelines
10. License section
11. Do **not** include folder structure

---

🧾 **Formatting Rules**:
- Use GitHub-flavored Markdown
- Emojis in headings
- Code blocks with language syntax
- Limit lines to 100 chars
- Use tables for technologies
- Clear, professional tone
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
        readme_content = generate_readme_content(repo_data, user_prompt, repo_url)
        cache.set(cache_key, readme_content, timeout=86400)
        return readme_content
    except Exception as e:
        raise Exception(f"Failed to generate README: {str(e)}")
    
    
# generator/services.py (add at module level after imports)
load_dotenv()

# Validate GitHub token on startup
try:
    github_token = os.getenv('GITHUB_TOKEN')
    if github_token:
        g = Github(github_token)
        # Simple verification by getting authenticated user
        user = g.get_user()
        print(f"GitHub token validated for user: {user.login}")
    else:
        print("WARNING: GITHUB_TOKEN environment variable not set")
except Exception as e:
    print(f"WARNING: GitHub token validation failed: {str(e)}")


# generator/services.py (update the push_to_github function)

def push_to_github(repo_url, readme_content, branch="main", commit_message="Added README.md via README Generator"):
    """
    Push the generated README.md to the GitHub repository
    """
    try:
        # First verify we have a token
        github_token = os.getenv('GITHUB_TOKEN')
        if not github_token:
            return False, "GitHub token not configured in environment variables"
            
        owner, repo_name = extract_repo_info(repo_url)
        g = Github(github_token)
        
        # Improved token verification
        try:
            # Get authenticated user to verify token works
            user = g.get_user()
            # Get token scopes if available (PyGithub doesn't always expose this)
            try:
                scopes = getattr(g, 'oauth_scopes', [])
                if scopes and not ('repo' in scopes or 'public_repo' in scopes):
                    return False, "GitHub token needs 'repo' or 'public_repo' scope"
            except Exception as scope_error:
                # If we can't check scopes but can get user, assume token has basic permissions
                pass
        except Exception as auth_error:
            return False, f"GitHub authentication failed: {str(auth_error)}"
        
        # Rest of the function remains the same...
        repo = g.get_repo(f"{owner}/{repo_name}")
        
        # Verify user has push access
        try:
            permission = repo.get_collaborator_permission(user.login)
            if permission not in ['admin', 'write']:
                return False, f"User has {permission} permissions, needs 'write' or 'admin'"
        except Exception as perm_error:
            return False, f"Permission check failed: {str(perm_error)}"
        
        # Check if README exists and update/create
        try:
            readme = repo.get_contents("README.md", ref=branch)
            repo.update_file(
                path="README.md",
                message=commit_message,
                content=readme_content,
                sha=readme.sha,
                branch=branch
            )
            return True, "README.md updated successfully"
        except Exception as update_ex:
            if "Not Found" not in str(update_ex):
                return False, f"Update check failed: {str(update_ex)}"
            try:
                repo.create_file(
                    path="README.md",
                    message=commit_message,
                    content=readme_content,
                    branch=branch
                )
                return True, "README.md created successfully"
            except Exception as create_ex:
                return False, f"Create failed: {str(create_ex)}"
            
    except Exception as e:
        return False, f"Error pushing to GitHub: {str(e)}"