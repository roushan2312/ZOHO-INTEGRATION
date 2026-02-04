import requests
from src.get_invoice import get_invoice_function
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')

"""
Do any response in need to send to salesforce?
"""

def update_invoice_shipping_function(event):
    client_id = event.get("client_id")
    client_secret = event.get("client_secret")
    refresh_token = event.get("refresh_token")
    org_id = event.get("org_id")
    invoice_id = event.get("invoice_id")
    invoice_table = event.get("invoice_table")
    table = dynamodb.Table(invoice_table)
    
    if not all([client_id, client_secret, refresh_token, org_id, invoice_id]):
        return {"error": "Missing required fields: client_id, client_secret, refresh_token, org_id, invoice_id"}
    
    generate_access_token_url = "https://accounts.zoho.in/oauth/v2/token"
    data = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "http://www.zoho.in/books",
        "grant_type": "refresh_token"
    }
    
    token_response = requests.post(generate_access_token_url, data=data)
    print("Zoho token response:", token_response.text)
    
    if token_response.status_code != 200:
        return {"error": "Failed to generate access token"}
    
    access_token = token_response.json().get("access_token")
    if not access_token:
        return {"error": "Access token not found in response"}
    
    update_invoice_url = f"https://www.zohoapis.in/books/v3/invoices/{invoice_id}/address/shipping?organization_id={org_id}"
    
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "address": event.get("ShippingAddressStreet__c"),
        "city": event.get("ShippingAddressCity__c"),
        "state": event.get("ShippingAddressState__c"),
        "zip": event.get("ShippingAddressPostalCode__c"),
        "country": event.get("ShippingAddressCountry__c")
    }
    
    response = requests.put(update_invoice_url, headers=headers, json=payload)
    
    print("Zoho update invoice Shipping response:", response.json())
    print("Response status code:", response.status_code)

    update_invoice_response = {
            "API_Status": response.status_code,
            "API_Timestamp" : str(datetime.now())
        }
    
    # After updating Shipping address, optionally call get_invoice_function to fetch PDF (and handle copies/upload)
    if response.status_code == 200:
        get_event = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "org_id": org_id,
            "invoice_id": invoice_id,
            "bucket_name": event.get("bucket_name"),
            "copies": event.get("copies", 1)
        }
        get_result = get_invoice_function(get_event)
        body, status_code = get_result

        get_invoice_response = {
            "API_Status": status_code,
            "API_Timestamp" : str(datetime.now())
        }

        if status_code != 200:
            get_invoice_response["Error_Details"] = body.get("error")
        
        final_api_response = {
            "Update_Invoice_Shipping_Response": update_invoice_response,
            "GET_Invoice_Response": get_invoice_response
        }
        
    else:
        final_api_response = {
            "Update_Invoice_Shipping_Response": update_invoice_response
        }

    # return {
    #     "update_response": response.json(),
    #     "update_status_code": response.status_code,
    #     "get_invoice_result": get_result
    # }
    try:
        table.update_item(
            Key={'Invoice_Number': event.get("invoice_number")},
            UpdateExpression="SET Update_Invoice = :u",
            ExpressionAttributeValues={
                ':u': final_api_response
            }
        )
        return {
            "message": "Shipping address updated and DynamoDB updated successfully",
            "update_status_code": response.status_code,
            "get_invoice_result": get_result
        }
    except Exception as e:
        return {"error": f"Failed to update DynamoDB: {str(e)}"}