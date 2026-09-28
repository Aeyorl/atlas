"""Publish official token CA and deploy live."""
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = REPO_ROOT / "web" / "index.html"


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/publish_ca.py <CONTRACT_ADDRESS>")
        sys.exit(1)

    ca = sys.argv[1].strip()
    if not ca:
        print("Error: contract address cannot be empty")
        sys.exit(1)

    print(f"Updating web/index.html with CA: {ca}...")
    content = INDEX_PATH.read_text(encoding="utf-8")
    content = re.sub(r'data-token-ca="[^"]*"', f'data-token-ca="{ca}"', content)
    content = re.sub(r'<code id="tokenCaValue">[^<]*</code>', f'<code id="tokenCaValue">{ca}</code>', content)
    content = content.replace('<div class="hero-ca" hidden', '<div class="hero-ca"')
    INDEX_PATH.write_text(content, encoding="utf-8")

    print("Pushing to GitHub (fork main)...")
    subprocess.run(["git", "add", "web/index.html", "web/landing.css", "web/landing.js"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"feat(web): publish official community token CA {ca}"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "push", "fork", "main"], cwd=REPO_ROOT, check=True)

    print("Deploying live to Vercel production...")
    subprocess.run(["npx", "--yes", "vercel", "--prod", "--yes"], cwd=REPO_ROOT / "web", check=True)
    print("\nSUCCESS! Official CA is live on https://www.niveprotocol.xyz")


if __name__ == "__main__":
    main()
