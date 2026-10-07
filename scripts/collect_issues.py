"""Collect closed Streamlit bugs explicitly resolved by merged pull requests."""
import hashlib
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "source_cache"
REPO = "streamlit/streamlit"


def get(path):
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / (hashlib.sha256(path.encode()).hexdigest() + ".json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "FixFinder-dataset"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request("https://api.github.com/" + path, headers=headers), timeout=60) as response:
                result = json.load(response)
            cache.write_text(json.dumps(result), encoding="utf-8")
            return result
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def clean(body):
    body = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    body = re.sub(r"^\s*- \[[ xX]\].*$", "", body, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def main():
    fixes = {}
    # Require GitHub closing syntax, not a passing mention of an issue.
    pattern = re.compile(r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s+(?:https://github.com/streamlit/streamlit/issues/|streamlit/streamlit#|#)(\d+)", re.I)
    for page in range(1, 21):
        prs = get(f"repos/{REPO}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page={page}")
        for pr in prs:
            if pr.get("merged_at"):
                for number in pattern.findall(pr.get("body") or ""):
                    fixes.setdefault(int(number), pr)
        print(f"PR page {page}: {len(fixes)} explicit fixes", flush=True)
    cases, seen, descriptions = [], set(), []
    for page in range(1, 21):
        issues = get(f"repos/{REPO}/issues?state=closed&labels=type%3Abug&sort=updated&direction=desc&per_page=100&page={page}")
        if not issues:
            break
        for issue in issues:
            description = clean(issue.get("body"))
            fingerprint = hashlib.sha256(re.sub(r"\s+", " ", description.lower()).encode()).hexdigest()
            pr = fixes.get(issue["number"])
            labels = [label["name"] for label in issue["labels"]]
            normalized = re.sub(r"\s+", " ", description.lower())
            if "pull_request" in issue or not pr or len(description) < 350 or len(description.split()) < 55 or fingerprint in seen or any("duplicate" in label.lower() for label in labels) or issue.get("state_reason") == "not_planned":
                continue
            if any(SequenceMatcher(None, normalized, previous).ratio() >= 0.92 for previous in descriptions):
                continue
            seen.add(fingerprint)
            descriptions.append(normalized)
            cases.append({"id": f"{REPO}#{issue['number']}", "repository": REPO,
                "number": issue["number"], "title": issue["title"], "description": description,
                "labels": [label["name"] for label in issue["labels"]], "issue_url": issue["html_url"],
                "state": issue["state"], "closed_at": issue["closed_at"],
                "resolution": f"Resolved by merged PR #{pr['number']}: {pr['title']}.",
                "resolution_source": "merged_pull_request_title", "link_evidence": "explicit_closing_reference_in_pr_body",
                "related_pr": {"number": pr["number"], "title": pr["title"], "url": pr["html_url"],
                    "description": clean(pr.get("body")), "merged_at": pr["merged_at"], "merge_commit_sha": pr["merge_commit_sha"]}})
            if len(cases) == 100:
                break
        print(f"Issue page {page}: {len(cases)} eligible cases", flush=True)
        if len(cases) == 100:
            break
    if len(cases) < 90:
        raise RuntimeError(f"Only {len(cases)} verified cases; existing dataset was not replaced")
    (ROOT / "data" / "issues.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "data" / "provenance.json").write_text(json.dumps({
        "repository": "https://github.com/" + REPO, "assembled_at_utc": datetime.now(timezone.utc).isoformat(),
        "count": len(cases), "source": "GitHub public REST API; cached responses are reused on rerun",
        "selection": "100 most recently updated eligible closed type:bug reports matched against 2,000 recently updated closed PRs",
        "quality_rules": ["Merged PR with explicit closing reference", "At least 350 characters and 55 whitespace-separated words",
            "Remove HTML comments and template checkboxes", "Exclude duplicate labels and not_planned closures", "Unique issue IDs and normalized descriptions; reject description similarity >= 0.92"],
        "resolution": "Factual merged PR title, with full cleaned PR description retained; no inferred root cause",
        "limitations": "Single-repository convenience sample, not an exhaustive duplicate detector. Upstream issue and PR text may change."
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(cases)} verified cases", flush=True)


if __name__ == "__main__":
    main()
