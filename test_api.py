"""
Скрипт для тестирования работы с Portals API
Используйте для проверки и адаптации под реальный API
"""

import asyncio
import json
from config import API_ID, API_HASH
from portalsmp import update_auth, search, filterFloors


async def test_api():
    """Tests API data retrieval"""
    print("Testing Portals API...")
    
    # Test authentication
    print("\n1. Testing authentication...")
    auth_token = await update_auth(API_ID, API_HASH)
    
    if auth_token:
        print(f"Authentication successful. Token: {auth_token[:20]}...")
    else:
        print("Authentication failed. Check API_ID and API_HASH")
        return
    
    # Test search
    print("\n2. Testing gift search...")
    items = search(
        gift_name=["test"],  # Replace with real name
        model=[],
        limit=5,
        sort="price_asc",
        authData=auth_token
    )
    
    if isinstance(items, str):
        print(f"API Error: {items}")
        return
    
    if isinstance(items, dict) and "items" in items:
        items = items["items"]
        print(f"Received {len(items)} gifts")
        
        if items:
            print("\nFirst gift:")
            print(json.dumps(items[0], indent=2, default=str))
            
            # Test filtering
            print("\n3. Testing floor price filtering...")
            filtered = filterFloors(items, min_floor_price=0, max_floor_price=1000)
            print(f"Filtered {len(filtered)} gifts")
    else:
        print("Unexpected response format")


if __name__ == "__main__":
    asyncio.run(test_api())

