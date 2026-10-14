import csv
import os
import unittest


class SmokeTests(unittest.TestCase):
    def test_items_csv_is_present_and_has_data(self):
        project_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(project_dir, 'csvs', 'items.csv')
        with open(csv_path, encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(rows, 'items.csv should contain at least one listing row')
        self.assertIn('Title', rows[0])

    def test_web_app_port_is_expected(self):
        import web_app
        self.assertEqual(web_app.PORT, 8765)


if __name__ == '__main__':
    unittest.main()
