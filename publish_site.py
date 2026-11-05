"""Send site/index.html to the live website (GitHub Pages).

Live site:  https://tradingzoo.github.io/token-watch/
Repo:       https://github.com/tradingzoo/token-watch  (public, holds only the page)

watch.py calls publish() after it rebuilds the page. Run this file by hand
to push the current page right now:  python publish_site.py
Only the page is sent: no code, data or keys.
"""
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site", "index.html")
REPO = os.path.join(HERE, "publish")          # local copy of the website repo
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _git(*args):
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True,
                          timeout=120, creationflags=NO_WINDOW)


def publish(log=print):
    if os.environ.get("GITHUB_ACTIONS"):
        # Running on GitHub's servers: this folder IS the website repo. The page goes at the top
        # (where GitHub Pages serves it) and the workflow commits and pushes everything.
        shutil.copyfile(SITE, os.path.join(HERE, "index.html"))
        log("Live site: page copied, the workflow pushes it")
        return
    if not os.path.isdir(os.path.join(REPO, ".git")):
        log("Live site: skipped (publish folder not set up)")
        return
    shutil.copyfile(SITE, os.path.join(REPO, "index.html"))
    _git("add", "index.html")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        log("Live site: no change")
        return
    _git("commit", "-m", "Update token watch")
    r = _git("push", "origin", "main")
    log("Live site: updated" if r.returncode == 0 else f"Live site: push failed ({r.stderr.strip()[:200]})")


if __name__ == "__main__":
    publish()
