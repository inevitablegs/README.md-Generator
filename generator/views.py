from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .forms import RepoForm
from .services import generate_readme
from .models import Repository
from markdown import markdown

@never_cache
@require_http_methods(["GET", "POST"])
def home(request):
    if request.method == 'POST':
        form = RepoForm(request.POST)
        if form.is_valid():
            try:
                repo_url = form.cleaned_data['repo_url']
                user_prompt = form.cleaned_data.get('custom_prompt', '')
                readme_content = generate_readme(repo_url, user_prompt)

                # Convert to HTML for preview
                readme_html = markdown(readme_content)

                # Save to database
                Repository.objects.update_or_create(
                    url=repo_url,
                    defaults={'readme_content': readme_content}
                )

                return render(request, 'result.html', {
                    'readme': readme_html,           # rendered HTML
                    'raw_readme': readme_content,    # original markdown
                    'repo_url': repo_url
                })
            except Exception as e:
                error_msg = str(e)
                if "404" in error_msg and "license" in error_msg:
                    messages.warning(request, "License info not found. Generated README without license.")
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



from urllib.parse import unquote
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

@never_cache
@require_http_methods(["GET"])
def edit_readme(request):
    repo_url = unquote(request.GET.get('repo', ''))
    try:
        repo = Repository.objects.get(url=repo_url)
        return render(request, 'edit.html', {
            'readme_content': repo.readme_content,
            'repo_url': repo_url
        })
    except Repository.DoesNotExist:
        messages.error(request, "Repository not found")
        return redirect('home')

@csrf_exempt
@require_http_methods(["POST"])
def save_readme(request):
    try:
        repo_url = request.POST.get('repo_url')
        content = request.POST.get('readme_content')

        repo = Repository.objects.get(url=repo_url)
        repo.readme_content = content
        repo.save()

        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})

