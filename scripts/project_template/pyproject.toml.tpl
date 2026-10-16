[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "{{ slug }}"
version = "0.1.0"
description = "{{ title }}, built on django-generic."
requires-python = ">=3.10"
dependencies = [
    # From vendor/ (requirements.txt names the wheel by its path): the
    # name on PyPI is an unrelated package - never install it by name.
    "django-generic[export,events,tasks,postgres,wiki]>={{ version }},<2",
    # The password hasher OWASP recommends (settings/base.py).
    "argon2-cffi>=23.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-django>=4.8",
    "black>=24",
    "isort>=5.13",
    "flake8>=7",
    "pip-audit>=2.7",
    "django-debug-toolbar>=4.4",
]

[tool.setuptools.packages.find]
include = ["{{ project }}*", "{{ app }}*"]

[tool.black]
line-length = 79

[tool.isort]
profile = "black"
line_length = 79

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "tests.settings"
python_files = ["test_*.py"]
testpaths = ["tests"]
