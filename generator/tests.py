from django.test import TestCase

# Create your tests here.
# generator/tests.py

class ReadmeGenerationTest(TestCase):
    def test_clone_link_in_readme(self):
        from .services import generate_readme_content
        data = {
            'name': 'TestRepo',
            'description': 'Test description',
            'languages': {'Python': 1000},
            'stars': 5,
            'forks': 2,
            'license': 'mit',
            'ingestion_summary': [{'path': 'README.md'}]
        }
        repo_url = 'https://github.com/testuser/TestRepo'
        content = generate_readme_content(data, '', repo_url)
        self.assertIn(repo_url, content)
        self.assertIn(f"git clone {repo_url}", content)
