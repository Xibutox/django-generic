__pycache__/
*.py[cod]
*.egg-info/
build/
dist/
.venv/
venv/
.pytest_cache/
.coverage
htmlcov/
*.sqlite3
staticfiles/
media/
logs/

# Secrets and backups never go into the repository (ISO/IEC 27002
# 5.17, 8.13): `python ops.py env` writes the first, `python ops.py
# backup` the second. Keep a copy of docker/prod.env in a password
# manager or a safe: without BACKUP_PASSPHRASE no backup can be read.
docker/dev.env
docker/prod.env
docker/*.env.bak-*
backups/
