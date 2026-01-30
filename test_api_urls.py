"""
Тест доступности разных API URLs
"""

import requests
import sys

urls_to_test = [
    'https://portals-market.com/api',
    'https://api.portals.fi',
    'https://portals.fi/api',
    'https://api.portals.fi/v1',
]

print("Testing API URLs...")
print("=" * 60)

for url in urls_to_test:
    try:
        print(f"\nTesting: {url}")
        # Пробуем простой GET запрос
        response = requests.get(url, timeout=5)
        print(f"  Status: {response.status_code}")
        print(f"  OK")
    except requests.exceptions.ConnectionError as e:
        print(f"  FAIL: Connection error - {str(e)[:50]}")
    except requests.exceptions.Timeout:
        print(f"  FAIL: Timeout")
    except Exception as e:
        print(f"  FAIL: {str(e)[:50]}")

