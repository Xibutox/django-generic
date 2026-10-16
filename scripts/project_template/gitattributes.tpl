# Line endings the containers read: a shell script or a Caddyfile with
# Windows line endings fails in Linux, whatever git's core.autocrlf.
*.sh text eol=lf
*.py text eol=lf
*.yml text eol=lf
*.env text eol=lf
Caddyfile text eol=lf
Dockerfile text eol=lf
vendor/*.whl binary
