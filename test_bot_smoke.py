import unittest


class BotSmokeTests(unittest.TestCase):
    def test_basic_import(self):
        import main
        self.assertTrue(hasattr(main, 'run'))


if __name__ == '__main__':
    unittest.main()
