# api_payloads.py
# This module contains the direct API payloads for extracting jobs from protected consultancies

def get_payload(provider_name: str, page: int, results_per_page: int) -> dict | None:
    \"\"\"
    Returns a dictionary containing:
    {
        "url": str,
        "method": str,
        "headers": dict,
        "data": str | dict (for POST)
    }
    \"\"\"
    
    if provider_name == 'synergie':
        return {
            "url": "https://www.synergie.es/wp-admin/admin-ajax.php",
            "method": "POST",
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest"
            },
            # TODO: Add exact action from the hunter results
            "data": f"action=xxx&page={page}"
        }
        
    # Will add other providers once the hunter finishes
    
    return None
