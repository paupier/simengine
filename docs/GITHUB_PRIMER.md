# GitHub Primer for Simantha OPC UA Project

A practical guide to using GitHub for this project, tailored for those new to the platform.

---

## 🎯 What is GitHub?

GitHub is a platform for:
- **Version control** (tracking changes to code)
- **Collaboration** (multiple people working on the same project)
- **Project management** (issues, milestones, project boards)
- **Documentation** (README, wikis, discussions)

Think of it as "Google Docs for code" with powerful project management tools.

---

## 📦 Core Concepts

### 1. Repository (Repo)
A project folder containing all files, history, and documentation.

```
simantha-opcua/          <- Your repository
├── src/                 <- Source code
├── tests/               <- Test files
├── docs/                <- Documentation
└── README.md            <- Project homepage
```

### 2. Commit
A snapshot of changes with a descriptive message.

```bash
git add src/opcua_server.py        # Stage file
git commit -m "Add OPC UA server setup"  # Save snapshot
```

**Best practice:** Small, frequent commits with clear messages.

### 3. Branch
A parallel version of the code for working on features.

```
main ────────────────────── (stable)
      \
       feature/issue-5 ──── (work in progress)
```

### 4. Pull Request (PR)
A request to merge your branch into main after review.

### 5. Issue
A task, bug report, or feature request. Think "to-do item."

### 6. Project Board
Kanban board for tracking issues (Backlog → In Progress → Testing → Done).

---

## 🚀 Getting Started

### Step 1: Create Repository

**On GitHub.com:**
1. Click "+" (top right) → "New repository"
2. Name: `simantha-opcua`
3. Description: "OPC UA server for Simantha manufacturing simulations"
4. ✅ Public or Private (your choice)
5. ✅ Add README
6. ✅ Add .gitignore → Python
7. ✅ License → Public Domain (or MIT)
8. Click "Create repository"

### Step 2: Clone to Your Computer

```bash
# Get the repository URL from GitHub (green "Code" button)
git clone https://github.com/YOUR-USERNAME/simantha-opcua.git
cd simantha-opcua
```

You now have a local copy!

### Step 3: Set Up Development Environment

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# or
source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

---

## 📝 Basic Git Workflow

### Scenario: Adding Phase 1 baseline simulation

```bash
# 1. Make sure you're on main branch and up to date
git checkout main
git pull origin main

# 2. Create a new branch for your work
git checkout -b feature/issue-1-baseline-sim

# 3. Create/edit files
# Write src/simantha_baseline.py
# Write tests/test_scenarios.py

# 4. Check what changed
git status

# 5. Stage files (prepare for commit)
git add src/simantha_baseline.py
git add tests/test_scenarios.py

# Or stage everything:
git add .

# 6. Commit with descriptive message
git commit -m "Add baseline simulation with 3 test scenarios

- Implement 2-machine 1-buffer line
- Add Scenario A (balanced), B (bottleneck), C (failures)
- Export results to CSV
- Closes #1"

# 7. Push to GitHub
git push origin feature/issue-1-baseline-sim
```

### Commit Message Best Practices

**Good:**
```
Add OPC UA server with read-only variables

- Configure endpoint opc.tcp://localhost:4840
- Create System, M1, M2, B1 folders
- Map Simantha states to OPC UA strings
- Add integration layer for state updates

Closes #5
```

**Bad:**
```
fixed stuff
```

**Format:**
```
<Type>: <Short summary> (50 chars max)

<Detailed description>
- Bullet points for multiple changes
- Reference issue numbers

Closes #XX
```

---

## 🎯 Working with Issues

### Creating an Issue

1. Go to your repo on GitHub.com
2. Click "Issues" tab → "New issue"
3. Title: `[PHASE-1] Setup Development Environment`
4. Description:
   ```
   Install required dependencies and configure environment.

   Tasks:
   - [ ] Install Python 3.8+
   - [ ] Create virtual environment
   - [ ] Install simantha, scipy, pandas
   - [ ] Verify installation

   Acceptance: No import errors, simantha.__version__ displayed
   ```
5. Assign to yourself
6. Add labels: `phase-1`, `setup`
7. Set milestone: `Phase 1: Simantha Baseline`
8. Click "Submit new issue"

You now have Issue #1!

### Working on an Issue

```bash
# Create branch named after issue
git checkout -b feature/issue-1-dev-setup

# Do work...

# Commit referencing issue
git commit -m "Setup development environment

Installed all dependencies and verified Simantha import.

Relates to #1"

# Push and create PR
git push origin feature/issue-1-dev-setup
```

On GitHub, create Pull Request:
1. Click "Compare & pull request" button
2. Title: `Setup development environment (Issue #1)`
3. Description: Describe what you did, link to issue
4. Click "Create pull request"

