"""
Aisha Voice Audio Matching System
==================================
Maps Claude AI text responses to pre-recorded ElevenLabs audio files.
Zero API cost - just plays matching audio files.

How it works:
1. Claude generates a text response (e.g. "Roti canai satu.")
2. This module finds the closest matching pre-recorded audio
3. Returns the audio file path to play to the customer

Setup:
- Place WAV files in /static/audio/wavs/
- metadata.csv maps file IDs to text
"""

import os
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


class AishaVoice:
    """Pre-recorded audio response system for restaurant voice ordering."""
    
    def __init__(self, audio_dir: str = "static/audio/wavs", metadata_path: str = "static/audio/metadata.csv"):
        self.audio_dir = audio_dir
        self.entries = []  # list of {"id": "0001", "text": "Selamat datang!", "text_lower": "selamat datang!"}
        self.text_index = {}  # exact text -> file_id mapping
        
        self._load_metadata(metadata_path)
        print(f"[AishaVoice] Loaded {len(self.entries)} audio entries")
    
    def _load_metadata(self, metadata_path: str):
        """Load metadata.csv: id|text format"""
        if not os.path.exists(metadata_path):
            print(f"[AishaVoice] WARNING: {metadata_path} not found!")
            return
        
        with open(metadata_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "|" in line:
                    parts = line.split("|", 1)
                    if len(parts) == 2:
                        file_id = parts[0].strip()
                        text = parts[1].strip()
                        text_lower = text.lower().strip()
                        
                        entry = {
                            "id": file_id,
                            "text": text,
                            "text_lower": text_lower,
                            "words": set(re.findall(r'\w+', text_lower))
                        }
                        self.entries.append(entry)
                        self.text_index[text_lower] = file_id
    
    def find_best_match(self, query: str, threshold: float = 0.5) -> dict | None:
        """
        Find the best matching audio for a given text query.
        
        Args:
            query: The text to match (e.g., Claude's response)
            threshold: Minimum similarity score (0.0-1.0)
        
        Returns:
            {"id": "0051", "text": "Roti canai.", "score": 0.95, "audio_path": "/audio/wavs/0051.wav"}
            or None if no good match
        """
        if not self.entries:
            return None
        
        query_lower = query.lower().strip()
        
        # 1. Try exact match first
        if query_lower in self.text_index:
            file_id = self.text_index[query_lower]
            return self._make_result(file_id, query, 1.0)
        
        # 2. Try exact match without punctuation
        query_clean = re.sub(r'[^\w\s]', '', query_lower)
        for entry in self.entries:
            entry_clean = re.sub(r'[^\w\s]', '', entry["text_lower"])
            if query_clean == entry_clean:
                return self._make_result(entry["id"], entry["text"], 0.99)
        
        # 3. Fuzzy match using SequenceMatcher
        best_score = 0
        best_entry = None
        
        for entry in self.entries:
            score = SequenceMatcher(None, query_lower, entry["text_lower"]).ratio()
            if score > best_score:
                best_score = score
                best_entry = entry
        
        if best_score >= threshold and best_entry:
            return self._make_result(best_entry["id"], best_entry["text"], best_score)
        
        return None
    
    def find_matches_in_response(self, response_text: str) -> list[dict]:
        """
        For a longer AI response, find all matching audio segments.
        Splits response into sentences and matches each one.
        
        Args:
            response_text: Full AI response (may contain multiple sentences)
        
        Returns:
            List of matches with audio paths
        """
        # Split response into sentences
        sentences = re.split(r'[.!?]+', response_text)
        sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 2]
        
        matches = []
        for sentence in sentences:
            match = self.find_best_match(sentence + ".", threshold=0.6)
            if not match:
                match = self.find_best_match(sentence, threshold=0.6)
            if match:
                matches.append(match)
        
        return matches
    
    def get_greeting(self, time_of_day: str = "default") -> dict | None:
        """Get a greeting audio based on time of day."""
        greeting_map = {
            "morning": ["Selamat pagi, nak order apa hari ini?", "Good morning, welcome!"],
            "afternoon": ["Selamat tengahari, nak makan apa?", "Good afternoon, ready to order?"],
            "evening": ["Selamat petang, jemput order.", "Good evening, what can I get for you?"],
            "night": ["Selamat malam, selamat datang."],
            "default": ["Hai, saya Aisha. Boleh saya ambil pesanan anda?", "Welcome! Nak order apa?"]
        }
        
        candidates = greeting_map.get(time_of_day, greeting_map["default"])
        for text in candidates:
            match = self.find_best_match(text, threshold=0.8)
            if match:
                return match
        return None
    
    def get_menu_item_audio(self, item_name: str) -> dict | None:
        """Find audio for a specific menu item name."""
        # Try direct match
        match = self.find_best_match(item_name + ".", threshold=0.7)
        if match:
            return match
        
        # Try without period
        match = self.find_best_match(item_name, threshold=0.7)
        return match
    
    def _make_result(self, file_id: str, text: str, score: float) -> dict:
        """Create a result dictionary."""
        audio_filename = f"{file_id}.wav"
        audio_path = f"/audio/wavs/{audio_filename}"
        full_path = os.path.join(self.audio_dir, audio_filename)
        
        return {
            "id": file_id,
            "text": text,
            "score": round(score, 3),
            "audio_path": audio_path,
            "audio_exists": os.path.exists(full_path)
        }
    
    def get_all_entries(self) -> list[dict]:
        """Return all available audio entries."""
        return [
            {
                "id": e["id"],
                "text": e["text"],
                "audio_path": f"/audio/wavs/{e['id']}.wav"
            }
            for e in self.entries
        ]
    
    def stats(self) -> dict:
        """Return stats about the audio library."""
        existing = sum(
            1 for e in self.entries 
            if os.path.exists(os.path.join(self.audio_dir, f"{e['id']}.wav"))
        )
        return {
            "total_entries": len(self.entries),
            "audio_files_found": existing,
            "audio_files_missing": len(self.entries) - existing,
            "categories": self._categorize()
        }
    
    def _categorize(self) -> dict:
        """Categorize entries by type."""
        categories = {
            "greetings": 0,
            "roti": 0,
            "naan": 0,
            "nasi": 0,
            "briyani": 0,
            "goreng": 0,
            "drinks": 0,
            "other": 0
        }
        for e in self.entries:
            t = e["text_lower"]
            if any(w in t for w in ["selamat", "welcome", "hai", "hi ", "good "]):
                categories["greetings"] += 1
            elif "roti" in t or "murtabak" in t or "capati" in t or "chappathi" in t:
                categories["roti"] += 1
            elif "naan" in t:
                categories["naan"] += 1
            elif "briyani" in t:
                categories["briyani"] += 1
            elif "nasi goreng" in t:
                categories["goreng"] += 1
            elif "nasi" in t:
                categories["nasi"] += 1
            elif any(w in t for w in ["teh", "kopi", "milo", "air", "bandung", "limau"]):
                categories["drinks"] += 1
            else:
                categories["other"] += 1
        return categories


