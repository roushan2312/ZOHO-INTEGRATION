import requests

def run_create(event):
    # Your create logic here
    # def handle_event(event):
    # client_id = "1000.DMZKLD5JA20XDVRL71F18K3BQAXUFJ"
    client_id = event.get("client_id")
    client_secret = event.get("client_secret")
    refresh_token = event.get("refresh_token")
    ORG_ID = event.get("ORG_ID")
    url = "https://accounts.zoho.in/oauth/v2/token"
    data = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "http://www.zoho.in/books",
        "grant_type": "refresh_token"
    }
    token_response = requests.post(url, data=data)
    # Optionally, you can print or log the response
    print("Zoho token response:", token_response.text)
    ACCESS_TOKEN = token_response.json().get("access_token")
    create_url = f"https://www.zohoapis.in/books/v3/invoices?organization_id={ORG_ID}"
    print("Hello")
    headers = {
        "Authorization": f"Zoho-oauthtoken {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "customer_id": event.get("customer_id"),
        "line_items": [
            {
                "name": "Invoice Service",
                "rate": 500,
                "quantity": 1
            }
        ]
    }

    response = requests.post(create_url, headers=headers, data=json.dumps(payload))
    print("Zoho create invoice response:", response.text)
    print("Response status code:", response.status_code)
    return response.text
    # return "Create logic executed"