---

## 📊 Project Board Setup

### Creating the Board

1. Go to "Projects" tab → "New project"
2. Select "Board" view
3. Name: "Simantha OPC UA Development"
4. Description: "Phased development tracker"
5. Click "Create"

### Add Columns

Default has "Todo", "In Progress", "Done". Customize:
1. Rename "Todo" → "📋 Backlog"
2. Keep "In Progress" → "🔄 In Progress"
3. Add column: "🧪 Testing"
4. Keep "Done" → "✅ Done"

### Link Issues to Board

1. Open an issue
2. Right sidebar → "Projects"
3. Select your project board
4. Issue appears in Backlog column

### Move Issues

Drag and drop between columns as you work:
- **Backlog:** Not started
- **In Progress:** Actively working
- **Testing:** Code written, running tests
- **Done:** Tests passed, PR merged

---

## 🏷️ Labels

### Create Labels

Settings → Labels → New label

Suggested labels:
- `phase-1` through `phase-6` (green shades)
- `bug` (red)
- `enhancement` (blue)
- `documentation` (yellow)
- `testing` (purple)
- `priority-high` (orange)

### Apply Labels

On any issue, right sidebar → Labels → check boxes

---

## 🎯 Milestones

### Create Milestones

Issues → Milestones → New milestone

Example:
- **Title:** Phase 1: Simantha Baseline
- **Due date:** 2026-02-03 (1 day from start)
- **Description:** Validate Simantha library and establish baseline simulation models

Repeat for Phase 2-6.

### Assign Issues to Milestones

On issue page, right sidebar → Milestone → select

Track progress: Milestones page shows "X of Y issues complete"

---

## 🔄 Pull Request Workflow

### 1. Create PR

After pushing branch:
```bash
git push origin feature/issue-5-opcua-server
```

On GitHub:
1. Click "Compare & pull request"
2. **Base:** `main` ← **Compare:** `feature/issue-5-opcua-server`
3. Title: `Add OPC UA server with read-only variables`
4. Description:
   ```
   ## Changes
   - Created opcua_server.py with endpoint configuration
   - Added System, M1, M2, B1 folders to address space
   - Implemented state mapping layer

   ## Testing
   - [x] Server starts without errors
   - [x] UA Expert connects successfully
   - [x] All variables browseable

   Closes #5, Closes #6, Closes #7
   ```
5. Link to project (right sidebar → Projects)
6. Click "Create pull request"

### 2. Review (if working with team)

Team members can:
- Comment on code
- Request changes
- Approve

For solo projects, self-review:
1. Check "Files changed" tab
2. Verify all changes intentional
3. Approve your own PR (or just merge)

### 3. Merge

Once tests pass:
1. Click "Merge pull request"
2. Choose merge strategy:
   - **Create a merge commit** (recommended for features)
   - **Squash and merge** (combine all commits into one)
   - **Rebase and merge** (advanced)
3. Click "Confirm merge"
4. Delete branch (click "Delete branch" button)

### 4. Update Local

```bash
git checkout main
git pull origin main
git branch -d feature/issue-5-opcua-server  # Delete local branch
```

---

## 🔍 Common Commands

### Daily Workflow

```bash
# Check status
git status

# See what changed
git diff

# See commit history
git log --oneline --graph

# Undo changes to file (before commit)
git checkout -- filename.py

# Undo last commit (keep changes)
git reset --soft HEAD~1

# Update from main
git checkout main
git pull origin main
```

### Branch Management

```bash
# List branches
git branch

# Switch branches
git checkout branch-name

# Create and switch
git checkout -b feature/new-feature

# Delete branch
git branch -d feature/old-feature

# See remote branches
git branch -r
```

### Fixing Mistakes

```bash
# Forgot to add file to commit
git add forgotten_file.py
git commit --amend --no-edit

# Wrong commit message
git commit --amend -m "Correct message"

# Pushed wrong code (careful!)
git revert HEAD  # Creates new commit undoing last
git push origin main
```

---

## 📋 Workflow Example: Complete Phase 1

### Day 1: Issue #1

```bash
# Morning
git checkout main
git pull
git checkout -b feature/issue-1-dev-setup

# Work: install dependencies
pip install -r requirements.txt
python -c "import simantha; print(simantha.__version__)"

# Commit
git add requirements.txt
git commit -m "Setup development environment

Installed simantha, scipy, pandas, pytest.
Verified installation successful.

Closes #1"

git push origin feature/issue-1-dev-setup

# On GitHub: Create PR, merge
```

### Day 1: Issue #2

