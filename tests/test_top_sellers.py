"""
Test Suite — Top 20 Best-Sellers fuzzy match & validation
==========================================================
10 tests using the most popular items from Khulafa Bistro sales data.
"""
import pytest
from menu_validator import validate_menu_item, validate_order_items
from order_engine import MENU


class TestTopSellersFuzzyMatch:
    """Verify top-selling items resolve correctly via fuzzy match."""

    def test_teh_o_ais_exact(self):
        """#2 best-seller: teh o ais (pop=99)"""
        result = validate_menu_item("teh o ais")
        assert result["valid"] is True
        assert result["item_key"] == "teh o ais"
        assert result["price"] == 2.10

    def test_roti_canai_misspelled(self):
        """#3 best-seller: roti canai — misspelled as 'roti cana'"""
        result = validate_menu_item("roti cana")
        assert result["valid"] is True
        assert result["item_key"] == "roti canai"

    def test_nasi_ayam_exact(self):
        """#5 best-seller: nasi ayam (pop=48)"""
        result = validate_menu_item("nasi ayam")
        assert result["valid"] is True
        assert result["item_key"] == "nasi ayam"
        assert result["price"] == 7.52

    def test_ais_kosong_exact(self):
        """#1 best-seller: ais kosong (pop=133)"""
        result = validate_menu_item("ais kosong")
        assert result["valid"] is True
        assert result["item_key"] == "ais kosong"
        assert result["price"] == 0.30

    def test_milo_ais_fuzzy(self):
        """#7 best-seller: milo ais — typed as 'melo ais'"""
        result = validate_menu_item("melo ais")
        assert result["valid"] is True
        assert result["item_key"] == "milo ais"

    def test_nasi_ayam_sayur_exact(self):
        """#9 best-seller: nasi ayam sayur (pop=30)"""
        result = validate_menu_item("nasi ayam sayur")
        assert result["valid"] is True
        assert result["item_key"] == "nasi ayam sayur"
        assert result["price"] == 8.03

    def test_ayam_goreng_exact(self):
        """#11 best-seller: ayam goreng (pop=25)"""
        result = validate_menu_item("ayam goreng")
        assert result["valid"] is True
        assert result["item_key"] == "ayam goreng"
        assert result["price"] == 5.00

    def test_maggi_goreng_misspelled(self):
        """#22 best-seller: maggi goreng — misspelled as 'magi goreng'"""
        result = validate_menu_item("magi goreng")
        assert result["valid"] is True
        assert result["item_key"] == "maggi goreng"

    def test_mee_goreng_mamak_exact(self):
        """#17 best-seller: mee goreng mamak (pop=17)"""
        result = validate_menu_item("mee goreng mamak")
        assert result["valid"] is True
        assert result["item_key"] == "mee goreng mamak"
        assert result["price"] == 6.00

    def test_top_sellers_have_popularity(self):
        """All top 10 items must have popularity > 0."""
        top10 = sorted(MENU.items(), key=lambda x: x[1].get("popularity", 0), reverse=True)[:10]
        for name, data in top10:
            assert data.get("popularity", 0) > 0, f"{name} has no popularity"
