.PHONY: test test-fast test-order test-audio test-api test-promo test-voice coverage

test:
	pytest

test-fast:
	pytest -x --no-cov

test-order:
	pytest tests/test_order_engine.py -v

test-audio:
	pytest tests/test_aisha_voice.py -v

test-api:
	pytest tests/test_api_orders.py -v

test-promo:
	pytest tests/test_promo.py -v

test-voice:
	pytest tests/test_voice_ai.py -v

coverage:
	pytest --cov --cov-report=html
	@echo "Coverage report: coverage_report/index.html"
