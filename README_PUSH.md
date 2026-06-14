Run the automated push helper to add a remote, commit local changes, and push `main` to GitHub.

Steps

1) Make the script executable and run it from the project root:

```bash
cd /Users/clemeze/Desktop/ai201-project2-fitfindr-starter
chmod +x push_to_github.sh
./push_to_github.sh
```

2) Authentication options
- Recommended: install GitHub CLI and run `gh auth login` to authenticate via browser.
- Alternatively, push via HTTPS and provide credentials or a Personal Access Token when prompted.
- If you prefer SSH, open `push_to_github.sh` and change `REMOTE_URL` to `git@github.com:clem0g/NVIDIA_Jetson_Nano_AI_Agent_2.0.git` before running.

3) Verify
- After the script completes, open: https://github.com/clem0g/NVIDIA_Jetson_Nano_AI_Agent_2.0

Notes
- I cannot push from here (no network/auth access). This script performs the push locally on your machine.
- If you see authentication errors, run `gh auth login` or create a PAT with `repo` scope and use it when prompted.
