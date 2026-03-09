import re

file_path = "/Users/idokatz/VSCode/Archmorph/backend/roadmap.py"
with open(file_path, "r") as f:
    text = f.read()

injection = """
import time
_github_issues_cache = None
_github_issues_last_fetched = 0

def fetch_github_ideas() -> List[str]:
    global _github_issues_cache, _github_issues_last_fetched
    now = time.time()
    
    # 15 minute cache to avoid rate limits
    if _github_issues_cache is not None and now - _github_issues_last_fetched < 900:
        return _github_issues_cache
        
    if not GITHUB_TOKEN:
        return []
        
    try:
        from github import Github
        import os
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        
        # Get only open issues
        issues = repo.get_issues(state="open")
        highlights = []
        for issue in issues:
            # Skip pull requests
            if issue.pull_request:
                continue
                
            labels = [l.name.lower() for l in issue.labels]
            
            # Format: Title (#123)
            # Add emojis based on labels
            prefix = ""
            if "bug" in labels:
                continue # Skip bugs for roadmap features mostly
            elif "enhancement" in labels or "feature" in labels:
                prefix = "✨ "
            
            # Use markdown formatting for Github links in the UI
            highlights.append(f"{prefix}{issue.title} ([#{issue.number}]({issue.html_url}))")
            
        _github_issues_cache = highlights
        _github_issues_last_fetched = now
        return highlights
    except Exception as exc:
        logger.error(f"Failed to fetch GitHub issues for roadmap: {exc}")
        return _github_issues_cache or []

def get_roadmap() -> Dict[str, Any]:
    \"\"\"
    Get the complete roadmap with timeline.
    
    Returns grouped releases by status with statistics.
    \"\"\"
    released = []
    in_progress = []
    planned = []
    ideas = []
    
    for release in RELEASE_TIMELINE:
        status = release["status"]
        if status == ReleaseStatus.RELEASED:
            released.append(release)
        elif status == ReleaseStatus.IN_PROGRESS:
            in_progress.append(release)
        elif status == ReleaseStatus.PLANNED:
            planned.append(release)
        else:
            ideas.append(release)
            
    # ------ GITHUB SYNC INJECTION ------
    gh_ideas = fetch_github_ideas()
    if gh_ideas:
        ideas.insert(0, {
            "version": "Live Sync",
            "name": "Community Feedback & GitHub Issues",
            "date": "Auto-Updated",
            "status": ReleaseStatus.IDEA,
            "highlights": gh_ideas,
        })
"""

text = re.sub(r'def get_roadmap\(\) -> Dict\[str, Any\]:(.*?)ideas\.append\(release\)', injection, text, flags=re.DOTALL)

with open(file_path, "w") as f:
    f.write(text)

print("Updated roadmap.py")
