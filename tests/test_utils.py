import unittest
from utils import reverse_string


class TestUtils(unittest.TestCase):
    def test_reverse(self):
        self.assertEqual(reverse_string('abc'), 'cba')


if __name__ == '__main__':
    unittest.main()
