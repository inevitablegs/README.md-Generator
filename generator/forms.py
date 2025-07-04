from django import forms
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
import re

class RepoForm(forms.Form):
    repo_url = forms.URLField(
        label='GitHub URL (Repository or Profile)',
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'https://github.com/username OR https://github.com/username/repo',
            'autocomplete': 'off'
        }),
        help_text="Enter a GitHub repository or profile URL"
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

    is_profile = forms.BooleanField(
        label='Generate for GitHub Profile (instead of Repo)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def clean_repo_url(self):
        url = self.cleaned_data['repo_url'].strip()

        if not url.startswith("https://github.com/"):
            raise ValidationError("URL must start with https://github.com/")

        path_parts = url.replace("https://github.com/", "").strip("/").split("/")

        # Either https://github.com/username  → 1 part (profile)
        # Or    https://github.com/username/repo  → 2 parts (repository)
        if len(path_parts) not in [1, 2]:
            raise ValidationError("Please enter a valid GitHub profile or repository URL")

        return url


