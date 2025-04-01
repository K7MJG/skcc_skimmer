import subprocess

def create_version_file():
    try:
        version = subprocess.check_output(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        # If we have a tag, we'll get its commit
        gitSha = subprocess.check_output(
            ["git", "rev-list", "-n", "1", version]
        ).strip().decode('utf-8')
    except subprocess.CalledProcessError:
        # No tag, use the current commit SHA
        gitSha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"]
        ).decode().strip()
        version = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"]
        ).decode().strip()

    # Check if there are modified files in the worktree
    status_output = subprocess.check_output(
        ["git", "status", "--porcelain"]
    ).decode().strip()

    if status_output:
        version += "-"

    commit_date = subprocess.check_output(
        ['git', 'show', '-s', '--format=%as', gitSha]
    ).strip().decode('utf-8')

    short_sha = subprocess.check_output(
        ['git', 'rev-parse', '--short', gitSha]
    ).strip().decode('utf-8')

    if version == short_sha:
        versionStamp = f'{version} / {commit_date}'
    else:
        versionStamp = f'{version} / {commit_date} ({short_sha})'

    with open(rf'cVersion.py', 'w', encoding='utf-8') as file:
        file.write(f"VERSION = '{versionStamp}'\n")

if __name__ == "__main__":
    create_version_file()