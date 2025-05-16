# Em tests/test_sefaz.py
import unittest
from monitor.utils.sefaz_scraper import SEFAZScraper

class TestSEFAZScraper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scraper = SEFAZScraper()
    
    def test_decreto_21866(self):
        self.assertTrue(self.scraper.check_norm_status("DECRETO", "21866"))
    
    def test_lei_4257(self):
        self.assertTrue(self.scraper.check_norm_status("LEI", "4.257"))