import unittest

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


if __name__ == "__main__":
    unittest.main()
