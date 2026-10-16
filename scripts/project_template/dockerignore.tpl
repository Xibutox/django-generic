# What never goes into an image: local environments, caches, databases,
# collected files, backups and above all the secrets.
.git
.venv
venv
**/__pycache__
**/*.py[cod]
*.egg-info
build
dist
.pytest_cache
.coverage
htmlcov
**/*.sqlite3
**/*.log
logs
staticfiles
media
backups
.env
docker/*.env
docker/*.env.bak-*
