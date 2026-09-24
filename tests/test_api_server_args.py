import unittest
from unittest.mock import patch


from fabos_api.server import _parse_args


class ApiServerArgsTests(unittest.TestCase):
    def test_parse_explicit_service_arguments(self):
        args = _parse_args(
            [
                "--host",
                "127.0.0.1",
                "--port",
                "8123",
                "--threads",
                "4",
                "--data-dir",
                r"C:\FabVex\Data",
            ]
        )
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8123)
        self.assertEqual(args.threads, 4)
        self.assertEqual(args.data_dir, r"C:\FabVex\Data")

    def test_parse_environment_file_argument(self):
        args = _parse_args(["--env-file", r"C:\FabVex\FabOS-Web\deployment\windows\server.env"])
        self.assertEqual(args.env_file, r"C:\FabVex\FabOS-Web\deployment\windows\server.env")

    def test_load_env_file_preserves_explicit_environment(self):
        import os
        import tempfile
        from fabos_api.server import _load_env_file

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("TEST_FABOS_ENV=from-file\n")
            handle.write("TEST_FABOS_QUOTED=\"quoted value\"\n")
            path = handle.name
        try:
            previous = os.environ.get("TEST_FABOS_ENV")
            previous_quoted = os.environ.get("TEST_FABOS_QUOTED")
            os.environ["TEST_FABOS_ENV"] = "explicit"
            os.environ.pop("TEST_FABOS_QUOTED", None)
            try:
                _load_env_file(path)
                self.assertEqual(os.environ["TEST_FABOS_ENV"], "explicit")
                self.assertEqual(os.environ["TEST_FABOS_QUOTED"], "quoted value")
            finally:
                if previous is None:
                    os.environ.pop("TEST_FABOS_ENV", None)
                else:
                    os.environ["TEST_FABOS_ENV"] = previous
                if previous_quoted is None:
                    os.environ.pop("TEST_FABOS_QUOTED", None)
                else:
                    os.environ["TEST_FABOS_QUOTED"] = previous_quoted
        finally:
            import os as _os
            _os.unlink(path)
    def test_missing_waitress_fails_before_core_startup(self):
        import fabos_api.server as server

        with patch.object(server, "serve", None), patch.object(server, "FabOSApplication") as application:
            with self.assertRaisesRegex(RuntimeError, "Waitress is required"):
                server.run()
            application.assert_not_called()


if __name__ == "__main__":
    unittest.main()
