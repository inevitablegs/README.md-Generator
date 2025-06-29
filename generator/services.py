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
    """Fetch repository data from GitHub"""
    g = Github(os.getenv('GITHUB_TOKEN'))
    repo = g.get_repo(f"{owner}/{repo_name}")
    
    # Initialize data with default values
    data = {
        'description': repo.description or 'No description provided',
        'languages': repo.get_languages(),
        'topics': repo.get_topics(),
        'license': None,  # Default to None
        'stars': repo.stargazers_count,
        'forks': repo.forks_count,
        'watchers': repo.watchers_count,
        'default_branch': repo.default_branch,
    }
    
    # Handle license information more gracefully
    try:
        license_info = repo.get_license()
        if license_info:
            data['license'] = license_info.license.key if license_info.license else None
    except Exception as e:
        # If there's any error getting license, just keep it as None
        pass
    
    # Handle README
    try:
        readme = repo.get_readme()
        data['existing_readme'] = readme.decoded_content.decode('utf-8')
    except:
        data['existing_readme'] = ""
    
    return data

def generate_readme_content(repo_data):
    """Generate README content using Gemini"""
    license_info = repo_data.get('license', None)
    license_section = f"License: {license_info}" if license_info else "No license specified"
    
    prompt = f"""
    Generate a comprehensive, professional README.md file for a GitHub repository with these details:
    
    - Repository Name: {repo_data.get('name', '')}
    - Description: {repo_data.get('description', 'No description provided')}
    - Primary Languages: {', '.join(repo_data.get('languages', {}).keys())}
    - Topics: {', '.join(repo_data.get('topics', [])) if repo_data.get('topics') else 'No topics'}
    - {license_section}
    - Stars: {repo_data.get('stars', 0)}
    - Forks: {repo_data.get('forks', 0)}
    
    Current README content (if any):
    {repo_data.get('existing_readme', 'No existing README')}
    
    The README should include these sections:
    1. Project Title with appropriate emoji
    2. Badges section (include version, license if available, build status if applicable)
    3. Clear description with features list
    4. Installation instructions
    5. Usage examples with code snippets
    6. Configuration options if applicable
    7. Contributing guidelines
    8. License information (if available)
    9. Professional formatting with proper Markdown
    
    Output only the raw README.md content without any commentary or formatting around it.
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

def generate_readme(repo_url):
    """Main function to generate README with caching"""
    cache_key = f"readme_{repo_url}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    try:
        owner, repo_name = extract_repo_info(repo_url)
        repo_data = get_repo_data(owner, repo_name)
        repo_data['name'] = repo_name
        readme_content = generate_readme_content(repo_data)
        
        # Save to cache for 24 hours
        cache.set(cache_key, readme_content, timeout=86400)
        
        return readme_content
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg and "license" in error_msg:
            # This is specifically for license 404 errors - we can continue
            try:
                # Try again without license info
                repo_data['license'] = None
                readme_content = generate_readme_content(repo_data)
                cache.set(cache_key, readme_content, timeout=86400)
                return readme_content
            except Exception as fallback_error:
                raise Exception(f"Failed to generate README (fallback attempt): {str(fallback_error)}")
        else:
            raise Exception(f"Failed to generate README: {error_msg}")