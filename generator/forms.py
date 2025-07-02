from django import forms
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
import re

class RepoForm(forms.Form):
    repo_url = forms.URLField(
        label='GitHub Repository URL',
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'https://github.com/username/repo',
            'autocomplete': 'off'
        }),
        help_text="Enter the full URL of the GitHub repository"
    )

    custom_prompt = forms.CharField(
        label='Custom Instructions (Optional)',
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Add features, change tone, add badges...'
        }),
        required=False,
        help_text="Enter additional instructions for the README generation"
    )

    def clean_repo_url(self):
        url = self.cleaned_data['repo_url']
        if not re.match(r'^https?://github\.com/[^/]+/[^/]+/?$', url):
            raise ValidationError("Please enter a valid GitHub repository URL")
        return url
