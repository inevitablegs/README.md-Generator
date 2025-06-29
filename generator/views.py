from django.shortcuts import render

# Create your views here.
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .forms import RepoForm
from .services import generate_readme
from .models import Repository


@never_cache
@require_http_methods(["GET", "POST"])
def home(request):
    if request.method == 'POST':
        form = RepoForm(request.POST)
        if form.is_valid():
            try:
                repo_url = form.cleaned_data['repo_url']
                readme_content = generate_readme(repo_url)
                
                # Save to database
                Repository.objects.update_or_create(
                    url=repo_url,
                    defaults={'readme_content': readme_content}
                )
                
                return render(request, 'result.html', {
                    'readme': readme_content,
                    'repo_url': repo_url
                })
            except Exception as e:
                error_msg = str(e)
                if "404" in error_msg and "license" in error_msg:
                    messages.warning(request, "License information not found for this repository. Generated README without license details.")
                else:
                    messages.error(request, f"Error: {error_msg}")
                return redirect('home')
        else:
            messages.error(request, "Please enter a valid GitHub repository URL")
    else:
        form = RepoForm()
    
    return render(request, 'home.html', {
        'form': form,
        'recent_repos': Repository.objects.order_by('-created_at')[:5]
    })

@never_cache
def about(request):
    return render(request, 'about.html')