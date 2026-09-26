"""debug.py: the project under a debugger, in one process."""

import sys
import types

import pytest

import debug


class TestParse:
    def test_nothing_asked(self):
        assert debug.parse([]) == {
            "listen": None,
            "wait": False,
            "reload": False,
            "rest": [],
        }

    def test_the_debugger_options_are_taken_out(self):
        options = debug.parse(
            ["--listen", "0.0.0.0:5678", "--wait", "0.0.0.0:8000"]
        )

        assert options["listen"] == "0.0.0.0:5678"
        assert options["wait"] is True
        assert options["rest"] == ["0.0.0.0:8000"]

    def test_listen_with_an_equals_sign(self):
        assert debug.parse(["--listen=6000"])["listen"] == "6000"

    @pytest.mark.parametrize(
        "argv",
        [["--listen"], ["--listen", "--wait"], ["--listen", "shell"]],
    )
    def test_listen_alone_takes_the_default_port(self, argv):
        options = debug.parse(argv)

        assert options["listen"] == debug.DEFAULT_LISTEN
        assert options["rest"] == [
            argument for argument in argv[1:] if argument != "--wait"
        ]

    def test_reload(self):
        assert debug.parse(["--reload"])["reload"] is True

    def test_vs_code_s_prompt_is_split(self):
        # launch.json's "${input:command}" arrives as one argument.
        assert debug.parse(["migrate generic 0012"])["rest"] == [
            "migrate",
            "generic",
            "0012",
        ]

    def test_a_single_word_is_left_whole(self):
        assert debug.parse(["seed_example"])["rest"] == ["seed_example"]


class TestSplit:
    def test_quotes_group(self):
        assert debug.split('shell -c "print(1)"', windows=False) == [
            "shell",
            "-c",
            "print(1)",
        ]

    def test_windows_paths_keep_their_backslashes(self):
        assert debug.split(
            r'loaddata C:\data\x.json "C:\my data\y.json"', windows=True
        ) == ["loaddata", r"C:\data\x.json", r"C:\my data\y.json"]


class TestCommandLine:
    def test_the_server_by_default_without_the_reloader(self):
        assert debug.command_line([], reload=False) == [
            "runserver",
            "--noreload",
            debug.DEFAULT_ADDRESS,
        ]

    @pytest.mark.parametrize(
        "address", ["8001", "0.0.0.0:8001", "localhost:8001", "[::1]:8001"]
    )
    def test_an_address_is_the_server_s(self, address):
        assert debug.command_line([address], reload=False) == [
            "runserver",
            "--noreload",
            address,
        ]

    def test_runserver_named_with_its_options(self):
        assert debug.command_line(
            ["runserver", "--nostatic", "8002"], reload=False
        ) == ["runserver", "--noreload", "--nostatic", "8002"]

    def test_options_alone_get_the_default_address(self):
        assert debug.command_line(["--nostatic"], reload=False) == [
            "runserver",
            "--noreload",
            "--nostatic",
            debug.DEFAULT_ADDRESS,
        ]

    def test_the_reloader_when_asked(self):
        assert debug.command_line([], reload=True) == [
            "runserver",
            debug.DEFAULT_ADDRESS,
        ]

    def test_noreload_is_not_repeated(self):
        assert debug.command_line(["runserver", "--noreload"], False) == [
            "runserver",
            "--noreload",
            debug.DEFAULT_ADDRESS,
        ]

    @pytest.mark.parametrize(
        "rest",
        [
            ["seed_example"],
            ["migrate", "generic", "0012"],
            ["shell", "-c", "print(1)"],
            ["oauth2"],
        ],
    )
    def test_any_other_command_is_run_as_it_is(self, rest):
        assert debug.command_line(rest, reload=False) == rest


class TestListenAddress:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("5678", ("127.0.0.1", 5678)),
            ("0.0.0.0:5678", ("0.0.0.0", 5678)),
            ("localhost:6000", ("localhost", 6000)),
            ("[::]:5678", ("::", 5678)),
        ],
    )
    def test_host_and_port(self, value, expected):
        assert debug.listen_address(value) == expected


class TestMain:
    @pytest.fixture
    def ran(self, monkeypatch):
        ran = []
        monkeypatch.setattr(
            "django.core.management.execute_from_command_line", ran.append
        )

        return ran

    @pytest.fixture
    def debugpy(self, monkeypatch):
        calls = []
        module = types.SimpleNamespace(
            listen=lambda address: calls.append(("listen", address)),
            wait_for_client=lambda: calls.append(("wait",)),
        )
        monkeypatch.setitem(sys.modules, "debugpy", module)

        return calls

    def test_runs_manage_py_s_command(self, ran, capsys):
        debug.main([])

        assert ran[0][1:] == ["runserver", "--noreload", "127.0.0.1:8000"]
        assert "manage.py runserver --noreload" in capsys.readouterr().out

    def test_keeps_the_settings_it_is_given(self, ran, monkeypatch):
        monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "tests.settings")

        debug.main(["check"])

        assert ran[0][1:] == ["check"]
        assert debug.os.environ["DJANGO_SETTINGS_MODULE"] == "tests.settings"

    def test_listens_then_waits(self, ran, debugpy):
        debug.main(["--listen", "0.0.0.0:5678", "--wait", "0.0.0.0:8000"])

        assert debugpy == [("listen", ("0.0.0.0", 5678)), ("wait",)]
        assert ran[0][1:] == ["runserver", "--noreload", "0.0.0.0:8000"]

    def test_listens_without_waiting(self, ran, debugpy):
        debug.main(["--listen"])

        assert debugpy == [("listen", ("127.0.0.1", 5678))]

    def test_listen_without_debugpy_says_what_to_install(
        self, ran, monkeypatch
    ):
        monkeypatch.setitem(sys.modules, "debugpy", None)

        with pytest.raises(SystemExit, match="pip install debugpy"):
            debug.main(["--listen"])

        assert ran == []

    def test_listen_and_reload_are_refused(self, ran, debugpy):
        with pytest.raises(SystemExit, match="do not go together"):
            debug.main(["--listen", "--reload"])

        assert debugpy == []
        assert ran == []
