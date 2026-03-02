# tests/test_aisha_voice.py
"""
P1 PRIORITY — Wrong audio match = wrong voice plays to customer.
Tests AishaVoice: metadata loading, fuzzy matching, segment splitting.
"""
import pytest
import os
from unittest.mock import patch, mock_open
from aisha_voice import AishaVoice


# Fake metadata for deterministic tests (no dependency on real WAV files)
FAKE_METADATA = """0001|Selamat datang!
0005|Selamat pagi! Saya Aisha, boleh saya ambil pesanan anda?
0006|Selamat tengah hari! Saya Aisha, nak pesan apa hari ini?
0007|Selamat petang! Saya Aisha, boleh saya ambil pesanan anda?
0008|Selamat malam! Saya Aisha, selamat datang ke Khulafa Bistro.
0021|Terima kasih! Pesanan sudah dihantar ke dapur.
0043|Ada lagi?
0045|Boleh ulang?
0051|Roti canai.
0052|Roti canai satu.
0054|Roti telur.
0081|Roti canai susu."""


@pytest.fixture
def aisha(tmp_path):
    """AishaVoice loaded from fake metadata in a temp directory."""
    # Write fake metadata
    meta_file = tmp_path / "metadata.csv"
    meta_file.write_text(FAKE_METADATA, encoding="utf-8")

    # Create some fake WAV files so audio_exists checks work
    wavs_dir = tmp_path / "wavs"
    wavs_dir.mkdir()
    for fid in ["0001", "0005", "0006", "0007", "0008", "0021", "0043", "0045", "0051", "0052", "0054", "0081"]:
        (wavs_dir / f"{fid}.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")

    return AishaVoice(
        audio_dir=str(wavs_dir),
        metadata_path=str(meta_file),
    )


# ============================================================
# Metadata Loading
# ============================================================


class TestMetadataLoading:

    def test_metadata_loads(self, aisha):
        assert len(aisha.entries) > 0

    def test_metadata_count(self, aisha):
        # Our fake metadata has 12 entries
        assert len(aisha.entries) == 12

    def test_entries_have_required_fields(self, aisha):
        for entry in aisha.entries:
            assert "id" in entry
            assert "text" in entry
            assert "text_lower" in entry

    def test_text_index_built(self, aisha):
        assert len(aisha.text_index) > 0
        assert "roti canai." in aisha.text_index

    def test_missing_metadata_file(self, tmp_path):
        """Should not crash if metadata file is missing."""
        aisha = AishaVoice(
            audio_dir=str(tmp_path),
            metadata_path=str(tmp_path / "nonexistent.csv"),
        )
        assert len(aisha.entries) == 0


# ============================================================
# find_best_match
# ============================================================


class TestFindBestMatch:

    def test_exact_match(self, aisha):
        match = aisha.find_best_match("Roti canai.")
        assert match is not None
        assert match["id"] == "0051"
        assert match["score"] == 1.0

    def test_exact_match_case_insensitive(self, aisha):
        match1 = aisha.find_best_match("roti canai.")
        match2 = aisha.find_best_match("ROTI CANAI.")
        assert match1 is not None
        assert match2 is not None
        assert match1["id"] == match2["id"]

    def test_punctuation_insensitive(self, aisha):
        """'Roti canai' (no period) should match 'Roti canai.'"""
        match = aisha.find_best_match("Roti canai")
        assert match is not None
        assert match["id"] == "0051"
        assert match["score"] >= 0.95

    def test_empty_string_returns_none(self, aisha):
        # Empty entries list in a fresh AishaVoice won't match anything
        empty_aisha = AishaVoice(audio_dir="/tmp", metadata_path="/tmp/nonexistent")
        assert empty_aisha.find_best_match("") is None

    def test_gibberish_below_threshold(self, aisha):
        match = aisha.find_best_match("xyzabc123qqqq")
        assert match is None

    def test_fuzzy_match_typo(self, aisha):
        """'Roti canai saru' (typo) should fuzzy match 'Roti canai satu.'"""
        match = aisha.find_best_match("Roti canai saru.")
        assert match is not None
        assert "canai" in match["text"].lower()

    def test_result_has_audio_path(self, aisha):
        match = aisha.find_best_match("Ada lagi?")
        assert match is not None
        assert "audio_path" in match
        assert match["audio_path"].endswith(".wav")

    def test_result_audio_exists_flag(self, aisha):
        match = aisha.find_best_match("Ada lagi?")
        assert match is not None
        assert match["audio_exists"] is True


# ============================================================
# find_matches_in_response
# ============================================================


class TestFindMatchesInResponse:

    def test_single_sentence(self, aisha):
        matches = aisha.find_matches_in_response("Roti canai.")
        assert len(matches) >= 1

    def test_multi_sentence(self, aisha):
        response = "Roti canai satu. Ada lagi?"
        matches = aisha.find_matches_in_response(response)
        assert len(matches) >= 2

    def test_empty_response(self, aisha):
        matches = aisha.find_matches_in_response("")
        assert matches == []

    def test_no_match_response(self, aisha):
        matches = aisha.find_matches_in_response("xyzabc.")
        assert matches == []


# ============================================================
# get_greeting
# ============================================================


class TestGetGreeting:

    def test_morning_greeting(self, aisha):
        match = aisha.get_greeting("morning")
        assert match is not None
        assert "pagi" in match["text"].lower()

    def test_night_greeting(self, aisha):
        match = aisha.get_greeting("night")
        assert match is not None
        assert "malam" in match["text"].lower()

    def test_default_greeting(self, aisha):
        match = aisha.get_greeting("default")
        # default may or may not match, but should not crash
        assert match is None or "text" in match


# ============================================================
# get_menu_item_audio
# ============================================================


class TestGetMenuItemAudio:

    def test_find_menu_audio(self, aisha):
        match = aisha.get_menu_item_audio("Roti canai")
        assert match is not None
        assert "canai" in match["text"].lower()

    def test_unknown_item_returns_none(self, aisha):
        match = aisha.get_menu_item_audio("Pizza Hawaii")
        assert match is None


# ============================================================
# stats
# ============================================================


class TestStats:

    def test_stats_returns_dict(self, aisha):
        s = aisha.stats()
        assert "total_entries" in s
        assert "audio_files_found" in s
        assert "audio_files_missing" in s
        assert "categories" in s

    def test_total_entries_correct(self, aisha):
        s = aisha.stats()
        assert s["total_entries"] == 12

    def test_all_fake_audio_found(self, aisha):
        s = aisha.stats()
        assert s["audio_files_found"] == 12
        assert s["audio_files_missing"] == 0


# ============================================================
# get_all_entries
# ============================================================


class TestGetAllEntries:

    def test_returns_list(self, aisha):
        entries = aisha.get_all_entries()
        assert isinstance(entries, list)
        assert len(entries) == 12

    def test_entries_have_fields(self, aisha):
        entries = aisha.get_all_entries()
        for e in entries:
            assert "id" in e
            assert "text" in e
            assert "audio_path" in e
