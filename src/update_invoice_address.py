"""
Update invoice address in Zoho Books and handle related operations.
This module defines the `update_invoice_address_function` which updates the billing and shipping
"""
from flask import json
import requests
from src.get_invoice import get_invoice_function
import boto3
from datetime import datetime
from src.email import send_failure_email

dynamodb = boto3.resource('dynamodb')

# Function to update invoice address in Zoho Books
def update_invoice_address_function(event):
    client_id = event.get("client_id")
    client_secret = event.get("client_secret")
    refresh_token = event.get("refresh_token")
    org_id = event.get("org_id")
    invoice_number = event.get("InvoiceNumber__c")
    invoice_table = event.get("invoice_table")
    table = dynamodb.Table(invoice_table)

    cloudwatch_payload = {}
    # Validate required fields
    if not all([client_id, client_secret, refresh_token, org_id]):
        return {"error": "Missing required fields: client_id, client_secret, refresh_token, org_id"}
    
    #  State and Country mapping
    state_map = {
        "AN": "Andaman and Nicobar Islands", "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam", "BR": "Bihar", "CH": "Chandigarh", "CT": "Chhattisgarh",
        "DD": "Daman and Diu", "DL": "Delhi", "DN": "Dadra and Nagar Haveli", "GA": "Goa", "GJ": "Gujarat", "HP": "Himachal Pradesh", "HR": "Haryana", "JH": "Jharkhand",
        "JK": "Jammu and Kashmir", "KA": "Karnataka", "KL": "Kerala", "LD": "Lakshadweep", "MH": "Maharashtra", "ML": "Meghalaya", "MN": "Manipur", "MP": "Madhya Pradesh",
        "MZ": "Mizoram", "NL": "Nagaland", "OR": "Odisha", "PB": "Punjab", "PY": "Puducherry", "RJ": "Rajasthan", "SK": "Sikkim", "TN": "Tamil Nadu", "TG": "Telangana",
        "TR": "Tripura", "UP": "Uttar Pradesh", "UT": "Uttarakhand", "WB": "West Bengal"
    }

    country_map = {"IN": "India"}
    
    # Parse payload
    inside_payload = json.loads(event.get("Payload__c"))
    zoho_invoice_id = inside_payload.get("invoice").get("ZohoInvoiceId")


    # Generate access token
    generate_access_token_url = "https://accounts.zoho.in/oauth/v2/token"
    data = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "http://www.zoho.in/books",
        "grant_type": "refresh_token"
    }
    
    token_response = requests.post(generate_access_token_url, data=data)
    # print("Zoho token response:", token_response.text)
    
    # Handle token generation failure
    if token_response.status_code != 200:
        send_failure_email("Zoho Token Generation Failed", "Failed to generate access token for Zoho Books API while updating invoice address.", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Failed to generate access token"}
    
    access_token = token_response.json().get("access_token")
    if not access_token:
        send_failure_email("Zoho Access Token Missing", "Access token not found in response while updating invoice address.", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Access token not found in response"}
    
    # Update billing and shipping address urls
    update_billing_url = f"https://www.zohoapis.in/books/v3/invoices/{zoho_invoice_id}/address/billing?organization_id={org_id}"
    update_shipping_url = f"https://www.zohoapis.in/books/v3/invoices/{zoho_invoice_id}/address/shipping?organization_id={org_id}"
    
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }
    
    # Prepare billing address payload
    billing_payload = {
        "address": inside_payload.get("shipment").get("Bill_To_Address__Street__s") if inside_payload.get("shipment").get("Bill_To_Address__Street__s") else "",
        "city": inside_payload.get("shipment").get("Bill_To_Address__City__s") if inside_payload.get("shipment").get("Bill_To_Address__City__s") else "",
        "state": state_map[inside_payload.get("shipment").get("Bill_To_Address__StateCode__s")] if inside_payload.get("shipment").get("Bill_To_Address__StateCode__s") else "",
        "zip": inside_payload.get("shipment").get("Bill_To_Address__PostalCode__s") if inside_payload.get("shipment").get("Bill_To_Address__PostalCode__s") else "",
        "country": country_map[inside_payload.get("shipment").get("Bill_To_Address__CountryCode__s")] if inside_payload.get("shipment").get("Bill_To_Address__CountryCode__s") else ""
    }
    
    # Update billing address
    response_billing = requests.put(update_billing_url, headers=headers, json=billing_payload)


    # Handle billing address update response
    if response_billing.status_code == 200:
        billing_response = {
            "API_Status": response_billing.status_code,
            "API_Timestamp" : str(datetime.now())
        }
        # Prepare shipping address payload
        shipping_payload = {
            "address": inside_payload.get("shipment").get("Ship_To_Address__Street__s") if inside_payload.get("shipment").get("Ship_To_Address__Street__s") else "",
            "city": inside_payload.get("shipment").get("Ship_To_Address__City__s") if inside_payload.get("shipment").get("Ship_To_Address__City__s") else "",
            "state": state_map[inside_payload.get("shipment").get("Ship_To_Address__StateCode__s")] if inside_payload.get("shipment").get("Ship_To_Address__StateCode__s") else "",
            "zip": inside_payload.get("shipment").get("Ship_To_Address__PostalCode__s") if inside_payload.get("shipment").get("Ship_To_Address__PostalCode__s") else "",
            "country": country_map[inside_payload.get("shipment").get("Ship_To_Address__CountryCode__s")] if inside_payload.get("shipment").get("Ship_To_Address__CountryCode__s") else ""
        }
        # Update shipping address
        response_shipping = requests.put(update_shipping_url, headers=headers, json=shipping_payload)
        
        # Get copies value
        account_obj = inside_payload.get("account") or {}
        copies_value = account_obj.get("invoiceCopies")
        if copies_value is None:
            copies_value = 1

        # Handle shipping address update response
        if response_shipping.status_code == 200:

            get_event = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "org_id": org_id,
                "invoice_number": event.get("InvoiceNumber__c"),
                "invoice_id": zoho_invoice_id,
                "bucket_name": event.get("bucket_name"),
                "invoice_url_prefix": event.get("invoice_url_prefix"),
                "copies": copies_value
            }
            get_result = get_invoice_function(get_event)
            body, status_code = get_result

            # Handle get_invoice_function failure
            if status_code != 200:
                send_failure_email("Zoho Get Invoice Failed", f"Failed to get updated invoice after address update. Error: {body.get('error')}", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
                # return {"error": "Failed to get updated invoice", "details": body}

            # Prepare get_invoice_response
            get_invoice_response = {
                "API_Status": status_code,
                "API_Timestamp" : str(datetime.now())
            }

        else:
            cloudwatch_payload["Shipping_Address_Update_Error"] = response_shipping.text
            send_failure_email("Zoho Update Shipping Address Failed", f"Failed to update shipping address for Zoho Invoice. Error: {response_shipping.text}", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
            # return {"error": "Failed to update shipping address", "details": response_shipping.json()}
        
        # Prepare shipping_response
        shipping_response = {
            "API_Status": response_shipping.status_code,
            "API_Timestamp" : str(datetime.now())
        }

    # Handle billing address update failure
    else:
        send_failure_email("Zoho Update Billing Address Failed", f"Failed to update billing address for Zoho Invoice. Error: {response_billing.text}", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        cloudwatch_payload["Billing_Address_Update_Error"] = response_billing.text
        return cloudwatch_payload

    # Prepare final response
    final_response = {
        "Billing_Address_Update_Response": billing_response,
        "Shipping_Address_Update_Response": shipping_response,
        "Get_Invoice_Response": get_invoice_response
    }

    # Update DynamoDB
    dynamodb_payload = {
        "Invoice_Number": event.get("InvoiceNumber__c"),
        "Update_Address_Response": final_response
    }


    # Perform DynamoDB update
    try:
        dynamodb_payload["Last_Updated_Timestamp"] = str(datetime.now())
        update_fields = {k: v for k, v in dynamodb_payload.items() if k not in ["Invoice_Number"]}
        expression_attribute_names = {f"#{k.replace(' ', '_')}": k for k in update_fields.keys()}
        expression_attribute_values = {f":{k.replace(' ', '_')}": v for k, v in update_fields.items()}
            # Build the UpdateExpression dynamically
        update_expr = "SET " + ", ".join(f"#{k.replace(' ', '_')} = :{k.replace(' ', '_')}" for k in update_fields.keys())

        table.update_item(
            Key={
                "Invoice_Number": event.get("InvoiceNumber__c")
            },
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values
        )

        cloudwatch_payload["DynamoDB_Update"] = "Success"

        return cloudwatch_payload
    except Exception as e:
        send_failure_email("DynamoDB Update Failed", f"Failed to update DynamoDB for invoice: {event.get('InvoiceNumber__c')}. Error: {str(e)}", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        cloudwatch_payload["DynamoDB_Update_Error"] = str(e)
        return cloudwatch_payload