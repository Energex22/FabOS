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

    def test_missing_waitress_fails_before_core_startup(self):
        import fabos_api.server as server

        with patch.object(server, "serve", None), patch.object(server, "FabOSApplication") as application:
            with self.assertRaisesRegex(RuntimeError, "Waitress is required"):
                server.run()
            application.assert_not_called()


if __name__ == "__main__":
    unittest.main()