```bash
# Afternoon
git checkout main
git pull  # Get Issue #1 changes
git checkout -b feature/issue-2-baseline-model

# Work: write src/simantha_baseline.py
# Test: python src/simantha_baseline.py

git add src/simantha_baseline.py
git commit -m "Add baseline simulation model

- Implement 2-machine 1-buffer line
- Configure Source, M1, B1, M2, Sink
- Run 100s simulation horizon

Relates to #2"

git push origin feature/issue-2-baseline-model

# GitHub: Create PR, merge
```

### Day 1: Issue #3

```bash
git checkout main
git pull
git checkout -b feature/issue-3-test-scenarios

# Work: write tests/test_scenarios.py
# Test: pytest tests/test_scenarios.py -v

git add tests/test_scenarios.py
git add results/phase1/  # CSV outputs
git commit -m "Add Phase 1 test scenarios

- Scenario A (balanced): ✓
- Scenario B (bottleneck): ✓
- Scenario C (failures): ✓

All tests pass. CSV outputs saved.

Closes #3"

git push origin feature/issue-3-test-scenarios

# GitHub: PR, merge
```

### Day 1 Evening: Close Phase 1

1. Check Project Board: All Issue #1-4 in "Done"
2. Go to Milestones → Phase 1 → 100% complete
3. Close milestone
4. Update README: Phase 1 status → ✅ Complete

---

## 🎨 GitHub Features to Use

### 1. README Badges

Top of README.md:
```markdown
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/YOUR-USERNAME/simantha-opcua/actions/workflows/tests.yml/badge.svg)](https://github.com/YOUR-USERNAME/simantha-opcua/actions)
```

### 2. GitHub Actions (CI/CD)

Auto-run tests on every push (already in `.github/workflows/tests.yml`).

View results: Actions tab on GitHub

### 3. Discussions

Enable: Settings → Features → ✅ Discussions

Use for:
- Q&A about implementation
- Brainstorming new features
- Announcements

### 4. Wiki

Enable: Settings → Features → ✅ Wiki

Use for:
- Detailed technical docs
- Architecture diagrams
- Tutorials

### 5. Releases

After Phase completion:
1. Code → Releases → "Draft a new release"
2. Tag: `v1.0-phase1`
3. Title: "Phase 1: Simantha Baseline"
4. Description: Summary of deliverables
5. Attach: `results/phase1/` as ZIP
6. Publish

---

## 🛠️ Recommended Tools

### Git GUI Clients (if you prefer visual)

- **GitHub Desktop** (easiest) - https://desktop.github.com/
- **GitKraken** (powerful) - https://www.gitkraken.com/
- **SourceTree** (free) - https://www.sourcetreeapp.com/

### VS Code Extensions

- **GitLens** - Enhanced Git integration
- **GitHub Pull Requests** - Manage PRs in VS Code
- **Python** - Linting, debugging
- **YAML** - Config file support

### Command Line Aliases

Add to `~/.gitconfig`:
```ini
[alias]
    st = status
    co = checkout
    br = branch
    ci = commit
    lg = log --oneline --graph --decorate --all
```

Now use: `git st` instead of `git status`

---

## 🚨 Common Pitfalls

### 1. Committing to main directly

❌ Bad:
```bash
git checkout main
# edit files
git commit -m "changes"
git push
```

✅ Good:
```bash
git checkout -b feature/my-changes
# edit files
git commit -m "changes"
git push origin feature/my-changes
# Create PR on GitHub
```

### 2. Large binary files

Don't commit:
- `results/*.csv` (add to .gitignore)
- Screenshots (link to external storage or use GitHub Releases)
- Virtual environment (`venv/`)

### 3. Vague commit messages

❌ "fixed bug"  
✅ "Fix OPC UA connection timeout in opcua_server.py (Issue #12)"

### 4. Not pulling before pushing

Always:
```bash
git pull origin main  # Get latest changes
# Then work and push
```

---

## 📚 Learning Resources

- **GitHub Docs:** https://docs.github.com/
- **Git Cheat Sheet:** https://training.github.com/downloads/github-git-cheat-sheet/
- **Interactive Tutorial:** https://learngitbranching.js.org/
- **Video Course:** https://www.youtube.com/githubguides

---

## ✅ Quick Reference

| Task | Command |
|------|---------|
| Clone repo | `git clone <url>` |
| Create branch | `git checkout -b feature/name` |
| Stage changes | `git add filename` or `git add .` |
| Commit | `git commit -m "message"` |
| Push | `git push origin branch-name` |
| Update from main | `git pull origin main` |
| Check status | `git status` |
| See history | `git log --oneline` |
| Undo changes | `git checkout -- filename` |

---

**Next Steps:**
1. Create your GitHub repository
2. Clone to local machine
3. Create Issue #1: Setup Development Environment
4. Start Phase 1!

Good luck! 🚀