# === FastAPI Integration ===

def create_voice_routes(app, aisha: AishaVoice):
    """
    Add voice audio routes to an existing FastAPI app.
    
    Usage:
        from aisha_voice import AishaVoice, create_voice_routes
        aisha = AishaVoice()
        create_voice_routes(app, aisha)
    """
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, JSONResponse
    
    @app.get("/api/voice/match")
    async def match_audio(text: str):
        """Find matching audio for given text."""
        match = aisha.find_best_match(text)
        if match:
            return match
        return JSONResponse(
            {"error": "No matching audio found", "text": text},
            status_code=404
        )
    
    @app.get("/api/voice/match-response")
    async def match_response_audio(text: str):
        """Find all matching audio segments in a response."""
        matches = aisha.find_matches_in_response(text)
        return {"matches": matches, "count": len(matches)}
    
    @app.get("/api/voice/greeting")
    async def get_greeting(time_of_day: str = "default"):
        """Get greeting audio."""
        match = aisha.get_greeting(time_of_day)
        if match:
            return match
        return JSONResponse(
            {"error": "No greeting audio found"},
            status_code=404
        )
    
    @app.get("/api/voice/stats")
    async def voice_stats():
        """Get audio library statistics."""
        return aisha.stats()
    
    @app.get("/api/voice/library")
    async def voice_library():
        """List all available audio entries."""
        return {"entries": aisha.get_all_entries()}


# Singleton instance
_aisha_instance = None

def get_aisha(audio_dir: str = "static/audio/wavs", metadata_path: str = "static/audio/metadata.csv") -> AishaVoice:
    """Get or create the AishaVoice singleton."""
    global _aisha_instance
    if _aisha_instance is None:
        _aisha_instance = AishaVoice(audio_dir, metadata_path)
    return _aisha_instance
